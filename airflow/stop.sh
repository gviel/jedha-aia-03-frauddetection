#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
else
    DOCKER_COMPOSE=(docker-compose)
fi

export COMPOSE_PROJECT_NAME=fraud-detection
# Toujours inclure le profil "test" ici (que la stack ait été démarrée en test ou en prod) :
# down/rm doit pouvoir nettoyer fraud-db s'il existe, sans se soucier du mode utilisé au start.
export COMPOSE_PROFILES=test

echo "=== Arrêt de la stack Fraud Detection Airflow ==="

if [[ "${1:-}" == "--clean" ]]; then
    echo "Mode --clean : suppression des volumes (DB Airflow + DB Fraud réinitialisées)"
    "${DOCKER_COMPOSE[@]}" down --volumes --remove-orphans
else
    "${DOCKER_COMPOSE[@]}" down --remove-orphans
    echo "Tip : './stop.sh --clean' pour aussi effacer les bases de données"
fi

echo "Stack arrêtée."
