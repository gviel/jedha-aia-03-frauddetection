#!/usr/bin/env python3
"""
Préparation du dataset historique pour l'entraînement.

Travaille sur work/fraudTest.csv (déjà présent — copié depuis data/fraudTest.csv par le DAG
Model Training, task copy_data, cf. specs.md §3.3 : ce script ne connaît que work/) : analyse
exploratoire, exclusion nulls/doublons puis feature engineering :
  - distance_km   : distance géographique client ↔ marchand
  - hour, dow     : heure et jour de semaine extraits du timestamp
  - diff_avg_amt  : écart entre le montant de la transaction et le montant
                     moyen historique du client (id_client=last_first_gender_dob_zip)
  - Suppression des champs inutiles (identifiants personnels)

Produit aussi work/client_trx_analysis.csv (id_client, avg_mnt, avg_frequency)
utilisé par l'API pour recalculer diff_avg_amt à l'inférence.

Usage :
    python src/prepare_dataset.py
    python src/prepare_dataset.py --input work/fraudTest.csv --output work/fraudTest_prepared.csv

Logs : work/logs/prepare_dataset_<YYYYMMDD_HHMMSS>.log
"""
import argparse
import logging
import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    from geopy.distance import geodesic
    _USE_GEOPY = True
except ImportError:
    _USE_GEOPY = False


# ── Logger ────────────────────────────────────────────────────────────────────

def setup_logger(log_dir: str = "work/logs") -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(log_dir) / f"prepare_dataset_{stamp}.log"

    fmt     = "[%(asctime)s] %(levelname)-5s %(name)s - %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger("prepare_dataset")
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


# ── Distance ──────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _distance_km(row) -> float:
    if _USE_GEOPY:
        return geodesic((row["lat"], row["long"]), (row["merch_lat"], row["merch_long"])).km
    return _haversine_km(row["lat"], row["long"], row["merch_lat"], row["merch_long"])


# ── Analyse exploratoire ───────────────────────────────────────────────────────

def analyze(df: pd.DataFrame, log: logging.Logger) -> None:
    log.info("=" * 60)
    log.info("ANALYSE DU DATASET")
    log.info("=" * 60)
    log.info("Effectif total      : %s", f"{len(df):,}")
    log.info("Nombre de colonnes  : %d", len(df.columns))

    nulls = df.isnull().sum()
    nulls = nulls[nulls > 0]
    if nulls.empty:
        log.info("Valeurs nulles      : aucune")
    else:
        log.warning("Valeurs nulles détectées :\n%s", nulls.to_string())

    fraud_count = int(df["is_fraud"].sum())
    total = len(df)
    log.info("Répartition fraude / légitime :")
    log.info("  Fraudes   : %s  (%.3f%%)", f"{fraud_count:,}", fraud_count / total * 100)
    log.info("  Légitimes : %s  (%.3f%%)", f"{total - fraud_count:,}", (total - fraud_count) / total * 100)

    dupes = df.duplicated(subset=["trans_num"]).sum()
    if dupes:
        log.warning("Doublons (trans_num) : %d", dupes)
    else:
        log.info("Doublons (trans_num) : aucun")

    ts_from_str = pd.to_datetime(df["trans_date_trans_time"]).astype("int64") // 10 ** 9
    diff_check  = df["unix_time"] - ts_from_str
    log.info("Décalage unix_time / trans_date_trans_time (s) : min=%.0f  max=%.0f  std=%.4f",
             diff_check.min(), diff_check.max(), diff_check.std())
    if diff_check.std() < 1.0:
        log.info("  => décalage CONSTANT — les deux champs sont cohérents")
    else:
        log.warning("  => décalage VARIABLE — incohérence entre unix_time et trans_date_trans_time")

    log.info("=" * 60)


# ── Exclusion nulls / doublons ────────────────────────────────────────────────

def exclude_invalid(df: pd.DataFrame, log: logging.Logger) -> pd.DataFrame:
    before = len(df)

    df = df.dropna()
    after_na = len(df)
    if after_na < before:
        log.warning("Lignes exclues (valeurs nulles) : %d", before - after_na)

    df = df.drop_duplicates(subset=["trans_num"])
    after_dupes = len(df)
    if after_dupes < after_na:
        log.warning("Lignes exclues (doublons trans_num) : %d", after_na - after_dupes)

    log.info("Effectif après exclusion : %s  (%d lignes retirées)",
             f"{after_dupes:,}", before - after_dupes)
    return df


# ── Statistiques client (pour diff_avg_amt) ───────────────────────────────────

def compute_client_stats(df: pd.DataFrame, log: logging.Logger, output_path: str) -> pd.Series:
    """Calcule id_client=last_first_gender_dob_zip, sauvegarde avg_mnt/avg_frequency
    par client dans work/client_trx_analysis.csv, et retourne diff_avg_amt aligné sur df."""
    id_client = (
        df["last"].astype(str) + "_" + df["first"].astype(str) + "_" +
        df["gender"].astype(str) + "_" + df["dob"].astype(str) + "_" + df["zip"].astype(str)
    )

    duration_days = max((df["unix_time"].max() - df["unix_time"].min()) / 86400.0, 1.0)

    grouped = df.groupby(id_client)["amt"].agg(avg_mnt="mean", n_trx="count")
    grouped["avg_frequency"] = grouped["n_trx"] / duration_days
    client_stats = grouped[["avg_mnt", "avg_frequency"]].reset_index(names="id_client")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    client_stats.to_csv(output_path, index=False)
    log.info("Stats clients sauvegardées → %s  (%d clients uniques)", output_path, len(client_stats))
    log.info("  Fréquence moyenne de transactions/client : %.4f /jour", client_stats["avg_frequency"].mean())

    diff_avg_amt = df["amt"] - id_client.map(client_stats.set_index("id_client")["avg_mnt"])
    return diff_avg_amt


# ── Feature engineering ───────────────────────────────────────────────────────

def feature_engineering(df: pd.DataFrame, log: logging.Logger, client_stats_path: str) -> pd.DataFrame:
    log.info("Feature engineering en cours...")

    dt = pd.to_datetime(df["trans_date_trans_time"])
    df["date"] = dt.dt.date
    df["time"] = dt.dt.time
    df["hour"] = dt.dt.hour
    df["dow"]  = pd.to_datetime(df["unix_time"], unit="s").dt.dayofweek
    log.debug("Colonnes temporelles ajoutées : date, time, hour, dow")
    log.info("  Jour de semaine le plus fréquent (dow) : %d  (0=lundi)", df["dow"].mode().iloc[0])

    lib = "geopy" if _USE_GEOPY else "haversine"
    log.info("Calcul distance_km (%s)...", lib)
    df["distance_km"] = df.apply(_distance_km, axis=1).round().astype(int)
    log.info("  distance_km : min=%d km  max=%d km  mean=%.2f km",
             df["distance_km"].min(), df["distance_km"].max(), df["distance_km"].mean())

    log.info("Calcul diff_avg_amt (montant vs moyenne historique du client)...")
    df["diff_avg_amt"] = compute_client_stats(df, log, client_stats_path)
    log.info("  diff_avg_amt : min=%.2f  max=%.2f  mean=%.2f",
             df["diff_avg_amt"].min(), df["diff_avg_amt"].max(), df["diff_avg_amt"].mean())

    df = df.set_index("trans_num")

    drop_cols = ["cc_num", "first", "last", "street", "dob", "trans_date_trans_time"]
    dropped   = [c for c in drop_cols if c in df.columns]
    df.drop(columns=dropped, inplace=True)
    log.debug("Colonnes supprimées : %s", dropped)
    log.info("Colonnes finales (%d) : %s", len(df.columns), list(df.columns))

    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Prépare le dataset historique pour l'entraînement")
    parser.add_argument("--input",        default="work/fraudTest.csv",          help="Copie de travail (déjà créée par le DAG, cf. task copy_data)")
    parser.add_argument("--output",       default="work/fraudTest_prepared.csv", help="CSV préparé de sortie")
    parser.add_argument("--client-stats", default="work/client_trx_analysis.csv", help="CSV des stats client en sortie")
    parser.add_argument("--log-dir",      default="work/logs",                  help="Répertoire des logs")
    parser.add_argument("--skip-analysis",action="store_true",                  help="Passer l'analyse exploratoire")
    args = parser.parse_args()

    log = setup_logger(args.log_dir)
    if not _USE_GEOPY:
        log.warning("geopy absent — utilisation de la formule haversine interne")

    log.info("Chargement depuis %s...", args.input)
    df = pd.read_csv(args.input, index_col=0)
    log.info("  %s lignes chargées", f"{len(df):,}")

    if not args.skip_analysis:
        analyze(df, log)

    df = exclude_invalid(df, log)
    df_prepared = feature_engineering(df, log, args.client_stats)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df_prepared.to_csv(args.output)
    log.info("Dataset préparé sauvegardé → %s  (%s lignes)", args.output, f"{len(df_prepared):,}")


if __name__ == "__main__":
    main()
