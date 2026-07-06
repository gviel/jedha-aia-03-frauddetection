"""
DAG Airflow — Collecte et analyse temps réel des transactions Jedha.

Chaîne d'exécution :
  fetch_trx → store_trx → fraud_detect → [branch]
    ├─ fraud_score ≥ THRESHOLD → send_fraud_alert_email
    ├─ sinon                   → end
    └─ toujours                → augment_training_data
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import BranchPythonOperator, PythonOperator

from tasks.augment_training_data import augment_training_data
from tasks.fetch_trx import fetch_trx
from tasks.fraud_detect import fraud_detect
from tasks.send_alert_email import send_fraud_alert_email
from tasks.store_trx import store_trx

default_args = {
    "owner":       "fraud_detection",
    "retries":     1,
    "retry_delay": timedelta(seconds=30),
}

with DAG(
    dag_id="fraud_detection_realtime",
    description="Collecte et analyse temps réel des transactions Jedha",
    schedule=timedelta(minutes=1),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["fraud", "realtime"],
) as dag:

    t_fetch   = PythonOperator(task_id="fetch_trx",              python_callable=fetch_trx)
    t_store   = PythonOperator(task_id="store_trx",              python_callable=store_trx)
    t_detect  = BranchPythonOperator(task_id="fraud_detect",     python_callable=fraud_detect)
    t_alert   = PythonOperator(task_id="send_fraud_alert_email", python_callable=send_fraud_alert_email)
    t_augment = PythonOperator(task_id="augment_training_data",  python_callable=augment_training_data)
    t_end     = EmptyOperator(task_id="end")

    t_fetch >> t_store >> t_detect >> [t_alert, t_end, t_augment]
