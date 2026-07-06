#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Compatibilité docker compose v2 (plugin) / docker-compose v1 (binaire autonome)
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
else
    DOCKER_COMPOSE=(docker-compose)
fi

export AIRFLOW_UID=$(id -u)

# Un seul fichier .env choisi entièrement selon APP_ENV (airflow/.env.test ou
# airflow/.env.production — mêmes clés des deux côtés, cf. airflow/.env.template) : pas de
# fusion entre fichiers, pas de variable au nom différent selon l'environnement. Lecture ligne
# par ligne via grep/cut (pas de `source` du fichier entier : une valeur contenant un caractère
# spécial shell, ex. le `&` d'une URL Neon, casserait un `source` direct), uniquement si la
# variable n'est pas déjà exportée dans l'environnement courant.
export APP_ENV="${APP_ENV:-test}"
if [ "$APP_ENV" = "prod" ]; then
    ENV_FILE=".env.production"
else
    ENV_FILE=".env.test"
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "ERREUR : airflow/$ENV_FILE introuvable (copier airflow/.env.template)." >&2
    exit 1
fi
for _var in DATABASE_URL POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB FRAUD_API_URL \
            FRAUD_THRESHOLD MLFLOW_URI MODEL_NAME MODEL_RELOAD_TOKEN S3_BUCKET \
            FRAUD_ALERT_EMAIL REPORT_EMAIL SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD \
            REPORT_LOOKBACK_HOURS WORK_DIR DATA_PATH TRAIN_SCHEDULE_MINUTES SRC_DIR \
            PROJECT_CONFIG_PATH AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION; do
    if [ -z "${!_var:-}" ]; then
        export "$_var=$(grep -E "^${_var}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)"
    fi
done
if [ "$APP_ENV" = "prod" ] && { [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; }; then
    echo "ERREUR : APP_ENV=prod nécessite AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY dans airflow/$ENV_FILE." >&2
    exit 1
fi

echo "=== Fraud Detection — Airflow 3.2.2 ==="
echo "AIRFLOW_UID=$AIRFLOW_UID"
echo "APP_ENV=$APP_ENV"

# Créer les répertoires locaux nécessaires
mkdir -p logs plugins config

# Première utilisation : initialiser la DB et créer l'utilisateur admin
if ! "${DOCKER_COMPOSE[@]}" ps airflow-init 2>/dev/null | grep -q "Exited (0)"; then
    echo ""
    echo "--- Initialisation Airflow (première fois) ---"
    "${DOCKER_COMPOSE[@]}" up --build airflow-init
fi

echo ""
echo "--- Démarrage des services ---"
"${DOCKER_COMPOSE[@]}" up -d --build

echo ""
echo "--- Attente du démarrage de l'API server ---"
for i in $(seq 1 20); do
    if curl -sf http://localhost:8080/api/v2/version >/dev/null 2>&1; then
        echo "✓ Airflow UI prête : http://localhost:8080  (airflow / airflow)"
        break
    fi
    printf "."
    sleep 3
done

echo ""
echo "--- Attente de l'API de prédiction ---"
for i in $(seq 1 10); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "✓ Fraud API prête : http://localhost:8000"
        break
    fi
    printf "."
    sleep 3
done

echo ""
echo "Services actifs :"
"${DOCKER_COMPOSE[@]}" ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"
