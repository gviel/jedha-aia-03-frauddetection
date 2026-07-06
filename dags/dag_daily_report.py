"""
DAG Airflow — Rapport de fraudes toutes les N heures.

Interroge la base de données, calcule les statistiques de fraude
sur la période configurée (REPORT_LOOKBACK_HOURS), et envoie le rapport par email.
"""
import json
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from airflow import DAG
from airflow.models import Variable
from airflow.providers.standard.operators.python import PythonOperator

# ── Configuration ─────────────────────────────────────────────────────────────

DATABASE_URL          = Variable.get("DATABASE_URL",           default_var=os.getenv("DATABASE_URL",           "postgresql://fraud:fraud@db:5432/fraud"))
REPORT_EMAIL          = Variable.get("REPORT_EMAIL",           default_var=os.getenv("REPORT_EMAIL",           ""))
SMTP_HOST             = Variable.get("SMTP_HOST",              default_var=os.getenv("SMTP_HOST",              "smtp.gmail.com"))
SMTP_PORT             = int(Variable.get("SMTP_PORT",          default_var=os.getenv("SMTP_PORT",              "587")))
SMTP_USER             = Variable.get("SMTP_USER",              default_var=os.getenv("SMTP_USER",              ""))
SMTP_PASSWORD         = Variable.get("SMTP_PASSWORD",          default_var=os.getenv("SMTP_PASSWORD",          ""))
REPORT_LOOKBACK_HOURS = int(Variable.get("REPORT_LOOKBACK_HOURS", default_var=os.getenv("REPORT_LOOKBACK_HOURS", "24")))

default_args = {
    "owner":       "fraud_detection",
    "retries":     1,
    "retry_delay": timedelta(minutes=5),
}


# ── Tâche principale ──────────────────────────────────────────────────────────

def gen_daily_report(**context):
    """Génère et envoie le rapport de fraudes pour la période écoulée."""
    import psycopg2

    now   = datetime.utcnow()
    since = now - timedelta(hours=REPORT_LOOKBACK_HOURS)

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        # Statistiques globales
        cur.execute("""
            SELECT
                COUNT(*)                                                AS total,
                COALESCE(SUM(CASE WHEN is_fraud_predicted THEN 1 ELSE 0 END), 0) AS frauds,
                COALESCE(AVG(amt), 0)                                   AS avg_amount,
                COALESCE(SUM(CASE WHEN is_fraud_predicted THEN amt ELSE 0 END), 0) AS fraud_amount
            FROM real_time_transactions
            WHERE stored_at >= %s
        """, (since,))
        total, frauds, avg_amount, fraud_amount = cur.fetchone()

        # Répartition par catégorie
        cur.execute("""
            SELECT
                category,
                COUNT(*)                                                AS total,
                COALESCE(SUM(CASE WHEN is_fraud_predicted THEN 1 ELSE 0 END), 0) AS frauds
            FROM real_time_transactions
            WHERE stored_at >= %s
            GROUP BY category
            ORDER BY frauds DESC, total DESC
            LIMIT 10
        """, (since,))
        by_category = cur.fetchall()
    conn.close()

    fraud_rate  = (frauds / total * 100) if total else 0.0
    avg_amount  = float(avg_amount)
    fraud_amount = float(fraud_amount)

    report = {
        "period_start":             since.isoformat(),
        "period_end":               now.isoformat(),
        "lookback_hours":           REPORT_LOOKBACK_HOURS,
        "total_transactions":       int(total),
        "frauds_detected":          int(frauds),
        "fraud_rate_pct":           round(fraud_rate, 3),
        "avg_transaction_amount":   round(avg_amount, 2),
        "total_fraud_amount":       round(fraud_amount, 2),
        "top_categories": [
            {"category": r[0], "total": int(r[1]), "frauds": int(r[2])}
            for r in by_category
        ],
    }
    print(json.dumps(report, indent=2))

    subject = (
        f"[Rapport fraude] {now.strftime('%Y-%m-%d %H:%M')} UTC — "
        f"{frauds}/{total} fraudes ({fraud_rate:.2f}%)"
    )
    body = (
        f"RAPPORT DE DÉTECTION DE FRAUDE\n"
        f"Période : {since.strftime('%Y-%m-%d %H:%M')} → {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
        f"Transactions analysées      : {total:,}\n"
        f"Fraudes détectées           : {frauds:,} ({fraud_rate:.2f}%)\n"
        f"Montant total frauduleux    : ${fraud_amount:,.2f}\n"
        f"Montant moyen / transaction : ${avg_amount:,.2f}\n\n"
        f"TOP CATÉGORIES À RISQUE :\n"
    )
    for cat in by_category:
        rate = (cat[2] / cat[1] * 100) if cat[1] else 0
        body += f"  {(cat[0] or 'N/A'):30s} — {cat[2]:4d} fraudes / {cat[1]:6d} total ({rate:.1f}%)\n"

    print(body)

    if REPORT_EMAIL and SMTP_USER:
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"]    = SMTP_USER
            msg["To"]      = REPORT_EMAIL
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
                srv.starttls()
                srv.login(SMTP_USER, SMTP_PASSWORD)
                srv.sendmail(SMTP_USER, [REPORT_EMAIL], msg.as_string())
            print(f"[daily_report] Rapport envoyé à {REPORT_EMAIL}")
        except Exception as exc:
            print(f"[daily_report] WARN email : {exc}")
    else:
        print("[daily_report] Email non configuré (SMTP_USER ou REPORT_EMAIL manquant).")

    return json.dumps(report)


# ── DAG ───────────────────────────────────────────────────────────────────────

_schedule = f"0 */{max(1, REPORT_LOOKBACK_HOURS)} * * *"  # toutes les N heures

with DAG(
    dag_id="fraud_detection_daily_report",
    description=f"Rapport de fraudes toutes les {REPORT_LOOKBACK_HOURS} heures",
    schedule=_schedule,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["fraud", "report"],
) as dag:

    PythonOperator(
        task_id="gen_daily_report",
        python_callable=gen_daily_report,
    )
