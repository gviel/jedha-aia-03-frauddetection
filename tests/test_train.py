import logging

import numpy as np
import pandas as pd
import pytest

from train import apply_resampling, compute_metrics, instantiate_model

LOG = logging.getLogger("test")


def _make_imbalanced(n_majority=90, n_minority=10, n_features=4, seed=0):
    rng = np.random.RandomState(seed)
    X_maj = pd.DataFrame(rng.normal(0, 1, size=(n_majority, n_features)), columns=list("abcd"))
    X_min = pd.DataFrame(rng.normal(5, 1, size=(n_minority, n_features)), columns=list("abcd"))
    X = pd.concat([X_maj, X_min], ignore_index=True)
    y = pd.Series([0] * n_majority + [1] * n_minority)
    return X, y


def test_apply_resampling_none_is_noop():
    X, y = _make_imbalanced()
    X_res, y_res = apply_resampling(X, y, {"method": "none"}, LOG)
    assert X_res is X
    assert y_res is y


def test_apply_resampling_under_sample_balances_classes():
    X, y = _make_imbalanced(n_majority=90, n_minority=10)
    X_res, y_res = apply_resampling(
        X, y, {"method": "under_sample", "sampling_strategy": 1.0, "random_state": 42}, LOG,
    )
    counts = y_res.value_counts()
    assert counts[0] == counts[1] == 10
    assert len(X_res) == len(y_res) == 20


def test_apply_resampling_smote_generates_synthetic_minority():
    X, y = _make_imbalanced(n_majority=90, n_minority=10)
    X_res, y_res = apply_resampling(
        X, y, {"method": "smote", "sampling_strategy": 1.0, "k_neighbors": 3, "random_state": 42}, LOG,
    )
    counts = pd.Series(y_res).value_counts()
    assert counts[0] == counts[1] == 90
    assert len(X_res) == 180


def test_apply_resampling_unknown_method_raises():
    X, y = _make_imbalanced()
    with pytest.raises(ValueError):
        apply_resampling(X, y, {"method": "bogus"}, LOG)


def test_instantiate_model_resolves_scale_pos_weight_auto():
    cfg = {
        "class": "xgboost.XGBClassifier",
        "params": {"scale_pos_weight": "auto", "n_estimators": 5},
    }
    model = instantiate_model(cfg, scale_pos_weight=7.5)
    assert model.get_params()["scale_pos_weight"] == 7.5


def test_instantiate_model_passes_through_normal_params():
    cfg = {
        "class": "sklearn.linear_model.LogisticRegression",
        "params": {"max_iter": 123, "C": 0.5},
    }
    model = instantiate_model(cfg)
    assert model.max_iter == 123
    assert model.C == 0.5


def test_compute_metrics_perfect_predictions():
    y_true = [0, 0, 1, 1]
    y_prob = [0.0, 0.1, 0.9, 1.0]
    metrics = compute_metrics(y_true, y_prob)
    assert metrics["f1"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["roc_auc"] == pytest.approx(1.0)
    assert metrics["pr_auc"] == pytest.approx(1.0)


def test_compute_metrics_worst_case():
    y_true = [0, 0, 1, 1]
    y_prob = [0.9, 0.9, 0.1, 0.1]
    metrics = compute_metrics(y_true, y_prob)
    assert metrics["recall"] == pytest.approx(0.0)
    assert metrics["accuracy"] == pytest.approx(0.0)
