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

# Bascule prod : APP_ENV=prod ./start.sh pointe les DAGs 3.1/3.2 vers Neon (DATABASE_URL_PROD)
# au lieu du fraud-db local. On ne source pas tout ../.env (écraserait DATABASE_URL et d'autres
# vars déjà utilisées ici) : on lit uniquement DATABASE_URL_PROD si elle n'est pas déjà exportée.
if [ -z "${DATABASE_URL_PROD:-}" ] && [ -f ../.env ]; then
    DATABASE_URL_PROD="$(grep -E '^DATABASE_URL_PROD=' ../.env | tail -1 | cut -d= -f2-)"
fi

# Email (alerte fraude + rapport quotidien) + reload modèle (DAG 3.3 -> API /reload-model) —
# indépendant du mode APP_ENV, lu depuis ../.env si pas déjà exporté (mêmes lecture ciblée
# que DATABASE_URL_PROD/AWS ci-dessous).
for _var in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD FRAUD_ALERT_EMAIL REPORT_EMAIL MODEL_RELOAD_TOKEN; do
    if [ -z "${!_var:-}" ] && [ -f ../.env ]; then
        export "$_var=$(grep -E "^${_var}=" ../.env | tail -1 | cut -d= -f2-)"
    fi
done

export APP_ENV="${APP_ENV:-test}"
if [ "$APP_ENV" = "prod" ]; then
    if [ -z "${DATABASE_URL_PROD:-}" ]; then
        echo "ERREUR : APP_ENV=prod nécessite DATABASE_URL_PROD (dans ../.env ou l'environnement)." >&2
        exit 1
    fi
    export DATABASE_URL="${DATABASE_URL:-$DATABASE_URL_PROD}"

    # store_trx.py bascule aussi sur l'upload S3 (au lieu du fichier local) quand APP_ENV=prod —
    # il faut donc aussi les credentials AWS dans les conteneurs Airflow (même lecture ciblée
    # de ../.env, sans écraser d'autres vars).
    for _var in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION; do
        if [ -z "${!_var:-}" ] && [ -f ../.env ]; then
            export "$_var=$(grep -E "^${_var}=" ../.env | tail -1 | cut -d= -f2-)"
        fi
    done
    if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
        echo "ERREUR : APP_ENV=prod nécessite AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (dans ../.env ou l'environnement)." >&2
        exit 1
    fi
    export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-west-3}"
else
    export DATABASE_URL="${DATABASE_URL:-postgresql://fraud:fraud@fraud-db:5432/fraud}"
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
