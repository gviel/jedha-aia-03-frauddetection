# Image Airflow avec les dépendances des DAGs + les deps ML (prepare_dataset.py/
# train.py tournent en subprocess dans ce conteneur — DAG 3.3, cf. specs.md Phase 4 :
# "pas de déport Docker dans un conteneur Docker car trop complexe").
# Variante -python3.12 : la variante par défaut (Python 3.13) n'a pas de wheel
# précompilée pour scikit-learn==1.4.2 (pin requis pour la compat pickle avec
# api/requirements.txt) et échoue à la construire depuis les sources (numpy==2.0.0rc1
# non disponible en 3.13).
FROM apache/airflow:3.2.2-python3.12

USER root
# libgomp1 : requis par LightGBM (libgomp.so.1, absent de l'image de base —
# vérifié : import lightgbm plante avec OSError sans ce paquet système, non
# installable via _PIP_ADDITIONAL_REQUIREMENTS qui ne fait que du pip install).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER airflow

COPY dags/requirements.txt /tmp/requirements-dags.txt
COPY src/requirements.txt  /tmp/requirements-src.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dags.txt -r /tmp/requirements-src.txt
