#!/usr/bin/env python3
"""
API de prédiction de fraude — FastAPI

  En test : charge le modèle depuis model/best_model.pkl
  En prod  : charge le meilleur run taggé status=best depuis MLFlow (artefact S3)

Endpoints :
  GET  /health   → statut du service et état du modèle
  POST /predict  → prédit si une transaction est frauduleuse
  GET  /docs     → Swagger UI (FastAPI natif)
"""
import asyncio
import math
import os
import pickle
from contextlib import asynccontextmanager

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status

from schemas import Transaction, PredictionResponse

load_dotenv()

MODEL_ENV        = os.getenv("MODEL_ENV", "test")
MLFLOW_URI       = os.getenv("MLFLOW_URI", "https://gviel-mlflow37.hf.space/")
MODEL_STATUS     = os.getenv("MODEL_STATUS", "best")
MODEL_NAME       = os.getenv("MODEL_NAME", "fraud_detection")
LOCAL_MODEL_PATH = os.getenv("MODEL_PATH", "model/best_model.pkl")
CLIENT_STATS_PATH = os.getenv("CLIENT_STATS_PATH", "work/client_trx_analysis.csv")
S3_BUCKET          = os.getenv("S3_BUCKET", "bucket-fraud-detection-gviel")
CLIENT_STATS_S3_KEY = os.getenv("CLIENT_STATS_S3_KEY", "work/client_trx_analysis.csv")
MODEL_RELOAD_TOKEN = os.getenv("MODEL_RELOAD_TOKEN", "")

# État global — mis à jour par _load_model_async au démarrage
_state: dict = {
    "model": None, "encoders": None, "features": None, "ready": False, "error": None,
    "client_avg_amt": {}, "client_avg_amt_fallback": 0.0, "model_name": None,
}


# ── Feature engineering (inférence) ──────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _client_id(trx: dict) -> str:
    """Reproduit id_client=last_first_gender_dob_zip (cf. src/prepare_dataset.py)."""
    return "_".join(str(trx.get(f, "")) for f in ("last", "first", "gender", "dob", "zip"))


def _build_features(trx: dict, client_avg_amt: dict, client_avg_amt_fallback: float) -> pd.DataFrame:
    ts_ms = trx.get("current_time") or ((trx.get("unix_time") or 0) * 1000)
    dt = pd.to_datetime(ts_ms / 1000, unit="s", utc=True)

    avg_mnt = client_avg_amt.get(_client_id(trx), client_avg_amt_fallback)

    # trx.get(key, default) ne suffit pas : Transaction.model_dump() inclut toujours toutes
    # les clés Optional avec la valeur None (pas absentes) — d'où (trx.get(key) or default).
    return pd.DataFrame([{
        "amt":          trx["amt"],
        "zip":          str(trx.get("zip") or ""),
        "lat":          trx["lat"],
        "long":         trx["long"],
        "city_pop":     trx.get("city_pop") or 0,
        "merch_lat":    trx["merch_lat"],
        "merch_long":   trx["merch_long"],
        "distance_km":  _haversine_km(trx["lat"], trx["long"], trx["merch_lat"], trx["merch_long"]),
        "diff_avg_amt": trx["amt"] - avg_mnt,
        "hour":         int(dt.hour),
        "dow":          int(dt.dayofweek),
        "gender":       str(trx.get("gender") or ""),
        "state":        str(trx.get("state") or ""),
        "category":     str(trx.get("category") or ""),
        "merchant":     str(trx.get("merchant") or ""),
        "job":          str(trx.get("job") or ""),
    }])


def _apply_encoders(df: pd.DataFrame, encoders: dict) -> pd.DataFrame:
    df = df.copy()
    for col, le in encoders.items():
        if col in df.columns:
            known = set(le.classes_)
            df[col] = df[col].apply(lambda v: v if v in known else le.classes_[0])
            df[col] = le.transform(df[col].astype(str))
    return df


# ── Chargement du modèle ──────────────────────────────────────────────────────

def _download_client_stats_from_s3() -> None:
    """En prod, work/client_trx_analysis.csv n'existe pas sur le disque du conteneur (pas de
    volume partagé avec l'entraînement, cf. specs.md Phase 2/5) — on le télécharge depuis S3.
    Toute erreur (fichier absent, credentials manquantes, etc.) est avalée : _load_client_stats
    retombe alors sur son repli habituel (moyenne globale à 0.0)."""
    try:
        import boto3
        parent = os.path.dirname(CLIENT_STATS_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        boto3.client("s3").download_file(S3_BUCKET, CLIENT_STATS_S3_KEY, CLIENT_STATS_PATH)
        print(f"[API] Stats client téléchargées depuis s3://{S3_BUCKET}/{CLIENT_STATS_S3_KEY}")
    except Exception as exc:
        print(f"[API] Échec téléchargement s3://{S3_BUCKET}/{CLIENT_STATS_S3_KEY} ({exc}) — "
              f"diff_avg_amt utilisera un fallback à 0.")


def _load_client_stats() -> None:
    if MODEL_ENV in ("prod", "staging") and not os.path.exists(CLIENT_STATS_PATH):
        _download_client_stats_from_s3()

    if not os.path.exists(CLIENT_STATS_PATH):
        print(f"[API] Stats client absentes ({CLIENT_STATS_PATH}) — diff_avg_amt utilisera un fallback à 0.")
        return
    stats = pd.read_csv(CLIENT_STATS_PATH)
    _state["client_avg_amt"] = dict(zip(stats["id_client"], stats["avg_mnt"]))
    _state["client_avg_amt_fallback"] = float(stats["avg_mnt"].mean())
    print(f"[API] Stats client chargées depuis {CLIENT_STATS_PATH} ({len(stats)} clients)")


def _load_local() -> None:
    with open(LOCAL_MODEL_PATH, "rb") as f:
        artifacts = pickle.load(f)
    _state["model"]      = artifacts["model"]
    _state["encoders"]   = artifacts["encoders"]
    _state["features"]   = artifacts["features"]
    _state["model_name"] = artifacts.get("model_name", "?")
    _state["ready"]      = True
    print(f"[API] Modèle chargé depuis {LOCAL_MODEL_PATH} ({artifacts.get('model_name', '?')})")


def _load_from_mlflow() -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.tracking.MlflowClient()
    runs = mlflow.search_runs(
        experiment_names=[MODEL_NAME],
        filter_string=f"tags.status = '{MODEL_STATUS}'",
        order_by=["metrics.pr_auc DESC"],
        max_results=1,
    )
    if runs.empty:
        raise RuntimeError(f"Aucun modèle taggé status={MODEL_STATUS} trouvé dans MLFlow.")

    run_id = runs.iloc[0]["run_id"]
    model  = mlflow.sklearn.load_model(f"runs:/{run_id}/model")

    run_data = client.get_run(run_id)
    encoders, features = {}, []
    try:
        # Encoders/features poussés par train.py --env prod (préprocessing.pkl, cf.
        # tag_and_save) — introuvable pour les runs entraînés avant ce fix.
        prep_path = mlflow.artifacts.download_artifacts(
            f"runs:/{run_id}/preprocessing/preprocessing.pkl"
        )
        with open(prep_path, "rb") as f:
            art = pickle.load(f)
        encoders = art.get("encoders", {})
        features = art.get("features", [])
    except Exception:
        # Repli : ancien mécanisme test-only (tag local_pkl_path, cf. tag_and_save env=test)
        local_pkl = run_data.data.tags.get("local_pkl_path")
        if local_pkl and os.path.exists(local_pkl):
            with open(local_pkl, "rb") as f:
                art = pickle.load(f)
            encoders = art.get("encoders", {})
            features = art.get("features", [])

    model_class = run_data.data.tags.get("model_class", "?")
    run_name    = run_data.data.tags.get("mlflow.runName", "?")

    _state["model"]      = model
    _state["encoders"]   = encoders
    _state["features"]   = features
    _state["model_name"] = f"{run_name} ({model_class})"
    _state["ready"]      = True
    print(f"[API] Modèle chargé depuis MLFlow (run_id={run_id}, {run_name})")


async def _load_model_async() -> None:
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _load_client_stats)
        if MODEL_ENV in ("prod", "staging"):
            await loop.run_in_executor(None, _load_from_mlflow)
        else:
            await loop.run_in_executor(None, _load_local)
    except Exception as exc:
        _state["error"] = str(exc)
        print(f"[API] ERREUR chargement modèle : {exc}")


# ── Application FastAPI ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[API] Démarrage en mode {MODEL_ENV.upper()} — chargement asynchrone du modèle...")
    asyncio.create_task(_load_model_async())
    yield
    print("[API] Arrêt")


app = FastAPI(
    title="Fraud Detection API",
    description="API de prédiction de fraude bancaire — Jedha Certification Bloc 3",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", summary="Statut du service")
def health():
    return {
        "status":       "ready" if _state["ready"] else ("error" if _state["error"] else "loading"),
        "env":          MODEL_ENV,
        "model_loaded": _state["ready"],
        "error":        _state.get("error"),
        "model_name":   _state.get("model_name"),
        "api_version":  app.version,
    }


@app.post("/reload-model", summary="Recharger le modèle (déclenché par le DAG 3.3 après entraînement)")
def reload_model(token: str = ""):
    """Protégé par une valeur secrète partagée (MODEL_RELOAD_TOKEN, cf. dags/tasks/train_model.py) —
    pas d'auth utilisateur ici, seul le DAG d'entraînement est censé appeler cet endpoint."""
    if not MODEL_RELOAD_TOKEN or token != MODEL_RELOAD_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token invalide ou reload non configuré.")

    _state["ready"] = False
    _state["error"] = None
    try:
        _load_client_stats()
        if MODEL_ENV in ("prod", "staging"):
            _load_from_mlflow()
        else:
            _load_local()
    except Exception as exc:
        _state["error"] = str(exc)
        raise HTTPException(status_code=500, detail=f"Échec du rechargement : {exc}")

    return {"status": "reloaded", "model_name": _state.get("model_name")}


@app.post(
    "/predict",
    response_model=PredictionResponse,
    summary="Prédire si une transaction est frauduleuse",
)
def predict(trx: Transaction):
    if not _state["ready"]:
        detail = (f"Modèle non disponible : {_state['error']}" if _state["error"]
                  else "Modèle en cours de chargement — réessayez dans quelques secondes.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)

    df = _build_features(trx.model_dump(), _state["client_avg_amt"], _state["client_avg_amt_fallback"])
    df = _apply_encoders(df, _state["encoders"])

    available_features = [f for f in _state["features"] if f in df.columns]
    X = df[available_features]

    model = _state["model"]
    if hasattr(model, "predict_proba"):
        score = float(model.predict_proba(X)[:, 1][0])
    elif hasattr(model, "decision_function"):
        raw   = float(model.decision_function(X)[0])
        score = float(max(0.0, min(1.0, (0.0 - raw + 1.0) / 2.0)))
    else:
        score = float(np.clip(model.predict(X)[0], 0.0, 1.0))

    threshold = 0.5
    return PredictionResponse(
        trans_num=trx.trans_num,
        is_fraud=score >= threshold,
        fraud_score=round(score, 6),
        threshold=threshold,
    )
