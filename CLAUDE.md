# Projet Fraud Detection — Jedha RNCP7 AIA Bloc 3

## Contexte

Certification Jedha RNCP7 Bloc 3 AIA : pipeline ML de détection de fraude en production.
Specs : `specs.md` — source de vérité unique pour toutes les phases.
Bugs rencontrés + solutions (détail) : `docs/troubleshooting.md`.

## Infrastructure

- **MLFlow** (déployé) : `https://gviel-mlflow37.hf.space/`
- **API de prédiction** (déployée sur Render, 2026-07-06) : `https://jedha-aia-03-frauddetection.onrender.com`
- **Dashboard de suivi** (déployé sur Streamlit Community Cloud, 2026-07-06) :
  `https://jedha-aia-03-frauddetection-vs7adfbiy54amcv5jqy3gc.streamlit.app/`
- **PgSQL prod** (Neon, projet `fraud-detection-db`) : chaîne de connexion dans `DATABASE_URL_PROD`
- **S3 artifact store MLFlow** : bucket `aws-s3-mlflow`, région `eu-west-3` (modèles)
- **S3 transactions/training** : bucket `bucket-fraud-detection-gviel`, région `eu-west-3`
  (Phase 5 — `bucket-fraud-detection` demandé par specs.md était déjà pris globalement,
  suffixe `-gviel` ajouté pour l'unicité)
- **Credentials** : `.env.test` + `.env.production` racine (non commités — `.env.template` commité
  documente toutes les variables et explique les 3 contextes : stack de test locale, stack
  Airflow locale, API Render/dashboard Streamlit Cloud). `api/.env` existe mais n'est lu par aucun
  chemin de code actuel (Makefile lance `uvicorn` depuis la racine, `load_dotenv()` y trouve donc
  `.env.test`) — fichier vestigial, à ignorer.

## Conventions env vars

| Variable | Valeurs | Usage |
|----------|---------|-------|
| `MODEL_ENV` | `test` \| `prod` \| `staging` | Mode de chargement du modèle |
| `MLFLOW_URI` | URL | Tracking server MLFlow (`api/app.py`, `src/train.py --env prod`, `dags/tasks/train_model.py:_new_model_is_global_best`). Lu uniquement pour un entraînement `--env prod` — `src/train.py --env test` ignore cette variable et pointe toujours vers un store SQLite local `work/mlflow_local.db` (jamais poussé, pour ne pas polluer l'expérience hébergée partagée avec la prod ; cf. specs.md §1.2). Pour la même raison, `dags/tasks/train_model.py::train()` ne compare/relance l'API que si `APP_ENV=="prod"` |
| `MODEL_STATUS` | `best` | Tag MLFlow à filtrer |
| `MODEL_NAME` | `fraud_detection` | Nom expérience MLFlow |
| `MODEL_PATH` | chemin pkl | Modèle local en mode test |
| `APP_ENV` | `test` \| `prod` | Mode des DAGs Airflow (`dags/config.py`) — bascule `DATABASE_URL` |
| `DATABASE_URL_PROD` | URL PgSQL Neon | `.env.production` racine ; utilisée par `airflow/start.sh` quand `APP_ENV=prod` (DAGs 3.1/3.2 → Neon au lieu de fraud-db local) |
| `MODEL_RELOAD_TOKEN` | secret partagé | Protège `POST /reload-model` (`api/app.py`) — même valeur côté API et côté DAG 3.3 (`dags/tasks/train_model.py`), sinon 403 |

## Features du modèle

**16 features** : `amt, zip, lat, long, city_pop, merch_lat, merch_long, distance_km, diff_avg_amt, hour, dow, gender, state, category, merchant, job`

**Catégorielles** (LabelEncoder) : `gender, state, category, merchant, job, zip` — `zip` traité
comme catégorielle (pas numérique) depuis le 2026-07-06, cf. piège Render ci-dessous.

`diff_time` a été supprimée — valeur constante (-220 924 800s), sans pouvoir prédictif.

`diff_avg_amt` = montant de la transaction moins le montant moyen historique du client
(`id_client = last_first_gender_dob_zip`). Calculée par `src/prepare_dataset.py`,
qui sauvegarde aussi `work/client_trx_analysis.csv` (`id_client, avg_mnt, avg_frequency`) — l'API
recharge ce fichier au démarrage (`CLIENT_STATS_PATH`) pour recalculer la feature à
l'inférence, avec repli sur la moyenne globale pour un client inconnu.

## Reload du modèle à chaud (`POST /reload-model`)

`api/app.py` expose `POST /reload-model?token=...` pour recharger le modèle (MLFlow en
prod/staging, pkl local en test) et `client_trx_analysis.csv` sans redémarrer le service.
Protégé par un secret partagé `MODEL_RELOAD_TOKEN` (même valeur des deux côtés, sinon 403 —
pas d'auth utilisateur, cf. table des env vars ci-dessus). Déclenché par le DAG 3.3
(`dags/tasks/train_model.py`, fonction `_trigger_api_reload`) après un entraînement réussi,
**mais seulement si le nouveau modèle est devenu le meilleur global** — `src/train.py` tague
toujours le meilleur modèle de CE run en `status=best` (même s'il est moins bon que le meilleur
historique), donc `_new_model_is_global_best()` compare le run `status=best` le plus récent au
run `status=best` ayant le plus haut `pr_auc` toutes exécutions confondues (celui que l'API
chargerait réellement, cf. `_load_from_mlflow`) — reload déclenché seulement si c'est le même
run (vérifié : sur l'historique réel du projet, un run plus ancien avec pr_auc=0.839 reste
supérieur au dernier run pr_auc=0.799, donc pas de reload). Best-effort dans tous les cas (une
erreur de reload est loggée mais ne fait pas échouer la tâche, l'entraînement ayant déjà réussi).

⚠️ **Piège découvert en déployant sur Render (2026-07-06)** : la sélection par pr_auc maximum
parmi tous les runs `status=best` ne garantit **ni** la fraîcheur **ni** la compatibilité de
schéma avec le code d'inférence actuel. En ajoutant `zip` aux features catégorielles
(`CAT_FEATURES`, cf. ci-dessous), un run plus ancien (pr_auc=0.8907, sans encoder `zip`) restait
mieux classé qu'un nouveau run compatible (pr_auc=0.8875) — l'API chargeait donc un modèle
incompatible avec son propre code, crash `ValueError: pandas dtypes must be int, float or bool`
sur `zip`. **Chaque run d'entraînement de CE projet (test ou prod, tout au long des sessions de
debug) tague toujours son propre meilleur modèle `status=best`, sans jamais comparer aux runs
historiques ni les retaguer** — les runs `best` s'accumulent indéfiniment (30 dans l'historique
réel à ce jour) et un changement de schéma de features peut rendre les runs anciens invalides
tout en les laissant sélectionnables. Pas de garde-fou automatique dans le code contre ce cas :
si le schéma de features change, il faut retaguer manuellement (`status=superseded` par ex.) les
runs `best` devenus incompatibles avec un pr_auc supérieur, sans quoi ils resteront chargés.

## Entraînement (`config/models.yaml`)

- **4 modèles actifs** : `logistic_regression_balanced`, `xgboost_binary`, `lightgbm_unbalanced`,
  `random_forest_balanced`. `OneClassSVM` a été testé puis retiré (peu performant sur ce dataset,
  voir specs.md) ; `catboost_balanced` a aussi été retiré (générait `catboost_info/` à la racine
  sans gain notable — cf. `.gitignore`).
- `test_size` (global, défaut 0.2) et `resampling` (global : `none` \| `under_sample` \| `smote`,
  appliqué **après** le split train/test, jamais avant) sont des clés de config top-level, pas
  par-modèle — voir les commentaires dans `config/models.yaml` pour le détail des paramètres.

## Architecture des fichiers

```
src/prepare_dataset.py               # CSV brut → work/fraudTest_prepared.csv
src/train.py                         # Entraînement + MLFlow logging
src/requirements.txt                 # Deps communes préparation + entraînement
config/models.yaml                   # 5 modèles + test_size + resampling
api/app.py                           # FastAPI /predict + /health
api/schemas.py                       # Pydantic Transaction + PredictionResponse
dashboard/app.py                     # Dashboard Streamlit de suivi (specs.md Phase 6)
dags/dag_realtime.py                 # DAG Airflow temps réel (1/min) — augment_training_data en //
dags/dag_daily_report.py             # DAG rapport quotidien
dags/dag_train_model.py              # DAG 3.3 : entraînement (prepare/train en subprocess)
dags/config.py                       # Config partagée des DAGs
dags/tasks/                          # Tâches extraites des DAGs
airflow/Dockerfile                   # Image Airflow custom (+ libgomp1 + deps ML src/requirements.txt)
Makefile                             # make venv | prepare | train | api
```

Airflow (`airflow/docker-compose.yml`) tourne en **LocalExecutor** (pas de Celery/Redis —
inutile pour 1 transaction/minute). Le DAG 3.3 exécute `prepare_dataset.py`/`train.py` en
**subprocess directement dans le conteneur `airflow-scheduler`** (specs.md Phase 4 : "pas de
déport Docker dans un conteneur Docker car trop complexe") — plus de conteneur `fraud-train`
séparé ni de docker-outside-of-docker. L'image Airflow est buildée depuis `airflow/Dockerfile`
(ajoute `libgomp1` + les deps de `src/requirements.txt` à l'image officielle `apache/airflow`),
et monte `../src` + `../config` (racine) en plus des volumes habituels.

`fraud_detect` (DAG 3.1) est un `BranchPythonOperator` qui retourne une **liste** de task_ids
(`[branche_alerte_ou_end, "augment_training_data"]`) — pattern Airflow standard pour déclencher
plusieurs tâches en parallèle depuis un seul branchement. `augment_training_data` (toujours
exécutée, indépendamment du résultat fraude) génère une transaction synthétique dérivée de
chaque transaction collectée (nouveau `trans_num`, montant perturbé ±10-20%, `is_fraud` recopié
de la transaction de base — la vérité terrain fournie par l'API Jedha, **pas** la prédiction de
`fraud_detect` qui écrase ce même champ dans son propre XCom `fraud_result`) et l'ajoute à
`work/fraudTest.csv`. Fait grossir ce fichier au fil du temps pour déclencher la branche
"prepare" du DAG 3.3 (`work/fraudTest.csv` > `data/fraudTest.csv` en nombre de lignes, cf.
specs.md §3.3). Ne fait rien si `work/fraudTest.csv` n'existe pas encore (DAG 3.3 pas encore
initialisé — pas de copy_data fait, cf. `dags/tasks/augment_training_data.py`).

## Règles de développement

- **Ne jamais installer de libs Python dans le système ou conda** — toujours `requirements.txt` + venv
- Venv principal : `.venv/` (make venv)
- Logs : `work/logs/` (gitignored)
- Sorties intermédiaires : `work/` (gitignored)
- Modèles locaux : `model/` (gitignored)
- **Toute image basée sur `python:3.12-slim` ou `apache/airflow` qui installe LightGBM doit
  `apt-get install libgomp1`** (absent des deux images de base, sinon `OSError: libgomp.so.1`
  au chargement — vérifié aussi sur `apache/airflow:3.2.2`) — voir `api/Dockerfile` et
  `airflow/Dockerfile`.
- **`scikit-learn`/`xgboost`/`lightgbm` doivent avoir la même version épinglée dans
  `src/requirements.txt` (entraînement, DAG 3.3 en subprocess dans le conteneur Airflow) et
  `api/requirements.txt` (inférence)** — un `LabelEncoder`/modèle picklé avec une version puis
  dépicklé avec une autre déclenche `InconsistentVersionWarning` (voire des résultats invalides).
  Si l'un des deux fichiers change une version, répercuter sur l'autre.
- **`api/Dockerfile` installe aussi `curl`** (en plus de `libgomp1`) — requis par le
  `healthcheck` Docker (`docker-compose.yml`), absent de `python:3.12-slim`.

## Gotchas stack Airflow (trouvés en démarrant `./airflow/start.sh` pour de vrai)

Ces bugs n'existaient pas dans le code applicatif — ils viennent tous du fait que la stack
Airflow (`airflow/docker-compose.yml`) n'avait jamais été réellement démarrée avant. Tous corrigés :

- **`airflow-init` (migration DB) plantait en `ModuleNotFoundError: No module named 'airflow'`** :
  son `entrypoint: /bin/bash` court-circuite le script officiel de l'image qui configure
  `PYTHONPATH` pour le pip install `--user` d'Airflow. Combiné à `user: "0:0"` (HOME=/root),
  `airflow` ne se retrouvait plus lui-même. Fix : `HOME: /home/airflow` forcé dans
  l'environnement d'`airflow-init`.
- **Toutes les tâches échouaient en `Invalid auth token: Signature verification failed`** :
  Airflow 3.x signe les JWT échangés entre le scheduler (émetteur) et l'apiserver (vérificateur,
  execution API) avec `[api_auth] jwt_secret`. Non défini, chaque conteneur génère sa propre
  clé aléatoire → les tokens ne se valident jamais entre conteneurs différents. Fix :
  `AIRFLOW__API_AUTH__JWT_SECRET` fixé et identique sur tous les composants Airflow dans
  `airflow-common-env`. (Attention à ne pas confondre avec `[api] secret_key` — mauvaise piste
  suivie une première fois, sans effet.)
- **`fetch_trx.py` : double encodage JSON** — l'API Jedha renvoie une chaîne JSON (donc
  `resp.json()` donne déjà le texte JSON, pas un dict) ; le code faisait `json.dumps(resp.json())`
  qui ré-échappait cette chaîne, cassant `pd.read_json(..., orient="split")` en aval
  (`AttributeError: 'str' object has no attribute 'items'`). Fix : passer `resp.json()`
  directement à `pd.read_json`.
- **`fetch_trx.py` : `current_time` devenait un `pd.Timestamp`** — `pd.read_json` détecte
  automatiquement les colonnes au nom évocateur d'une date et les convertit, cassant la
  sérialisation JSON du XCom (`current_time` doit rester un entier epoch ms, comme attendu par
  `store_trx.py` et `api/schemas.py`). Fix : `pd.read_json(..., convert_dates=False)`.
- **docker-compose v1.29.2 (vs `docker compose` v2)** : `start.sh`/`stop.sh` détectent
  automatiquement lequel est disponible. Sur `docker-compose` v1 avec un daemon Docker récent,
  `--force-recreate` et `up` sur un conteneur au nom déjà pris (même arrêté) déclenchent des
  bugs internes (`KeyError: 'id'`, `KeyError: 'ContainerConfig'`) — si ça arrive, `docker rm -f`
  le(s) conteneur(s) concerné(s) puis relancer `up` (sans `--force-recreate`) plutôt que
  d'insister sur la recréation en place.
- **`model/best_model.pkl` jamais mis à jour par le DAG 3.3 en mode test** (trouvé le
  2026-07-06, après plusieurs cycles d'entraînement qui semblaient "fonctionner") : le service
  `airflow-scheduler` ne montait pas `../model`, alors que `train.py --env test` sauvegarde
  toujours dans `MODEL_DIR = Path("model")` (chemin relatif, résolu à `/opt/airflow/model` —
  cwd du conteneur). Ce répertoire était donc **local et éphémère au conteneur scheduler**,
  jamais partagé avec l'hôte ni avec `fraud-detection-api` (qui monte `../model:/app/model:ro`
  depuis l'hôte). Le modèle entraîné n'atteignait donc jamais l'API — `/reload-model` semblait
  fonctionner (200 OK) mais rechargeait toujours l'ancien fichier hôte, inchangé depuis le
  4 juillet. Fix : ajout de `../model:/opt/airflow/model` aux volumes de `airflow-common` dans
  `airflow/docker-compose.yml`, vérifié en confirmant le mtime du fichier hôte après un run réel
  du DAG 3.3 et un reload API reflétant bien le nouveau modèle.

## État des phases

- **Phase 1** ✅ — dataset complet (555 719 lignes) rejoué avec `diff_avg_amt` + resampling +
  4 modèles actifs (`make prepare && make train`, ou en subprocess via le DAG 3.3)
- **Phase 2** ✅ — FastAPI `api/app.py` implémentée, testée en conteneur Docker
  (`fraud_api_test`, build + `/health` + `/predict` avec le modèle réel)
- **Phase 3** ✅ — DAGs Airflow implémentés (realtime, daily_report, train_model 3.3 en subprocess)
- **Phase 4** ✅ — tests unitaires (`tests/`, `make test` ; ne couvrent que `src/`, les tests
  unitaires des scripts DAG restent différés, cf. specs.md), API testée en conteneur
  (`fraud_api_test`), stack Airflow démarrée pour de vrai via `./airflow/start.sh`
  (`fraud_detection_api_cicd`) avec les 3 DAGs vérifiés sans erreur d'import et
  `fraud_detection_realtime` exécuté de bout en bout (fetch_trx → store_trx → fraud_detect →
  end, transaction bien écrite en PgSQL locale). `gen_daily_report` (DAG 3.2) et
  `send_fraud_alert_email` (DAG 3.1) testés avec SMTP Gmail réel (email de rapport + email
  d'alerte reçus) — `send_fraud_alert_email` vérifié via un contexte XCom simulé (score forcé
  ≥ seuil), pas encore déclenché organiquement par une vraie transaction frauduleuse.
- **Phase 5** ⏳ — Déploiement prod (specs.md : MLFlow HF, API Render, PgSQL Neon, **Airflow
  reste en local** — DAG 3.3 toujours en subprocess, pas d'EC2/conteneur dédié "à ce stade").
  Fait et testé de bout en bout : projet Neon `fraud-detection-db` (table
  `real_time_transactions`) créé via le MCP Neon ; bascule `APP_ENV=prod ./airflow/start.sh`
  câblée et vérifiée — les DAGs 3.1/3.2 écrivent/lisent bien sur Neon (au lieu du fraud-db
  local) et sur le bucket S3 `bucket-fraud-detection-gviel` (transactions temps réel, distinct
  de `aws-s3-mlflow`) une fois relancés en mode prod. Encore ouvert :
  - **Déploiement API sur Render** ✅ — fait et vérifié en production :
    `https://jedha-aia-03-frauddetection.onrender.com`, `/health` → `ready`, `/predict` testé
    avec succès (payload minimal et payload complet). Voir `docs/travail/render_deployment.md`.
    Note : l'auto-deploy sur push ne se déclenche pas de façon fiable sur ce service — un
    "Manual Deploy" depuis le dashboard Render est nécessaire après chaque push impactant l'API.
  - **Sync S3 des artefacts d'entraînement** ✅ — automatisée le 2026-07-06, 2 points de
    synchronisation distincts (pas un seul, cf. correction du 2026-07-06 : synchroniser
    uniquement au cycle du DAG 3.3 rendrait `work/fraudTest.csv` obsolète entre deux
    entraînements, vu qu'il est modifié à chaque collecte de transaction, pas à chaque training) :
    - `dags/tasks/augment_training_data.py` (DAG 3.1, à chaque transaction collectée) uploade un
      snapshot de `work/fraudTest.csv` sur S3 juste après l'avoir modifié localement — c'est la
      seule task qui écrit ce fichier, donc le seul endroit pertinent pour le synchroniser.
    - `dags/tasks/train_model.py::train()` (DAG 3.3, une fois l'entraînement réellement terminé,
      pas juste `prepare()`) uploade `work/client_trx_analysis.csv` sur S3, indépendamment du
      résultat de `_new_model_is_global_best()` (les stats client ne sont pas liées à un run
      précis) — requis par l'API (Render, pas d'accès au disque local).
    Dans les deux cas : `bucket-fraud-detection-gviel`, préfixe `work/`, uniquement en
    `APP_ENV=prod`, upload best-effort (`try/except`, log un warning, ne fait pas échouer la
    task). `data/fraudTest.csv`, `work/fraudTest.csv` et `work/fraudTest_prepared.csv` restent des
    fichiers **locaux en permanence** (Airflow reste local) ; `work/fraudTest_prepared.csv` n'est
    jamais uploadé (fichier intermédiaire local uniquement, aucun composant distant n'en a besoin).
  - **`api/app.py`** sait maintenant télécharger `client_trx_analysis.csv` depuis S3 au
    démarrage quand `MODEL_ENV` vaut `prod`/`staging` (`_download_client_stats_from_s3`,
    clé `work/client_trx_analysis.csv`), avec repli gracieux (moyenne globale à 0.0, pas de
    crash) si le fichier est absent — testé dans les deux cas (fichier absent → 404 avalé ;
    fichier présent → 924 clients chargés).
- **Phase 6** ✅ — Dashboard de suivi Streamlit (`dashboard/app.py`) : implémenté et testé en
  Docker (`fraud_dashboard_test`, service dans `airflow/docker-compose.yml`, rejoint `fraud-db`
  et `fraud-detection-api` via le réseau Docker interne). Transactions du jour (plus récente en
  premier), filtre par jour et par niveau de fraude (code couleur rouge/orange/jaune/vert),
  panneau statut API/modèle via `/health` (étendu avec `model_name`/`api_version`). Affiche aussi
  `distance_km` (recalculée dans le dashboard depuis `lat`/`long`/`merch_lat`/`merch_long`, déjà en
  base) et `diff_avg_amt` (calculée par l'API à l'inférence, renvoyée par `/predict` — champ ajouté
  à `PredictionResponse` — et persistée par `fraud_detect.py` dans une colonne
  `real_time_transactions.diff_avg_amt`, `ALTER TABLE ADD COLUMN IF NOT EXISTS` car la table existe
  déjà en prod Neon ; `NULL` pour les transactions collectées avant ce changement). Déployé en
  prod sur Streamlit Community Cloud (2026-07-06) :
  `https://jedha-aia-03-frauddetection-vs7adfbiy54amcv5jqy3gc.streamlit.app/` — secrets
  `DATABASE_URL` (valeur de `DATABASE_URL_PROD`, Neon) et `FRAUD_API_URL` (URL Render) configurés
  côté dashboard Streamlit Cloud, pas dans un fichier local.

## Modèles entraînés (2026-07-06, dataset complet, post hyperparameter tuning + SMOTE désactivé)

5 modèles actifs (`config/models.yaml`) suite à deux ablations réelles le même jour (cf. mémoire
Claude Code `project_smote_ablation_findings`) :
1. Hyperparameter tuning (10 variantes xgboost/lightgbm) : `lightgbm_unbalanced` passé de
   `n_estimators=200` à `500`, et `lgbm_slow_more_leaves` (n_estimators=800, num_leaves=127,
   learning_rate=0.02) ajouté comme 5e modèle. Une variante `lgbm_more_trees` a été ajoutée puis
   retirée dans la foulée (doublon confirmé empiriquement avec `lightgbm_unbalanced`).
2. `resampling.method` passé de `smote` (0.1, k=5) à **`none`** : une ablation "sans resampling"
   avec les nouveaux hyperparamètres a montré un gain massif supplémentaire (`lgbm_slow_more_leaves`
   : pr_auc 0.8316→0.8794, **f1 0.541→0.790, precision 0.392→0.748**) — décision explicite de
   l'utilisateur après avoir vu ce résultat combiné (avait dit "pas pour l'instant" à la première
   ablation resampling seule, plus tard changé d'avis).

| Statut | Modèle | PR-AUC | ROC-AUC |
|--------|--------|--------|---------|
| best | lgbm_slow_more_leaves (n_estimators=800, num_leaves=127, lr=0.02) | 0.8794 | 0.9971 |
| challenger | lightgbm_unbalanced (n_estimators=500) | 0.8471 | 0.9662 |
| challenger | xgboost_binary | 0.8402 | 0.9969 |
| challenger | random_forest_balanced | 0.7061 | 0.9928 |
| worst | logistic_regression_balanced | 0.1822 | 0.8898 |
