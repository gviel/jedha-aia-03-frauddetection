#!/usr/bin/env bash
# Convertit la transaction (format "split" pandas, déjà décodée/pretty-printée par
# 01_fetch_trx.sh) stockée dans un fichier temporaire en payload conforme à
# api/schemas.py::Transaction, puis l'envoie à /predict. Les JSON produits sont mis en
# forme (pretty-print) pour un affichage direct avec `cat`.
set -euo pipefail

API_URL="${FRAUD_API_URL:-https://jedha-aia-03-frauddetection.onrender.com}"
IN="${1:-/tmp/demo_trx_raw.json}"
OUT="${2:-/tmp/demo_trx_predict_payload.json}"

jq '
    (.columns as $c | .data[0] as $d | [$c, $d] | transpose | map({(.[0]): .[1]}) | add)
    | {trans_num, amt, merchant, category, first, last, dob, gender, city, state,
       zip, lat, long, city_pop, job, merch_lat, merch_long, current_time}
' "$IN" > "$OUT"

echo "Payload /predict sauvegardé dans $OUT :"
cat "$OUT"
echo

curl -sS -X POST "$API_URL/predict" \
    -H "Content-Type: application/json" \
    -d @"$OUT" | jq '.'
