# Accès AWS (IAM) — Fraud Detection

L'API et le DAG Airflow lisent et écrivent dans S3. Ils utilisent **leur propre clé AWS**, rattachée à un user
IAM dont les droits sont limités à ce que le code fait réellement. Aucun `AmazonS3FullAccess`, aucune clé
partagée avec un autre projet.

Pourquoi : une clé AWS d'un autre projet de ce compte a fuité dans un dépôt GitHub public (sortie d'un
notebook qui affichait `os.environ`) et a dû être révoquée. Chaque projet a depuis son user IAM dédié, pour
qu'une fuite n'ouvre que les données de ce projet.

## Qui utilise quoi

| User IAM | Fichiers locaux | Clés (variables) |
|---|---|---|
| `fraud-detection` | `api/.env`, `api/.env.production`, `airflow/.env.production` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` |

En environnement de test (`MODEL_ENV=test`, `APP_ENV=test`), aucune clé AWS n'est nécessaire : le modèle est
chargé depuis un fichier local, MLflow est un SQLite local et les transactions restent dans `work/`. Les
variables `AWS_*` sont alors laissées vides. Le `dashboard` ne connaît pas S3.

Région : `eu-west-3`. Deux buckets :

| Bucket | Contenu |
|---|---|
| `bucket-fraud-detection-gviel` | `work/` (`client_trx_analysis.csv`, `fraudTest.csv`) et `<YYYYMMDD>/trx-<horodatage>_<trans_num>.json` (transactions temps réel) |
| `aws-s3-mlflow` | `mlflow-artifacts/` : artefacts et modèles du serveur MLflow partagé (Hugging Face Space) |

Le serveur MLflow est lancé avec `--default-artifact-root s3://…` sans proxy d'artefacts : **les clients
(`api`, entraînement Airflow) lisent et écrivent directement dans S3** avec leur propre clé.

| Composant | Code | Opération S3 | Droit requis |
|---|---|---|---|
| `api` | `api/app.py` | télécharge `work/client_trx_analysis.csv` | `s3:GetObject` |
| `api` | `mlflow.sklearn` (si `MODEL_ENV=prod\|staging`) | liste et lit le modèle `aws-s3-mlflow/mlflow-artifacts/…` | `s3:ListBucket` (préfixe `mlflow-artifacts/`) + `s3:GetObject` |
| `airflow` | `dags/tasks/store_trx.py` | dépose `<YYYYMMDD>/trx-….json` (`put_object`) | `s3:PutObject` |
| `airflow` | `dags/tasks/augment_training_data.py` | dépose `work/fraudTest.csv` | `s3:PutObject` |
| `airflow` | `dags/tasks/train_model.py` | dépose `work/client_trx_analysis.csv` | `s3:PutObject` |
| `airflow` | `src/train.py` (`log_model`, `log_artifact`) | écrit le modèle dans `aws-s3-mlflow/mlflow-artifacts/…` | `s3:PutObject` (+ lecture pour comparer les runs) |

## Policy du user (inline `fraud-detection-rw`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FraudWorkReadWrite",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::bucket-fraud-detection-gviel/work/*"
    },
    {
      "Sid": "FraudTransactionsWrite",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::bucket-fraud-detection-gviel/20*/trx-*.json"
    },
    {
      "Sid": "MlflowArtifactsReadWrite",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::aws-s3-mlflow/mlflow-artifacts/*"
    },
    {
      "Sid": "MlflowArtifactsList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::aws-s3-mlflow",
      "Condition": {
        "StringLike": { "s3:prefix": ["mlflow-artifacts/*", "mlflow-artifacts/"] }
      }
    }
  ]
}
```

Pas de `s3:DeleteObject`, pas de `s3:ListBucket` sur le bucket des transactions (le code ne le liste pas), pas
d'accès aux autres buckets du compte.

Amélioration possible : séparer deux users (`fraud-detection-api` en lecture seule, `fraud-detection-airflow`
en lecture/écriture), comme pour VitiScan, si l'API est exposée sur Internet.

## Créer ou renouveler la clé

À faire avec un profil administrateur. La clé est écrite dans un fichier lisible par vous seul : elle ne
s'affiche ni dans le terminal ni dans l'historique du shell, et ne doit jamais être collée dans un chat.

```bash
umask 077
aws iam create-access-key --user-name fraud-detection \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text > fraud-detection.key
```

Reporter l'identifiant et le secret dans **les trois** fichiers (`api/.env`, `api/.env.production`,
`airflow/.env.production`) et, si l'API ou Airflow sont hébergés, dans leurs variables d'environnement, puis
détruire le fichier (`shred -u fraud-detection.key`). Pour renouveler : créer la nouvelle clé, mettre à jour
tous les endroits, redémarrer, vérifier, puis supprimer l'ancienne (`aws iam delete-access-key`).

## Vérifier la clé (sans modifier de données)

```bash
set -a; source api/.env.production; set +a
aws sts get-caller-identity --query Arn --output text                                  # doit afficher fraud-detection
aws s3 cp s3://bucket-fraud-detection-gviel/work/client_trx_analysis.csv - | head -2    # doit réussir
aws s3api list-objects-v2 --bucket aws-s3-mlflow --prefix mlflow-artifacts/ --max-items 2   # doit réussir
aws s3 ls s3://bucket-fraud-detection-gviel/                                           # doit être refusé (AccessDenied)
aws s3 ls s3://aws-s3-mlflow/                                                          # doit être refusé
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN                        # avant de repasser en admin
```

Test applicatif : lancer l'API avec `MODEL_ENV=prod` (le modèle doit se charger depuis MLflow et les stats
client se télécharger), puis déclencher un DAG qui dépose une transaction et un entraînement.

Sans clé, le simulateur IAM évalue la policy sans rien écrire :

```bash
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::<ID_COMPTE>:user/fraud-detection \
  --action-names s3:PutObject --resource-arns arn:aws:s3:::bucket-fraud-detection-gviel/20260101/trx-x.json
```

## Une erreur 403 / AccessDenied

Lire le message : il nomme l'**action** et la **ressource** refusées. Si l'accès est légitime, ajouter cette
action sur cette ressource à la policy, au plus juste.

- `HeadObject` / téléchargement d'un fichier absent : sans `s3:ListBucket`, S3 renvoie **403** au lieu de 404.
  Vérifier d'abord que la clé (le chemin) existe.
- Chargement ou enregistrement d'un modèle MLflow refusé : les clients accèdent directement à
  `aws-s3-mlflow/mlflow-artifacts/` ; vérifier les statements `MlflowArtifacts*`.
- Écriture d'une transaction refusée : la clé a le format `<YYYYMMDD>/trx-<…>.json` à la racine du bucket, pas
  sous `work/`.
- `InvalidAccessKeyId` / `InvalidClientTokenId` (et non `AccessDenied`) : la clé n'existe plus. Mettre à jour
  les trois fichiers `.env` et les variables d'environnement des services hébergés, puis redémarrer.

## Règles

- Une clé par projet, jamais de clé partagée.
- Pas d'`AdministratorAccess` ni de `*FullAccess`, pas de `s3:*`, pas de ressource `*`.
- `.env*` reste hors git (`.gitignore`) et en `600`. Ne jamais afficher `os.environ` dans un notebook.
- Activer le *secret scanning* et la *push protection* GitHub sur le dépôt.
