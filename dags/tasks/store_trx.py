import json
from datetime import datetime

from config import APP_ENV, DATABASE_URL, S3_BUCKET, WORK_DIR


def store_trx(**context):
    """Valide et stocke la transaction (fichier local ou S3 + PgSQL)."""
    ti  = context["ti"]
    trx = json.loads(ti.xcom_pull(task_ids="fetch_trx"))

    required = ["trans_num", "amt", "lat", "long", "merch_lat", "merch_long", "category"]
    missing  = [f for f in required if trx.get(f) is None]
    if missing:
        raise ValueError(f"Champs obligatoires manquants : {missing}")

    trans_num = trx["trans_num"]
    now       = datetime.utcnow()
    date_str  = now.strftime("%Y%m%d")
    time_str  = now.strftime("%Y%m%d_%H%M%S")
    filename  = f"trx-{time_str}_{trans_num}.json"

    if APP_ENV == "test":
        out_dir = WORK_DIR / date_str
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / filename).write_text(json.dumps(trx, indent=2))
        print(f"[store_trx] Sauvegardé localement : {out_dir / filename}")
    else:
        import boto3
        s3  = boto3.client("s3")
        key = f"{date_str}/{filename}"
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(trx).encode())
        print(f"[store_trx] Uploadé vers s3://{S3_BUCKET}/{key}")

    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS real_time_transactions (
                    id                 SERIAL PRIMARY KEY,
                    trans_num          TEXT UNIQUE NOT NULL,
                    stored_at          TIMESTAMPTZ DEFAULT NOW(),
                    merchant           TEXT,
                    category           TEXT,
                    amt                DOUBLE PRECISION,
                    lat                DOUBLE PRECISION,
                    long_              DOUBLE PRECISION,
                    merch_lat          DOUBLE PRECISION,
                    merch_long         DOUBLE PRECISION,
                    state              TEXT,
                    is_fraud_predicted BOOLEAN,
                    fraud_score        DOUBLE PRECISION,
                    diff_avg_amt       DOUBLE PRECISION,
                    raw_data           JSONB
                )
            """)
            # CREATE TABLE IF NOT EXISTS ne modifie pas une table déjà existante (cf. Neon prod,
            # fraud-db local déjà initialisée avant cette colonne) — ALTER TABLE explicite requis.
            cur.execute("""
                ALTER TABLE real_time_transactions
                ADD COLUMN IF NOT EXISTS diff_avg_amt DOUBLE PRECISION
            """)
            cur.execute("""
                INSERT INTO real_time_transactions
                    (trans_num, merchant, category, amt, lat, long_, merch_lat, merch_long, state, raw_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trans_num) DO NOTHING
            """, (
                trans_num,
                trx.get("merchant"),  trx.get("category"),
                trx.get("amt"),       trx.get("lat"),
                trx.get("long"),      trx.get("merch_lat"),
                trx.get("merch_long"),trx.get("state"),
                json.dumps(trx),
            ))
        conn.commit()
        conn.close()
        print(f"[store_trx] Stocké en PgSQL : {trans_num}")
    except Exception as exc:
        print(f"[store_trx] WARN PgSQL : {exc}")

    return json.dumps(trx)
