"""
Dashboard Streamlit de suivi des transactions — Jedha Certification Bloc 3 (specs.md Phase 6).

Affiche les transactions temps réel stockées par le DAG ETL & Fraud Detection
(table `real_time_transactions`), avec code couleur par score de fraude et
filtres (jour, niveau de fraude). Affiche aussi l'état de l'API/modèle via /health.
"""
import os
from datetime import date

import pandas as pd
import psycopg2
import requests
import streamlit as st

DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://fraud:fraud@fraud-db:5432/fraud")
FRAUD_API_URL = os.getenv("FRAUD_API_URL", "http://fraud-detection-api:8000")

st.set_page_config(page_title="Fraud Detection — Suivi", layout="wide")

LEVELS = {
    "Toutes les transactions": None,
    "🔴 Rouge (score > 0.9)":          lambda s: s > 0.9,
    "🟠 Orange (0.7 < score ≤ 0.9)":   lambda s: 0.7 < s <= 0.9,
    "🟡 Jaune (0.5 < score ≤ 0.7)":    lambda s: 0.5 < s <= 0.7,
    "🟢 Vert (score ≤ 0.5)":           lambda s: s <= 0.5,
    "Toutes les fraudes détectées":   None,  # géré séparément (is_fraud_predicted)
}


def _color_for_score(score: float) -> str:
    if score is None:
        return "#808080"
    if score > 0.9:
        return "#e74c3c"   # rouge
    if score > 0.7:
        return "#e67e22"   # orange
    if score > 0.5:
        return "#f1c40f"   # jaune
    return "#2ecc71"       # vert


@st.cache_data(ttl=10)
def load_transactions(day: date) -> pd.DataFrame:
    query = """
        SELECT trans_num, stored_at, merchant, category, amt, state,
               is_fraud_predicted, fraud_score
        FROM real_time_transactions
        WHERE stored_at::date = %s
        ORDER BY stored_at DESC
    """
    with psycopg2.connect(DATABASE_URL) as conn:
        return pd.read_sql(query, conn, params=(day,))


def load_api_health() -> dict | None:
    try:
        resp = requests.get(f"{FRAUD_API_URL}/health", timeout=3)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


# ── En-tête : statut API / modèle ─────────────────────────────────────────────

st.title("🕵️ Fraud Detection — Suivi des transactions")

health = load_api_health()
cols = st.columns(4)
if health:
    cols[0].metric("Statut API", health.get("status", "?"))
    cols[1].metric("Environnement", health.get("env", "?"))
    cols[2].metric("Modèle", health.get("model_name") or "?")
    cols[3].metric("Version API", health.get("api_version", "?"))
else:
    st.warning(f"API de prédiction injoignable ({FRAUD_API_URL}) — infos modèle indisponibles.")

st.divider()

# ── Filtres ────────────────────────────────────────────────────────────────────

col_date, col_level, col_refresh = st.columns([2, 3, 1])
with col_date:
    selected_day = st.date_input("Jour", value=date.today())
with col_level:
    level_label = st.selectbox("Niveau de fraude", list(LEVELS.keys()))
with col_refresh:
    st.write("")
    if st.button("🔄 Rafraîchir"):
        st.cache_data.clear()

df = load_transactions(selected_day)

if df.empty:
    st.info(f"Aucune transaction trouvée pour le {selected_day.strftime('%Y-%m-%d')}.")
else:
    if level_label == "Toutes les fraudes détectées":
        df = df[df["is_fraud_predicted"] == True]  # noqa: E712
    else:
        predicate = LEVELS[level_label]
        if predicate is not None:
            df = df[df["fraud_score"].apply(lambda s: predicate(s) if pd.notna(s) else False)]

    st.caption(f"{len(df)} transaction(s) — {selected_day.strftime('%Y-%m-%d')}, la plus récente en premier")

    display_df = df.copy()
    display_df["stored_at"]   = display_df["stored_at"].dt.strftime("%H:%M:%S")
    display_df["fraud_score"] = display_df["fraud_score"].map(lambda s: f"{s:.2%}" if pd.notna(s) else "—")
    display_df = display_df.rename(columns={
        "trans_num":          "Transaction",
        "stored_at":          "Heure",
        "merchant":           "Marchand",
        "category":           "Catégorie",
        "amt":                "Montant ($)",
        "state":              "État",
        "is_fraud_predicted": "Fraude ?",
        "fraud_score":        "Score",
    })

    def _row_style(row):
        score = df.loc[row.name, "fraud_score"]
        color = _color_for_score(score) if pd.notna(score) else "#808080"
        return [f"background-color: {color}22"] * len(row)

    st.dataframe(
        display_df.style.apply(_row_style, axis=1),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.caption(
    "Légende score de fraude : "
    "🔴 > 0.9 · 🟠 0.7–0.9 · 🟡 0.5–0.7 · 🟢 ≤ 0.5"
)
