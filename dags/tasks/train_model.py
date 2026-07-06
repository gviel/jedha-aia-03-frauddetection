import shutil
import subprocess
from pathlib import Path

import requests

from config import (
    APP_ENV, DATA_PATH, FRAUD_API_URL, MLFLOW_URI, MODEL_NAME, MODEL_RELOAD_TOKEN,
    PROJECT_CONFIG_PATH, SRC_DIR, WORK_DIR,
)

WORK_RAW_CSV      = WORK_DIR / "fraudTest.csv"
WORK_PREPARED_CSV = WORK_DIR / "fraudTest_prepared.csv"
CLIENT_STATS_CSV  = WORK_DIR / "client_trx_analysis.csv"


def _count_lines(path: Path) -> int:
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def branch_train(**context) -> str:
    """Décide la branche à suivre (specs.md §3.3) :
    - work/fraudTest.csv absent  → copy_data (premier entraînement)
    - plus de lignes que data/fraudTest.csv → prepare directement
    - sinon → stop_dag (rien de neuf)."""
    data_path = Path(DATA_PATH)

    if not WORK_RAW_CSV.exists():
        print(f"[train_model] {WORK_RAW_CSV} absent — premier entraînement nécessaire.")
        return "copy_data"

    n_data = _count_lines(data_path)
    n_work = _count_lines(WORK_RAW_CSV)
    if n_work > n_data:
        print(f"[train_model] {WORK_RAW_CSV} ({n_work} lignes) > {data_path} ({n_data} lignes) — entraînement déclenché.")
        return "prepare"

    print(f"[train_model] Pas de nouvelles données ({WORK_RAW_CSV}={n_work} <= {data_path}={n_data}) — skip.")
    return "stop_dag"


def copy_data(**context):
    """Copie data/fraudTest.csv vers work/fraudTest.csv (premier entraînement)."""
    WORK_RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA_PATH, WORK_RAW_CSV)
    print(f"[train_model] Copié {DATA_PATH} → {WORK_RAW_CSV}")


def prepare(**context):
    """Exécute prepare_dataset.py en subprocess (specs.md Phase 4 : pas de conteneur
    Docker séparé, trop complexe pour ce projet)."""
    cmd = [
        "python", str(SRC_DIR / "prepare_dataset.py"),
        "--input", str(WORK_RAW_CSV),
        "--output", str(WORK_PREPARED_CSV),
        "--client-stats", str(CLIENT_STATS_CSV),
    ]
    subprocess.run(cmd, check=True)


def train(**context):
    """Exécute train.py en subprocess. tag_and_save() (src/train.py) tague toujours le meilleur
    modèle de CE run avec status=best, même s'il est moins bon que le meilleur historique — donc
    on ne déclenche le reload de l'API que si ce nouveau modèle est bien devenu LE meilleur tous
    runs confondus (celui que l'API chargerait réellement), pas juste le meilleur de son propre
    cohort de 4 modèles."""
    cmd = [
        "python", str(SRC_DIR / "train.py"),
        "--data", str(WORK_PREPARED_CSV),
        "--config", str(PROJECT_CONFIG_PATH),
        "--env", APP_ENV,
    ]
    subprocess.run(cmd, check=True)

    if _new_model_is_global_best():
        _trigger_api_reload()
    else:
        print("[train_model] Nouveau modèle pas meilleur que le meilleur existant — reload API ignoré.")


def _new_model_is_global_best() -> bool:
    """Compare le run tagué status=best le plus récent (celui que ce train() vient de produire)
    au run tagué status=best ayant le plus haut pr_auc toutes exécutions confondues (= celui que
    l'API charge réellement, cf. api/app.py:_load_from_mlflow). Coïncidence -> ce run est bien
    devenu le meilleur global."""
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_URI)

        latest_best = mlflow.search_runs(
            experiment_names=[MODEL_NAME],
            filter_string="tags.status = 'best'",
            order_by=["start_time DESC"],
            max_results=1,
        )
        global_best = mlflow.search_runs(
            experiment_names=[MODEL_NAME],
            filter_string="tags.status = 'best'",
            order_by=["metrics.pr_auc DESC"],
            max_results=1,
        )
        if latest_best.empty or global_best.empty:
            return False
        return latest_best.iloc[0]["run_id"] == global_best.iloc[0]["run_id"]
    except Exception as exc:
        print(f"[train_model] WARN comparaison MLFlow best global : {exc}")
        return False


def _trigger_api_reload():
    if not MODEL_RELOAD_TOKEN:
        print("[train_model] MODEL_RELOAD_TOKEN non configuré — reload API non déclenché.")
        return
    try:
        resp = requests.post(
            f"{FRAUD_API_URL}/reload-model", params={"token": MODEL_RELOAD_TOKEN}, timeout=30,
        )
        resp.raise_for_status()
        print(f"[train_model] Reload API déclenché : {resp.json()}")
    except Exception as exc:
        print(f"[train_model] WARN reload API : {exc}")
