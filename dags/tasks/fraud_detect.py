import json

import requests

from config import DATABASE_URL, FRAUD_API_URL, FRAUD_THRESHOLD


def fraud_detect(**context):
    """Appelle l'API de prédiction et retourne les tâches suivantes (BranchOperator) :
    la branche alerte/fin + toujours augment_training_data."""
    ti  = context["ti"]
    trx = json.loads(ti.xcom_pull(task_ids="store_trx"))

    resp = requests.post(f"{FRAUD_API_URL}/predict", json=trx, timeout=15)
    resp.raise_for_status()
    prediction   = resp.json()
    fraud_score  = float(prediction.get("fraud_score", 0.0))
    is_fraud     = bool(prediction.get("is_fraud", False))
    diff_avg_amt = prediction.get("diff_avg_amt")
    trans_num    = trx["trans_num"]

    print(f"[fraud_detect] {trans_num} → score={fraud_score:.4f}  is_fraud={is_fraud}")

    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE real_time_transactions
                   SET is_fraud_predicted=%s, fraud_score=%s, diff_avg_amt=%s
                 WHERE trans_num=%s
            """, (is_fraud, fraud_score, diff_avg_amt, trans_num))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[fraud_detect] WARN PgSQL update : {exc}")

    ti.xcom_push(key="fraud_result", value=json.dumps({
        **trx, "fraud_score": fraud_score, "is_fraud": is_fraud,
    }))

    branch = "send_fraud_alert_email" if fraud_score >= FRAUD_THRESHOLD else "end"
    return [branch, "augment_training_data"]
