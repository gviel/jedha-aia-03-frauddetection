"""Configuration partagée entre les DAGs et les tâches (Variables Airflow > env)."""
import os
from pathlib import Path

from airflow.models import Variable


def _var(key: str, default: str) -> str:
    return Variable.get(key, default_var=os.getenv(key, default))


JEDHA_API_URL   = "https://sdacelo-real-time-fraud-detection.hf.space/current-transactions"
FRAUD_API_URL   = _var("FRAUD_API_URL",    "http://api:8000")
FRAUD_THRESHOLD = float(_var("FRAUD_THRESHOLD",  "0.7"))
MLFLOW_URI      = _var("MLFLOW_URI",       "https://gviel-mlflow37.hf.space/")
MODEL_NAME      = _var("MODEL_NAME",       "fraud_detection")
APP_ENV         = _var("APP_ENV",          "test")
DATABASE_URL    = _var("DATABASE_URL",     "postgresql://fraud:fraud@db:5432/fraud")
ALERT_EMAIL     = _var("FRAUD_ALERT_EMAIL","")
SMTP_HOST       = _var("SMTP_HOST",        "smtp.gmail.com")
SMTP_PORT       = int(_var("SMTP_PORT",    "587"))
SMTP_USER       = _var("SMTP_USER",        "")
SMTP_PASSWORD   = _var("SMTP_PASSWORD",    "")
S3_BUCKET       = _var("S3_BUCKET",        "bucket-fraud-detection-gviel")
WORK_DIR        = Path(_var("WORK_DIR",    "work"))
MODEL_RELOAD_TOKEN = _var("MODEL_RELOAD_TOKEN", "")

# ── DAG 3.3 : entraînement des modèles (prepare/train en subprocess, cf. specs.md
# Phase 4 : "pas de déport Docker dans un conteneur Docker car trop complexe") ─────
DATA_PATH              = _var("DATA_PATH",              "data/fraudTest.csv")
TRAIN_SCHEDULE_MINUTES  = int(_var("TRAIN_SCHEDULE_MINUTES", "60"))
SRC_DIR             = Path(_var("SRC_DIR",             "/opt/airflow/src"))
PROJECT_CONFIG_PATH = _var("PROJECT_CONFIG_PATH", "/opt/airflow/project_config/models.yaml")
