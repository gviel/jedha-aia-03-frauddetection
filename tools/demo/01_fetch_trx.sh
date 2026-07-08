#!/usr/bin/env bash
# Récupère la dernière transaction depuis l'API temps réel Jedha et la sauve, décodée et
# mise en forme (pretty-print), dans un fichier temporaire — lisible directement avec `cat`
# (même URL que dags/config.py::JEDHA_API_URL).
set -euo pipefail

JEDHA_API_URL="https://sdacelo-real-time-fraud-detection.hf.space/current-transactions"
OUT="${1:-/tmp/demo_trx_raw.json}"

# L'API Jedha renvoie une chaîne JSON contenant elle-même du JSON (double encodage,
# cf. commentaire dags/tasks/fetch_trx.py) — un premier passage jq -r déséchappe la
# chaîne externe, le second met en forme le JSON interne (format pandas "split").
curl -sS "$JEDHA_API_URL" | jq -r '.' | jq '.' > "$OUT"

echo "Transaction brute sauvegardée dans $OUT"
echo "trans_num=$(jq -r '.data[0][.columns | index("trans_num")]' "$OUT")"
