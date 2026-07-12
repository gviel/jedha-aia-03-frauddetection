#!/usr/bin/env bash
# Réveille en parallèle tous les services tiers hébergés en free tier utilisés par la démo
# (Render, HuggingFace Spaces, Streamlit Community Cloud) — tous s'endorment après inactivité,
# avec un cold start de plusieurs dizaines de secondes. À lancer en tout premier, avant les
# préparatifs hors-caméra de docs/travail/video_demo_plan.md, pour ne pas perdre ce temps
# pendant l'enregistrement.
set -uo pipefail

MLFLOW_URI="${MLFLOW_URI:-https://gviel-mlflow37.hf.space/}"
JEDHA_API_URL="${JEDHA_API_URL:-https://sdacelo-real-time-fraud-detection.hf.space/current-transactions}"
FRAUD_API_URL="${FRAUD_API_URL:-https://jedha-aia-03-frauddetection.onrender.com}"
# Pas de ping automatique pour Streamlit Community Cloud : testé en réel, un GET boucle
# indéfiniment sur une redirection 303 vers l'auth share.streamlit.io (num_redirects=50 avec
# -L) sans jamais réveiller l'app — seul un clic navigateur sur "Yes, get this app back up!"
# fonctionne.
STREAMLIT_URL="${STREAMLIT_URL:-https://jedha-aia-03-frauddetection-vs7adfbiy54amcv5jqy3gc.streamlit.app/}"

MAX_WAIT="${MAX_WAIT:-90}"
INTERVAL=5

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# Ping générique par code HTTP : écrit "ok"/"ko" dans un fichier (pas de valeur de retour
# directe possible depuis un sous-shell lancé en arrière-plan).
wake_http() {
    local name="$1" url="$2" result_file="$3"
    local elapsed=0
    while [ "$elapsed" -lt "$MAX_WAIT" ]; do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo "000")"
        if [ "$code" = "200" ]; then
            echo "ok" > "$result_file"
            echo "[$name] réveillé (HTTP $code) après ${elapsed}s"
            return
        fi
        sleep "$INTERVAL"
        elapsed=$((elapsed + INTERVAL))
    done
    echo "ko" > "$result_file"
    echo "[$name] toujours indisponible après ${MAX_WAIT}s (dernier code: $code)"
}

# Cas particulier Render : /health doit renvoyer status=="ready" (modèle chargé), pas
# seulement un code 200 — même logique que 02_wait_api_health.sh.
wake_render_api() {
    local result_file="$1"
    local elapsed=0
    while [ "$elapsed" -lt "$MAX_WAIT" ]; do
        body="$(curl -sS --max-time 10 "$FRAUD_API_URL/health" 2>/dev/null || echo '{"status":"unreachable"}')"
        status="$(echo "$body" | jq -r '.status' 2>/dev/null || echo "unreachable")"
        if [ "$status" = "ready" ]; then
            echo "ok" > "$result_file"
            echo "[API Render] prête (status=ready) après ${elapsed}s"
            return
        fi
        sleep "$INTERVAL"
        elapsed=$((elapsed + INTERVAL))
    done
    echo "ko" > "$result_file"
    echo "[API Render] toujours pas ready après ${MAX_WAIT}s (dernier statut: $status)"
}

echo "Réveil des services (timeout ${MAX_WAIT}s chacun, en parallèle)..."
echo

wake_http "MLflow"        "$MLFLOW_URI"     "$WORK_DIR/mlflow"   &
wake_http "API Jedha"     "$JEDHA_API_URL"  "$WORK_DIR/jedha"    &
wake_render_api "$WORK_DIR/render" &

wait

echo
echo "=== Résumé ==="
for entry in "MLflow:mlflow" "API Jedha:jedha" "API Render:render"; do
    name="${entry%%:*}"
    file="${entry##*:}"
    result="$(cat "$WORK_DIR/$file" 2>/dev/null || echo "ko")"
    if [ "$result" = "ok" ]; then
        echo "✓ $name"
    else
        echo "✗ $name"
    fi
done

echo
echo "⚠️  Streamlit Community Cloud n'est pas réveillé automatiquement (impossible via curl,"
echo "   boucle de redirection vers l'auth share.streamlit.io). À réveiller manuellement dans"
echo "   le navigateur (bouton \"Yes, get this app back up!\") avant l'enregistrement : $STREAMLIT_URL"
