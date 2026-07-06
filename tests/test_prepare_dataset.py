import logging

import pandas as pd
import pytest

from prepare_dataset import _haversine_km, compute_client_stats, exclude_invalid

LOG = logging.getLogger("test")


def test_haversine_km_same_point_is_zero():
    assert _haversine_km(48.8566, 2.3522, 48.8566, 2.3522) == pytest.approx(0.0, abs=1e-6)


def test_haversine_km_paris_marseille():
    # Distance à vol d'oiseau Paris <-> Marseille ≈ 660 km
    d = _haversine_km(48.8566, 2.3522, 43.2965, 5.3698)
    assert d == pytest.approx(660, rel=0.05)


def test_exclude_invalid_drops_nulls_and_duplicates():
    df = pd.DataFrame({
        "trans_num": ["a", "b", "b", "c"],
        "amt":       [10.0, 20.0, 20.0, None],
    })
    result = exclude_invalid(df, LOG)
    assert list(result["trans_num"]) == ["a", "b"]


def test_exclude_invalid_no_change_when_clean():
    df = pd.DataFrame({
        "trans_num": ["a", "b", "c"],
        "amt":       [10.0, 20.0, 30.0],
    })
    result = exclude_invalid(df, LOG)
    assert len(result) == 3


def test_compute_client_stats_diff_avg_amt(tmp_path):
    # Un seul client (mêmes last/first/gender/dob/zip) avec 2 transactions
    df = pd.DataFrame({
        "last":   ["Doe", "Doe"],
        "first":  ["John", "John"],
        "gender": ["M", "M"],
        "dob":    ["1990-01-01", "1990-01-01"],
        "zip":    [75001, 75001],
        "amt":    [100.0, 200.0],
        "unix_time": [1_000_000_000, 1_000_086_400],  # 1 jour d'écart
    })
    output_path = tmp_path / "client_trx_analysis.csv"

    diff = compute_client_stats(df, LOG, str(output_path))

    # avg_mnt du client = 150 -> diff = amt - 150
    assert diff.tolist() == pytest.approx([-50.0, 50.0])
    assert output_path.exists()

    stats = pd.read_csv(output_path)
    assert len(stats) == 1
    assert stats.iloc[0]["avg_mnt"] == pytest.approx(150.0)
    assert stats.iloc[0]["avg_frequency"] == pytest.approx(2.0)  # 2 trx / 1 jour


def test_compute_client_stats_distinguishes_clients(tmp_path):
    df = pd.DataFrame({
        "last":   ["Doe", "Smith"],
        "first":  ["John", "Jane"],
        "gender": ["M", "F"],
        "dob":    ["1990-01-01", "1985-05-05"],
        "zip":    [75001, 69000],
        "amt":    [100.0, 500.0],
        "unix_time": [1_000_000_000, 1_000_000_000],
    })
    output_path = tmp_path / "client_trx_analysis.csv"

    diff = compute_client_stats(df, LOG, str(output_path))

    # Chaque client est seul dans son groupe -> diff_avg_amt = 0 pour chacun
    assert diff.tolist() == pytest.approx([0.0, 0.0])

    stats = pd.read_csv(output_path)
    assert len(stats) == 2
