#!/usr/bin/env bash
# Interroge /health sur l'API de prédiction (Render) jusqu'à ce que le modèle soit chargé
# (status == "ready"). Utile pour la démo : le service Render peut mettre quelques secondes
# à réveiller le conteneur (cold start) + charger le modèle depuis MLflow.
set -euo pipefail

API_URL="${FRAUD_API_URL:-https://jedha-aia-03-frauddetection.onrender.com}"
INTERVAL="${1:-5}"

echo "Attente de $API_URL/health (status=ready), intervalle ${INTERVAL}s — Ctrl+C pour arrêter."

while true; do
    body="$(curl -sS "$API_URL/health" || echo '{"status":"unreachable"}')"
    status="$(echo "$body" | jq -r '.status')"

    echo "[$(date +%H:%M:%S)] status=$status"
    echo "$body" | jq '.'

    if [ "$status" = "ready" ]; then
        echo "API prête."
        break
    fi

    sleep "$INTERVAL"
done
