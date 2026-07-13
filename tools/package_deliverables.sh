#!/usr/bin/env bash
# Package les livrables de certification (README, présentation, schéma d'architecture) dans une
# archive zip unique, prête à être déposée sur la plateforme Jedha.
#
# Usage :
#   ./tools/package_deliverables.sh [chemin_zip_sortie]
#
# Par défaut, l'archive est écrite dans work/ (gitignoré) sous le nom
# fraud_detection_deliverables.zip.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OUT_ZIP="${1:-$ROOT_DIR/work/fraud_detection_deliverables.zip}"

FILES=(
    "README.md"
    "docs/AIA_bloc3_fraud_detection_GV.pdf"
    "docs/architecture_prod.drawio._fond_blanc_demo.png"
)

for f in "${FILES[@]}"; do
    if [ ! -f "$ROOT_DIR/$f" ]; then
        echo "Fichier manquant : $f" >&2
        exit 1
    fi
done

mkdir -p "$(dirname "$OUT_ZIP")"
rm -f "$OUT_ZIP"

cd "$ROOT_DIR"
zip -j "$OUT_ZIP" "${FILES[@]}"

echo "Archive créée : $OUT_ZIP"
