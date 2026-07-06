import io
import json

import pandas as pd
import requests

from config import JEDHA_API_URL


def fetch_trx(**context):
    """Récupère la dernière transaction depuis l'API Jedha et la pousse en XCom."""
    resp = requests.get(JEDHA_API_URL, timeout=15)
    resp.raise_for_status()
    # L'API renvoie un JSON encodé en chaîne (resp.json() donne déjà le texte JSON,
    # pas besoin de le ré-encoder avec json.dumps avant de le passer à pandas).
    # convert_dates=False : sans ça, pandas convertit "current_time" en Timestamp
    # (nom de colonne reconnu comme une date), non sérialisable en JSON pour le XCom.
    df = pd.read_json(io.StringIO(resp.json()), orient="split", convert_dates=False)

    if df.empty:
        raise ValueError("L'API Jedha a retourné un résultat vide.")

    trx = df.iloc[0].to_dict()
    # Normalisation des types pour la sérialisation JSON XCom
    trx = {
        k: (int(v) if isinstance(v, float) and v == int(v) and k in
            ("cc_num", "zip", "city_pop", "unix_time", "current_time") else
            float(v) if isinstance(v, float) else v)
        for k, v in trx.items()
    }
    print(f"[fetch_trx] trans_num={trx.get('trans_num', '?')}  amt={trx.get('amt', '?')}")
    return json.dumps(trx)
