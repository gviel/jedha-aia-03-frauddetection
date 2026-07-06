import csv
import json
import random
import uuid
from datetime import datetime, timezone

from config import APP_ENV, S3_BUCKET, WORK_DIR

WORK_RAW_CSV = WORK_DIR / "fraudTest.csv"

# Doit correspondre exactement au schéma de data/fraudTest.csv (colonne d'index sans nom incluse).
CSV_COLUMNS = [
    "", "trans_date_trans_time", "cc_num", "merchant", "category", "amt",
    "first", "last", "gender", "street", "city", "state", "zip", "lat", "long",
    "city_pop", "job", "dob", "trans_num", "unix_time", "merch_lat", "merch_long", "is_fraud",
]


def _next_index() -> int:
    with open(WORK_RAW_CSV, "rb") as f:
        return sum(1 for _ in f) - 1  # -1 pour l'en-tête


def augment_training_data(**context):
    """Génère une transaction synthétique dérivée de la transaction collectée (nouveau trans_num,
    montant perturbé) et l'ajoute à work/fraudTest.csv, pour déclencher périodiquement un nouvel
    entraînement (specs.md §3.1/§3.3). Le label is_fraud reprend la valeur de la transaction de
    base (vérité terrain fournie par l'API Jedha) — pas la prédiction de fraud_detect, qui
    écrase ce même champ dans son propre XCom "fraud_result"."""
    if not WORK_RAW_CSV.exists():
        print(f"[augment_training_data] {WORK_RAW_CSV} absent (DAG 3.3 pas encore initialisé) — skip.")
        return

    ti  = context["ti"]
    trx = json.loads(ti.xcom_pull(task_ids="store_trx"))

    unix_time = int(trx["current_time"] / 1000)
    trans_date_trans_time = datetime.fromtimestamp(unix_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_trans_num = uuid.uuid4().hex
    new_amt = round(trx["amt"] * random.uniform(0.8, 1.2), 2)

    row = {
        "":                      _next_index(),
        "trans_date_trans_time": trans_date_trans_time,
        "cc_num":                trx["cc_num"],
        "merchant":              trx["merchant"],
        "category":              trx["category"],
        "amt":                   new_amt,
        "first":                 trx["first"],
        "last":                  trx["last"],
        "gender":                trx["gender"],
        "street":                trx["street"],
        "city":                  trx["city"],
        "state":                 trx["state"],
        "zip":                   trx["zip"],
        "lat":                   trx["lat"],
        "long":                  trx["long"],
        "city_pop":              trx["city_pop"],
        "job":                   trx["job"],
        "dob":                   trx["dob"],
        "trans_num":             new_trans_num,
        "unix_time":             unix_time,
        "merch_lat":             trx["merch_lat"],
        "merch_long":            trx["merch_long"],
        "is_fraud":              trx["is_fraud"],
    }

    with open(WORK_RAW_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerow(row)

    print(f"[augment_training_data] Transaction synthétique {new_trans_num} ajoutée à "
          f"{WORK_RAW_CSV} (is_fraud={trx['is_fraud']})")

    if APP_ENV == "prod":
        # work/fraudTest.csv reste la copie de travail LOCALE en permanence (lue/écrite par cette
        # task à chaque collecte de transaction) — mais synchronisée sur S3 ici, à la fin de la
        # collecte+prédiction (dernière étape du DAG ETL & Fraud Detection à modifier ce fichier),
        # pour que le DAG Model Training (3.3) voie un snapshot à jour, pas seulement au moment de
        # son propre cycle d'entraînement (cf. specs.md §3.1/§3.3).
        try:
            import boto3
            boto3.client("s3").upload_file(str(WORK_RAW_CSV), S3_BUCKET, "work/fraudTest.csv")
            print(f"[augment_training_data] Snapshot work/fraudTest.csv synchronisé sur S3")
        except Exception as exc:
            print(f"[augment_training_data] WARN sync S3 work/fraudTest.csv : {exc}")
