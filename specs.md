# JEDHA - Project Fraud detection - bloc 3

Certification RNCP7 AIA

Enoncé du projet dans : @docs/enonce/ENONCE.md

---

## Ressources

- @data/fraudTest.csv : dataset historique "fraudlent payment" qui contient un grand nombre de paiements labellisés (frauduleux ou non) à utiliser pour entraîner l'algorithme de détection de fraude
- Real-time payment API : https://huggingface.co/spaces/sdacelo/real-time-fraud-detection
    - fournit en (pseudo) temps réel (mise à jour toutes les minutes) des transactions de paiement en cours
    - Endpoint : /current-transactions
    - @data/response_example.json : contient un exemple de réponse de l'API 
- MCP serveurs :
    - mcp-julie : pour récupérer des choses sur le site JEDHA
    - mcp-neon : pour interagir avec une base de données PostgreSQL hébergée sur Néon (le nom du CLI est maintenant neon et non plus neonctl -> faire l'update si nécessaire)
- CLI :
    - AWS : aws-cli/2.35.15 Python/3.14.5 Linux/6.17.0-35-generic exe/x86_64.ubuntu.24
    - GH : gh version 2.93.0 (2026-05-27) https://github.com/cli/cli/releases/tag/v2.93.0

---

## Structure du projet

- data : contenant les données pour le projet
- work : répertoire de travail
- model : contient le best model en local pour les tests
- docs/enonce : contient des documents pour l'énoncé du projet
- on ignore pour l'instant le notebook + env_ml.yaml
- on a plusieurs modules
    - des scripts python de préparation+cleaning du dataset et training de modèle qui peuvent etre lancé facilement et paramétrables; le modèle est poussé sur le S3 de MLFlow et taggé en fonction de ses résultats
    - une API de prédiction qui utilisera un modèle MLFlow
    - un DAG Airflow qui pourra envoyer des emails (utilisation de Github action pertinente?)
- on utilisera des fichiers requirements.txt pour les env d'exécution python
- on fera d'abord les tests en local avec Docker et des images légère de type python-3.12-slim (on verra plus tard pour la mise en prod)

---

## Phase 1 : Construction et entrainements des modèles

### 1.1 - Script de préparation du dataset avant entrainement

Agent CodeWriter #1

- input : @work/fraudTest.csv (le script ne connaît que ce chemin — @data/fraudTest.csv n'existe
  pas de son point de vue ; c'est le DAG Model Training, task copy_data, qui garantit sa présence
  avant d'appeler ce script, cf. phase 3.3)
- output : @work/fraudTest_prepared.csv et @work/client_trx_analysis.csv

- premières analyses du dataset :
    - charger en prenant comme identifiant trans_num
    - analyser les effectifs et valeurs null
    - répartition fraude/non fraude
    - exclure valeurs null et/ou doublons
- feature engineering :
    - calculer nouveaux champs :
        - distance_km : distance entre long/lat et merch_lat, merch_long (utiliser geopy)
        - date : calculé à partir d'un split de trans_date_trans_time (ou unix_time)
        - time : calculé à partir d'un split de trans_date_trans_time (ou unix_time)
        - hour : calculé à partir d'un split de trans_date_trans_time (ou unix_time)
        - dow : day of week calculé à partir de unix time
        - diff_avg_amt : différence entre le montant de la transaction et le montant moyen par client (vérifier si les clients uniques peuvent etre définis par la clé qui concatène id_client={last}_{first}_{gender}_{dob}_{zip}) - on sauvegardera dans work un fichier @work/client_trx_analysis.csv contenant les id_client, le montant moyen de leurs dépenses avg_mnt et la fréquence moyenne de leurs transactions (sur la durée totale du dataset)
    - enlever les champs de data personnelles inutiles pour le training des modèles: 0, cc_num, first, last, street, dob
- faire EDA simple notamment en calculant + affichage en log :
        - fréquence moyenne des transactions/client
        - liste des jours dow les plus probables
        - moyenne de distance_km (distance entre client et marchand)

### 1.2 - Script d'entrainement

Agent CodeWriter #1

- input :  @work/fraudTest_prepared.csv
- output : 
    - en test : modèle sous forme pkl en local + base SQLite locale MLFlow
    - en prod : modèle dans S3 de MLFlow + MLFLow v3.7.0 déployé sur HuggingFace

ce script doit pouvoir
- accepter une config yaml qui indique
    - les modèles à tester avec éventuellement paramètres de modèle (un modèle peut apparaitre plusieurs fois mais avec des paramtères différents pour pouvoir tester plusieurs variantes):
        - LogisticRegression avec class_weight="balanced"
        - XGBoost avec scale_pos_weight
        - LightGBM avec is_unbalanced=True
        - (sklearn.svm.OneClassSVM testé puis retiré : peu performant sur ce dataset une fois
          assez d'exemples de fraude labellisés disponibles pour un classifieur supervisé — cf.
          CLAUDE.md pour le détail des modèles réellement actifs dans config/models.yaml)
    - le taux de train/test split
    - ajouter ou non une politique de rééchantillonage étant donné que le dataset est déséquilibré
        - sous-échantillonage : on supprime des exemples majoritaires jusqu'au taux souhaité pour les data minoritaires (RandomUnderSampler)
        - SMOTE : création artificielle de data minoritaires - configuration : sampling_strategy (ratio cible entre classe: 0.1 pour 10% de minoritaires, auto pour 50%/50%), k_neighbors nombre de voisins pour générer l'exemple (prendre k pas trop grand entre 3 et 5) et fixer le random_state
- faire l'entrainement des modèles
    - faire un train/test split selon la config
    - appliquer la technique de rééchantillonage
    - évaluer les scores f1-score, recall, precision, accuracy, ROC-AUC, PR-AUC des modèles
    - logger les scores dans MLFlow v3.7.0 https://gviel-mlflow37.hf.space/#/ (prod uniquement —
      cf. note ci-dessous)
- tagger les modèles avec des tags { env=prod|test, status=best|challenger|worst}; le meilleur sera taggé avec status=best, le pire avec status=worst et les autres en status=challenger
    - en prod : pousser le modèle vers le bucket S3 de MLFlow de prod
    - en test : sauver le modèle en local dans un répertoire model au format pkl, ET basculer
      automatiquement le tracking MLFlow sur un store **SQLite local** (`work/mlflow_local.db`, jamais poussé nulle part) au lieu du serveur MLFLow hébergée `https://gviel-mlflow37.hf.space/`
      partagée avec la prod — permet de s'entraîner/itérer en local (`make train ARGS="--env test"`) sans dépendre du réseau/des credentials du serveur MLFlow hébergé, et sans y
      accumuler de bruit : ces runs ne sont de toute façon jamais servis (pas de modèle poussé sur
      S3), les logguer dans l'historique partagé ne ferait qu'y ajouter du bruit de dev/itération
      et risquerait qu'un run de test pollue la sélection "meilleur modèle" utilisée par l'API en
      prod (cf. piège Render documenté dans CLAUDE.md). Pour consulter ces runs locaux :
      `mlflow ui --backend-store-uri sqlite:///work/mlflow_local.db`

#### Note de rappel sur SMOTE (Synthetic Minority Over-sampling Technique):
Rappel de ce qui est fait pas la lib imblearn.over_sampling.SMOTE (à faire toujours après le split train/test pas avant!)
1) Sélectionne un exemple minoritaire (ex: une fraude) au hasard.
2) Trouve ses k plus proches voisins (k-NN) dans la même classe minoritaire.
3) Génère un nouvel exemple synthétique en interpolant linéairement entre l'exemple et un voisin aléatoire :
    nouveau_point = point_existant + λ × (voisin - point_existant)
    où λ est un nombre aléatoire entre 0 et 1.
4) Répète jusqu'à ce que la classe minoritaire ait la taille souhaitée.

---

## Phase 2 : Création de l'API de prédiction de fraude

Agent CodeWriter #2

**Déployée en prod (Render, 2026-07-06)** : `https://jedha-aia-03-frauddetection.onrender.com`

Ce que doit faire notre API (FastAPI)
- doit récupérer avec MLFlow client le meilleur modèle taggé avec status=best
    - en test : on charge le modèle sauvé en local au format pkl dans le répertoire model
    - en prod : on charge le modèle à partir de MLFLow (bucket S3 de MLFlow)
- doit charger le fichier client_trx_analysis.csv (stats par client pour la feature diff_avg_amt,
  cf. phase 1.1) au démarrage
    - en test : depuis work/client_trx_analysis.csv en local (produit par prepare_dataset.py)
    - en prod (Render) : depuis le bucket S3 bucket-fraud-detection-gviel (préfixe work/), l'API
      n'ayant pas accès au disque local où tourne l'entraînement — le télécharger au démarrage
      avant de servir des prédictions
    - si le fichier est indisponible (client inconnu ou fichier manquant) : repli sur la moyenne
      globale, cf. phase 1.1
- on pourra charger le modèle en asynchrone et renvoyé err 503 avec message d'erreur tant qu'il n'est pas prêt
- avoir un endpoint /predict qui fait la prédiction avec le modèle
    - input : une transaction
    - output : indique si la transaction est une fraude ou pas + transaction elle-meme (id de la transaction : transac_num)
- avoir un endpoint /health qui indique le statut du service (ready/loading/error), l'environnement,
  le nom du modèle chargé et la version de l'API
- avoir un endpoint POST /reload-model permettant de forcer le rechargement du modèle (depuis
  MLFlow en prod, depuis le pkl local en test) et des stats client, sans redémarrer le service
    - protégé par une valeur secrète (magic value) passée en paramètre de requête (`token`) et
      comparée à une variable d'environnement `MODEL_RELOAD_TOKEN` partagée avec le DAG Model
      Training (phase 3.3) ; si absente ou différente -> 403, pas d'authentification utilisateur
    - déclenché par le DAG Model Training à la fin d'un entraînement réussi (cf. phase 3.3),
      pas destiné à un appel manuel/utilisateur en usage normal
- avoir un endpoint /docs swagger avec data d'exemple pour pouvoir tester l'API

---

## Phase 3 : création d'un DAG Airflow

### 3.1 - DAG ETL & Detection Fraud

Agent CodeWriter #3

Objectif : collecter les nouvelles transaction, les stocker, faire la détection de fraude et alerter par email.

- task fetch_trx : phase collecte
    - schedule : s'exécute toutes les X minutes (paramétrable dans Airflow?) sauf si le DAG n'est pas terminé
    - appel realtime API pour récupèrer la dernière transaction
    - output : une transaction au format JSON
    - si OK va vers : store_trx
- task store_trx : phase transformation et load (si la transaction en input est valide)
    - en prod :
        - on la stocke dans un bucket S3 dans un répertoire/prefix yyyyMMdd/trx-{yyyyMMdd_HHmmss}_{trans_num}.json
        - on la stocke dans une base PgSQL Neon
    - en test :
        - on la stocke dans un répertoire work/yyyyMMdd/trx-{yyyyMMdd_HHmmss}_{trans_num}.json
        - on la stocke 
            - en test : dans unee bdd PgSQL lancée en local dans un conteneur docker
            - en prod : dans une base PgSQL Neon distante
    - input : une transaction en JSON
    - output : une transaction en JSON si elle est valide (champs présent, non null)
    - si OK va vers : fraud_detect
-  task fraud_detect :
    - fait un appel à l'API de prédiction de fraude en lui envoyant la transaction reçue par store_trx.py et sauve la prédiction en base de données PgSQL fraud-detection-db (en prod : sur Neon, en test : dans un bdd pgsql locale sur docker)
    - input : transaction en JSON
    - output : prédiction si fraude ou non + la transaction
    - branchement :
        - si la transaction est une fraude >0.7 :
            - sauver en bdd pgsql fraud-detection-db le résultat de la prédiction pour la transaction
            - puis passe à la task suivante du DAG -> send_fraud_alert_email
        - sinon on s'arrete
- task send_fraud_alert_email :
    - input : transaction + prédiction de fraude
    - output : envoi d'un email (configurable) indiquant que la transaction est une fraude à x% (valeur de prédiction)
    - si OK fin du DAG
- task augment_training_data : déclenchée systématiquement après fraud_detect (indépendamment
  du résultat de fraude), pour permettre au DAG Model Training (phase 3.3) de se redéclencher
  périodiquement sans intervention manuelle
    - input : la transaction reçue + la prédiction de fraud_detect (fraud_score/is_fraud)
    - génère une transaction synthétique dérivée de la transaction reçue : mêmes champs
      (client, marchand, catégorie, localisation...) mais avec un nouveau trans_num généré et un
      montant légèrement perturbé (variation aléatoire, ex. ±10-20%) pour produire une ligne
      plausible mais distincte — pas d'utilisation de SMOTE ici (SMOTE interpole entre plusieurs
      exemples voisins d'un dataset labellisé complet, inadapté à la génération d'une seule
      transaction synthétique en flux temps réel)
    - label de fraude de la ligne ajoutée : réutilise la prédiction is_fraud de fraud_detect (pas
      de vérité terrain disponible pour une transaction temps réel)
    - output : la transaction synthétique est ajoutée (append) à work/fraudTest.csv, toujours EN
      LOCAL (test comme prod — Airflow reste local, cf. phase 5) — fait grossir ce fichier au fil
      du temps jusqu'à dépasser le nombre de lignes de data/fraudTest.csv, ce qui déclenche la
      branche de ré-entraînement du DAG Model Training (phase 3.3)
    - en prod : une fois la ligne ajoutée localement, synchroniser un snapshot de work/fraudTest.csv
      sur S3 (préfixe work/) — ici, à la fin de la collecte+prédiction (dernière étape du DAG à
      modifier ce fichier), pas dans le DAG Model Training (phase 3.3) qui ne tourne que
      périodiquement et verrait sinon un fichier obsolète
    - si OK fin du DAG

- synopsis DAG :
    - fetch_trx >> store_trx >> task_fraud_detect
    - task_fraud_detect >> send_fraud_alert_email (si fraude détectée)
    - task_fraud_detect >> augment_training_data (toujours)
    - send_fraud_alert_email >> end
    - augment_training_data >> end


### 3.2 - DAG Fraud Report

Agent CodeWriter #4

Ojectif: générer un rapport de fraude régulièrement et l'envoyer par email.

- schedule : s'exécute toutes les N heures pour générer un rapport de fraudes
- task daily_report :
    - va chercher dans la base de données pgsql fraud-detection-db toutes les trx avec date entre now-N heures et now et génére un rapport indiquant le taux de trx frauduleuses
- si task daily_report ok -> task send_email_report : envoie le rapport par email (configurable)

- synopsis DAG : 
    - daily_report >> send_email_report

### 3.3 - DAG Model Training

Agent CodeWriter #1

Objectif: déployer et exécuter de façon ponctuelle l'entrainement de plusieurs modèles.

- schedule : à exécuter toute les x minutes (schedule_interval=60min par défaut)
- en test comme en prod : @data/fraudTest.csv, @work/fraudTest.csv et @work/fraudTest_prepared.csv
  sont lus/écrits EN LOCAL en permanence, y compris en prod (Airflow reste local, cf. Phase 5).
  @work/fraudTest_prepared.csv reste de toute façon un fichier purement local au conteneur
  (produit par prepare_dataset.py, consommé par train_model.py dans le même subprocess/conteneur
  airflow-scheduler) : aucun composant distant n'en a jamais besoin.
- en prod uniquement, S3 (bucket bucket-fraud-detection-gviel, préfixe work/) sert de snapshot/
  point de reprise, synchronisé au plus près de chaque écriture qui modifie réellement le fichier
  concerné (pas dans le DAG Model Training pour @work/fraudTest.csv — il ne tourne que
  périodiquement et verrait un fichier obsolète) :
  - @work/fraudTest.csv : synchronisé par la task augment_training_data (DAG ETL & Fraud
    Detection, phase 3.1) juste après chaque ajout de ligne — c'est la seule task qui modifie ce
    fichier
  - @work/client_trx_analysis.csv : synchronisé par la task train du DAG Model Training (phase
    3.3, ci-dessous), une fois l'entraînement réellement terminé — requis par l'API (Phase 2) qui
    n'a pas accès au disque local où tourne l'entraînement
- branch : (toujours en local, y compris en prod)
    - si le fichier @work/fraudTest.csv n'existe pas -> copy_data -> prepare (pour lancer le training)
    - sinon si le fichier @work/fraudTest.csv contient plus de lignes que le fichier original @data/fraudTest.csv -> prepare(lance le training)
    - autrement on arrete le DAG (stop_dag)
- task copy_data : copier @data/fraudTest.csv dans @work/fraudTest.csv, toujours en local (y
  compris en prod — cf. ci-dessus)
- task prepare : on y exécute prepare_model.py : cf. specs phase 1.1 — reste purement local, y
  compris en prod (aucun upload S3 ici, cf. ci-dessus pour le détail des points de synchronisation)
- si task prepare réussie -> task train : on y execute train_model.py : cf. specs phase 1.2
    - en prod : une fois l'entraînement terminé (subprocess réussi), uploader
      @work/client_trx_analysis.csv sur S3 (préfixe work/), indépendamment du résultat de la
      comparaison status=best ci-dessous (les stats client ne sont pas liées à un run précis)
    - train_model.py tague toujours le meilleur modèle de CE run avec status=best (cf. phase 1.2),
      même s'il est moins bon que le meilleur historique — la task train ne doit donc appeler
      POST /reload-model de l'API (phase 2) que si ce nouveau modèle est bien devenu LE meilleur
      tous runs confondus (celui que l'API chargerait réellement), pas juste le meilleur de son
      propre cohort de modèles :
        - comparer le run tagué status=best le plus récent (celui qui vient d'être produit) au
          run tagué status=best ayant le plus haut pr_auc toutes exécutions confondues
        - coïncidence (même run_id) -> déclencher POST /reload-model avec le token partagé
          (MODEL_RELOAD_TOKEN), appel best-effort (un échec — API indisponible, token absent —
          est loggé mais ne fait pas échouer la task, l'entraînement ayant déjà réussi)
        - sinon -> ne rien déclencher, le modèle actuellement chargé par l'API reste le bon

- sysnopsis DAG :
    - start >> branch
    - branch >> copy_data >> prepare >> train
    - branch >> prepare
    - branch >> stop_dag

---

## Phase 4 : déploiement en test

Agent : Devops engineer #1 & QA Tester #1

- serveur MLFlow en local avec SQLite et fichier modèle local *.pkl

### 4.1 - tests unitaires

Répertoire @work est le répertoire de travail pour stocker et manipuler des fichiers.

- tests scripts phase 1 :
    - tests unitaires des scripts : pytest dans @tests
    - tests des scripts dans un conteneur docker (dans un répertoire scripts ou tools mettre les scripts qui permettent de kill, rebuild et démarrer le conteneur, suivre les logs, lancer manuellement les scripts prepare_dataset.py et train.py)
- tests phase 2 :
    - déploy de l'API avec Docker dans un conteneur (faire apparaitre 'test' dans le nom du conteneur)
- tests phase 3 :
    - tests unitaires des scripts pour les DAG (à implémenter plus tard)

### 4.2 - tests d'intégration

Répertoire @work est le répertoire de travail pour stocker et manipuler des fichiers

- si les tests unitaires sont OK 
    - deploy stack local Airflow 3.2.2 avec Docker LocalExecutor + un requirements.txt spécifique selon les besoins des DAGs avec les composants suivants :
        - composants Airflow de base (init, apiserver, triggerer, dag processor)
        - bdd pgsql pour stockage des transactions realtime collectées par le DAG ETL & Detection Fraud
        - API fraud-detection pour les prédictions (faire apparaitre 'cicd' dans le nom du contenan)
        - pour le DAT Model Training les scripts seront exécutés en subprocess dans Airflow (pas de déport Docker dans un conteneur Docker car trop complexe)
    - si la stack est déployée correctement sans erreur, lancer les tests d'intégration dessus pour tout tester de bout en bout

---

## Phase 5 : déploiement en prod

Agent : Devops engineer #1

**Stack prod déployée (2026-07-06)** :
- serveur MLFlow v3.7.0 (Hugging Face) : `https://gviel-mlflow37.hf.space/`
- API fraud detection (Render) : `https://jedha-aia-03-frauddetection.onrender.com`
- Dashboard de suivi (Streamlit Community Cloud, phase 6) :
  `https://jedha-aia-03-frauddetection-vs7adfbiy54amcv5jqy3gc.streamlit.app/`
- BDD PgSQL (Neon, projet `fraud-detection-db`) : chaîne de connexion dans `DATABASE_URL_PROD`
  (`.env.production`, non commité)

Définition de la stack à déployer :
    - API fraud detection sur Render
    - BDD PgSQl sur Neon pour le stockage des transactions au fur et à mesure qu'elles arrivent (utiliser le MCP server Neon pour créer et manipuler cette base de données)
    - stack serveur Airflow v3.2.2 en local avec les composants suivants:
        - composants Airflow de base (init, apiserver, triggerer, dag processor)
        - DAG Model Training : les scripts seront exécutés en subprocess dans Airflow (pas de déport du training dans un conteneur Docker ou de déploiement sur un EC2 à ce stade; à voir plus tard)
        - les DAGs :
            - DAG ETL & Fraud Detection interagit avec :
                - Neon DB fraud-detection-db
                - API fraud detection sur Render
                - Bucket S3 bucket-fraud-detection-gviel (bucket-fraud-detection déjà pris
                  globalement, suffixe -gviel ajouté pour l'unicité) permettant de stocker :
                    - work/yyyyMMdd/trx-{yyyyMMdd_HHmmss}_{trans_num}.json : les transactions
                      collectées, écrites directement sur S3 par store_trx (en prod)
                    - work/fraudTest.csv : snapshot de la copie de travail locale (celle-ci reste
                      un fichier LOCAL en permanence, complétée au fil du temps par la task
                      augment_training_data qui ajoute une transaction synthétique dérivée de
                      chaque transaction collectée, pour provoquer le déclenchement périodique d'un
                      nouveau training côté DAG Model Training, phase 3.3) — synchronisé sur S3
                      par cette même task, juste après chaque ajout de ligne (en prod uniquement)
                - SMTP Gmail
            - DAG Fraud Report interagit avec :
                - Neon DB fraud-detection-db
                - SMTP Gmail
                - (en option pour plus tard: bucket S3 bucket-fraud-detection-gviel pour stocker un rapport PDF)
            - DAG Model Training interragit avec:
                - MLFLow + S3 aws-s3-mlflow de MLFlow (pour déposer le modèle)
                - buket S3 bucket-fraud-detection-gviel : @data/fraudTest.csv et @work/fraudTest.csv
                  restent des fichiers LOCAUX en permanence (test comme prod, cf. phase 3.3 — la
                  synchronisation de work/fraudTest.csv se fait ailleurs, cf. DAG ETL & Fraud
                  Detection ci-dessus, pas ici). La task train (en prod uniquement, une fois
                  l'entraînement terminé) uploade work/client_trx_analysis.csv sur S3 (préfixe
                  work/) — pour les calculs des features, également lu par l'API (phase 2) au
                  démarrage en prod, pour la feature diff_avg_amt
                  (work/fraudTest_prepared.csv n'est PAS uploadé : fichier intermédiaire purement
                  local au conteneur airflow-scheduler, cf. phase 3.3 — aucun composant distant
                  n'en a besoin)
                - API fraud detection sur Render (POST /reload-model, cf. phase 2 et 3.3) via un
                  secret partagé MODEL_RELOAD_TOKEN (même valeur configurée côté Airflow et
                  côté Render)

## Phase 6 : création d'un dashboard de suivi

### 6.1 - Créer un dashboard streamlit permettant de
- voir les dernières transactions collectée sur la journée par le système (la dernière en premier) : les transactions doivent donc avoir un timestamp d'écriture en bdd (à vérifier dans le DAG ETL & Fraud detection)
- on doit voir le score de fraude et il faudra indiquer avec légende
    - en rouge les fraudes > 0.9
    - en orange les fraudes >0.7 et <=0.9>
    - en jaune les fraudes entre 0.5 et 0.7
    - en vert les fraudes <=0.5
- on doit pouvoir filtrer pour d'autres jour que la journée courante et filtrer les transactions par niveau de fraude ou toutes les fraudes
- on devra indiquer la version de l'API  + modèle et technique utilisée (si info facilement disponible : abandonner si trop complexe)

### 6.2 - Déploiement du dashboard

- en test : dans un docker
- en prod : sur streamlit — **déployé (2026-07-06)** :
  `https://jedha-aia-03-frauddetection-vs7adfbiy54amcv5jqy3gc.streamlit.app/`

