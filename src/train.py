#!/usr/bin/env python3
"""
Entraînement et sélection du meilleur modèle de détection de fraude.

Charge le dataset préparé, entraîne chaque modèle défini dans config/models.yaml,
évalue les métriques (f1, recall, precision, accuracy, ROC-AUC, PR-AUC),
log vers MLFlow et tague best / challenger / worst selon le PR-AUC.

  En test : sauvegarde le meilleur modèle localement dans model/best_model.pkl
  En prod : pousse les artefacts dans le bucket S3 de MLFlow

Usage :
    python src/train.py
    python src/train.py --config config/models.yaml --env prod
    python src/train.py --data work/fraudTest_prepared.csv --env test

Logs : work/logs/train_<YYYYMMDD_HHMMSS>.log
"""
import argparse
import importlib
import logging
import os
import pickle
import sys
import tempfile
import time
import warnings
from datetime import datetime
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

load_dotenv(".env.test")
load_dotenv(".env.production")  # additif (DATABASE_URL_PROD, AWS_*) — n'écrase pas .env.test
warnings.filterwarnings("ignore")

# ── Constantes ────────────────────────────────────────────────────────────────

FEATURES = [
    "amt", "zip", "lat", "long", "city_pop",
    "merch_lat", "merch_long", "distance_km", "diff_avg_amt",
    "hour", "dow",
    "gender", "state", "category", "merchant", "job",
]
CAT_FEATURES = ["gender", "state", "category", "merchant", "job", "zip"]
TARGET    = "is_fraud"
MODEL_DIR = Path("model")


# ── Logger ────────────────────────────────────────────────────────────────────

def setup_logger(log_dir: str = "work/logs") -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(log_dir) / f"train_{stamp}.log"

    fmt     = "[%(asctime)s] %(levelname)-5s %(name)s - %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger("train")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt))

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(fmt, datefmt))

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.info("Log initialisé → %s", log_path)
    return logger


# ── Chargement des données ────────────────────────────────────────────────────

def load_dataset(path: str, log: logging.Logger):
    df = pd.read_csv(path, index_col=0)

    encoders = {}
    for col in CAT_FEATURES:
        if col in df.columns:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].fillna("__missing__").astype(str))
            encoders[col] = le
            log.debug("LabelEncoder ajusté sur '%s' (%d classes)", col, len(le.classes_))

    available = [f for f in FEATURES if f in df.columns]
    missing   = [f for f in FEATURES if f not in df.columns]
    if missing:
        log.warning("Features absentes du dataset (ignorées) : %s", missing)

    X = df[available].copy()
    y = df[TARGET].astype(int)
    return X, y, encoders, available


# ── Rééchantillonnage (train set uniquement, après le split) ─────────────────

def apply_resampling(X_train: pd.DataFrame, y_train: pd.Series, cfg: dict, log: logging.Logger):
    method = cfg.get("method", "none")
    if method == "none":
        return X_train, y_train

    random_state       = cfg.get("random_state", 42)
    sampling_strategy   = cfg.get("sampling_strategy", "auto")

    if method == "under_sample":
        sampler = RandomUnderSampler(sampling_strategy=sampling_strategy, random_state=random_state)
    elif method == "smote":
        sampler = SMOTE(sampling_strategy=sampling_strategy,
                        k_neighbors=cfg.get("k_neighbors", 5), random_state=random_state)
    else:
        raise ValueError(f"Méthode de rééchantillonnage inconnue : {method}")

    X_res, y_res = sampler.fit_resample(X_train, y_train)
    n_neg, n_pos = int((y_res == 0).sum()), int((y_res == 1).sum())
    log.info("Rééchantillonnage (%s, sampling_strategy=%s) : %s → %s exemples  (%d normaux / %d fraudes)",
             method, sampling_strategy, f"{len(X_train):,}", f"{len(X_res):,}", n_neg, n_pos)
    return X_res, y_res


# ── Instanciation des modèles ─────────────────────────────────────────────────

def instantiate_model(cfg: dict, scale_pos_weight: float = 1.0):
    module_path, class_name = cfg["class"].rsplit(".", 1)
    cls = getattr(importlib.import_module(module_path), class_name)
    params = {
        k: v for k, v in cfg.get("params", {}).items()
        if k not in ("scale_pos_weight",) or v != "auto"
    }
    if cfg.get("params", {}).get("scale_pos_weight") == "auto":
        params["scale_pos_weight"] = scale_pos_weight
    model = cls(**params)

    if cfg.get("scale_features"):
        # zip/city_pop (dizaines de milliers) vs lat/long (~100) font converger lbfgs
        # très lentement sans standardisation — sans impact sur les modèles arbre.
        model = make_pipeline(StandardScaler(), model)
    return model


# ── Scoring ───────────────────────────────────────────────────────────────────

def get_fraud_scores(model, X: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    return np.clip(model.predict(X).astype(float), 0.0, 1.0)


def compute_metrics(y_true, y_prob) -> dict:
    y_prob = np.asarray(y_prob)
    y_pred = (y_prob >= 0.5).astype(int)
    return {
        "f1":        float(f1_score(y_true, y_pred, zero_division=0)),
        "recall":    float(recall_score(y_true, y_pred, zero_division=0)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "accuracy":  float(accuracy_score(y_true, y_pred)),
        "roc_auc":   float(roc_auc_score(y_true, y_prob)),
        "pr_auc":    float(average_precision_score(y_true, y_prob)),
    }


# ── Boucle d'entraînement ────────────────────────────────────────────────────

def train_all(config: dict, X_train, X_test, y_train, y_test,
              encoders: dict, features: list, env: str,
              log: logging.Logger) -> list:

    # En test : tracking local (jamais l'expérience hébergée partagée avec la prod), puisque ces
    # runs ne sont jamais servis (pas de log_model/log_artifact ci-dessous) — évite d'accumuler
    # des runs de dev/itération dans l'historique MLFlow partagé (cf. CLAUDE.md). Store SQLite
    # (pas le store fichier "work/mlruns" : mlflow le déprécie au profit d'un backend base de
    # données, cf. FutureWarning de mlflow.tracking._tracking_service.utils).
    tracking_uri = (os.getenv("MLFLOW_URI", "https://gviel-mlflow37.hf.space/") if env == "prod"
                    else "sqlite:///work/mlflow_local.db")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(config.get("experiment_name", "fraud_detection"))
    log.info("MLFlow tracking URI : %s", mlflow.get_tracking_uri())

    n_neg, n_pos = int((y_train == 0).sum()), int((y_train == 1).sum())
    scale_pos_weight = n_neg / n_pos

    results = []

    for model_cfg in config["models"]:
        name = model_cfg["name"]

        log.info("─" * 50)
        log.info("Modèle : %s  (déséquilibre train : %.1f×, %d normaux / %d fraudes)",
                 name, scale_pos_weight, n_neg, n_pos)

        with mlflow.start_run(run_name=name) as run:
            run_id = run.info.run_id
            mlflow.log_params(model_cfg.get("params", {}))
            mlflow.set_tag("env", env)
            mlflow.set_tag("model_class", model_cfg["class"])
            mlflow.set_tag("status", "running")

            try:
                model = instantiate_model(model_cfg, scale_pos_weight)

                log.info("  Entraînement sur %s exemples...", f"{len(X_train):,}")
                train_start = time.perf_counter()
                model.fit(X_train, y_train)
                train_seconds = time.perf_counter() - train_start
                mlflow.log_metric("train_seconds", train_seconds)
                log.info("  Temps d'entraînement : %.1f s", train_seconds)

                log.info("  Évaluation sur %s exemples de test...", f"{len(X_test):,}")
                y_prob  = get_fraud_scores(model, X_test)
                metrics = compute_metrics(y_test, y_prob)
                mlflow.log_metrics(metrics)

                log.info("  f1=%.4f  recall=%.4f  precision=%.4f  pr_auc=%.4f  roc_auc=%.4f",
                         metrics["f1"], metrics["recall"], metrics["precision"],
                         metrics["pr_auc"], metrics["roc_auc"])
                report = classification_report(
                    y_test, (y_prob >= 0.5).astype(int),
                    target_names=["légitime", "fraude"], zero_division=0,
                )
                for line in report.splitlines():
                    log.debug("    %s", line)

                if env == "prod":
                    mlflow.sklearn.log_model(model, artifact_path="model")
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        prep_path = os.path.join(tmp_dir, "preprocessing.pkl")
                        with open(prep_path, "wb") as f:
                            pickle.dump({"encoders": encoders, "features": features}, f)
                        mlflow.log_artifact(prep_path, artifact_path="preprocessing")
                    log.info("  Modèle + encoders/features poussés vers MLFlow S3 (run_id=%s)", run_id)

                results.append({
                    "model_name":    name,
                    "run_id":        run_id,
                    "model":         model,
                    "metrics":       metrics,
                    "pr_auc":        metrics["pr_auc"],
                    "train_seconds": train_seconds,
                })

            except Exception as exc:
                log.error("  ERREUR [%s] : %s", name, exc, exc_info=True)
                mlflow.set_tag("error", str(exc))
                mlflow.set_tag("status", "failed")

    return sorted(results, key=lambda r: r["pr_auc"], reverse=True)


# ── Tagging et sauvegarde ─────────────────────────────────────────────────────

def tag_and_save(results: list, encoders: dict, features: list, env: str,
                 log: logging.Logger) -> None:
    if not results:
        log.error("Aucun modèle entraîné avec succès.")
        return

    client = mlflow.tracking.MlflowClient()

    log.info("─" * 50)
    log.info("Classement final (par PR-AUC) :")
    for i, r in enumerate(results):
        tag = "best" if i == 0 else ("worst" if i == len(results) - 1 else "challenger")
        client.set_tag(r["run_id"], "status", tag)
        log.info("  [%10s]  %-40s  pr_auc=%.4f  train=%.1fs",
                 tag, r["model_name"], r["pr_auc"], r["train_seconds"])

    best = results[0]
    log.info("Meilleur modèle : %s  (pr_auc=%.4f)", best["model_name"], best["pr_auc"])

    if env == "test":
        MODEL_DIR.mkdir(exist_ok=True)
        pkl_path = MODEL_DIR / "best_model.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump({
                "model":      best["model"],
                "model_name": best["model_name"],
                "encoders":   encoders,
                "features":   features,
                "metrics":    best["metrics"],
                "run_id":     best["run_id"],
            }, f)
        log.info("Modèle sauvegardé : %s", pkl_path)
        client.set_tag(best["run_id"], "local_pkl_path", str(pkl_path.resolve()))
    else:
        log.info("Modèle déjà poussé vers S3 via MLFlow.")


# ── Main ──────────────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Entraîne les modèles de détection de fraude")
    parser.add_argument("--config",  default="config/models.yaml")
    parser.add_argument("--data",    default="work/fraudTest_prepared.csv")
    parser.add_argument("--env",     default=os.getenv("APP_ENV", "test"), choices=["test", "prod"])
    parser.add_argument("--log-dir", default="work/logs")
    args = parser.parse_args()

    log = setup_logger(args.log_dir)
    log.info("Environnement : %s", args.env.upper())

    config = load_config(args.config)
    log.info("Modèles à entraîner : %s", [m["name"] for m in config["models"]])

    log.info("Chargement du dataset préparé : %s", args.data)
    X, y, encoders, features = load_dataset(args.data, log)
    log.info("%s échantillons — %d features : %s", f"{len(X):,}", len(features), features)

    test_size = float(config.get("test_size", 0.2))
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y,
    )
    log.info("Split (test_size=%.2f) : train=%s  test=%s", test_size, f"{len(X_train):,}", f"{len(X_test):,}")

    resampling_cfg = config.get("resampling", {"method": "none"})
    X_train, y_train = apply_resampling(X_train, y_train, resampling_cfg, log)

    results = train_all(config, X_train, X_test, y_train, y_test,
                        encoders, features, args.env, log)
    tag_and_save(results, encoders, features, args.env, log)
    log.info("Terminé.")


if __name__ == "__main__":
    main()
