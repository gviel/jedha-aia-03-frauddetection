"""
DAG Airflow — Entraînement ponctuel des modèles (Phase 3.3).

prepare_dataset.py et train.py tournent en subprocess directement dans le
conteneur Airflow (specs.md Phase 4 : "pas de déport Docker dans un conteneur
Docker car trop complexe" — plus de conteneur fraud-train séparé/docker-outside
-of-docker).

Chaîne d'exécution (specs.md §3.3) :
  branch_train (BranchPythonOperator) :
    - work/fraudTest.csv absent   → copy_data >> prepare >> train
    - work/fraudTest.csv a grandi → prepare >> train (déjà présent)
    - sinon                       → stop_dag
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import BranchPythonOperator, PythonOperator

from config import TRAIN_SCHEDULE_MINUTES
from tasks.train_model import branch_train, copy_data, prepare, train

default_args = {
    "owner":       "fraud_detection",
    "retries":     1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="fraud_detection_train_model",
    description="Réentraîne les modèles (subprocess) si de nouvelles données sont disponibles",
    schedule=timedelta(minutes=TRAIN_SCHEDULE_MINUTES),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["fraud", "training"],
) as dag:

    t_branch    = BranchPythonOperator(task_id="branch_train", python_callable=branch_train)
    t_copy_data = PythonOperator(task_id="copy_data", python_callable=copy_data)
    # none_failed_min_one_success : prepare est atteignable soit via copy_data
    # (skipped si la branche directe est choisie), soit directement depuis branch_train.
    t_prepare = PythonOperator(
        task_id="prepare",
        python_callable=prepare,
        trigger_rule="none_failed_min_one_success",
    )
    t_train = PythonOperator(task_id="train", python_callable=train)
    t_stop  = EmptyOperator(task_id="stop_dag")

    t_branch >> t_copy_data >> t_prepare
    t_branch >> t_prepare
    t_branch >> t_stop
    t_prepare >> t_train
