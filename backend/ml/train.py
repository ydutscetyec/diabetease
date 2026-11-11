"""Train and compare candidate models against a logistic-regression baseline.

Safety interlock: a model is written with is_active=false unless the dataset
manifest declares synthetic=false AND --i-have-verified-provenance is passed.
The inference layer refuses to load an inactive artifact, so a model trained on
demonstration data can never serve a prediction to a user by accident.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
FEATURES = ["age", "family_history_t1d", "n_symptoms", "glucose_mgdl", "hba1c_pct", "autoantibody_count"]


def build(estimator) -> Pipeline:
    # Imputer and scaler live inside the pipeline, so they are fitted on training
    # folds only. Fitting them on the full frame first is the classic leak.
    pre = ColumnTransformer([("num", Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ]), FEATURES)])
    return Pipeline([("pre", pre), ("clf", estimator)])


def score(pipe: Pipeline, X, y) -> dict:
    pred = pipe.predict(X)
    out = {
        "accuracy": accuracy_score(y, pred),
        "precision": precision_score(y, pred, zero_division=0),
        "recall_sensitivity": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
    }
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    out["specificity"] = tn / (tn + fp) if (tn + fp) else 0.0
    out["confusion_matrix"] = {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}
    if hasattr(pipe, "predict_proba"):
        out["roc_auc"] = roc_auc_score(y, pipe.predict_proba(X)[:, 1])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "synthetic_demo.csv"))
    ap.add_argument("--out-dir", default=str(HERE / "artifacts"))
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--i-have-verified-provenance", action="store_true",
                    help="Required, with a non-synthetic manifest, to activate the model.")
    args = ap.parse_args()

    data = Path(args.data)
    manifest_file = data.with_suffix(".manifest.json")
    if not manifest_file.exists():
        raise SystemExit(
            f"refusing to train: no manifest at {manifest_file}. Every dataset needs a "
            "manifest recording its source, target definition and whether it is synthetic."
        )
    manifest = json.loads(manifest_file.read_text())
    is_synthetic = bool(manifest.get("synthetic", True))

    df = pd.read_csv(data)
    missing = [c for c in FEATURES + ["label"] if c not in df.columns]
    if missing:
        raise SystemExit(f"dataset is missing required columns: {missing}")

    before = len(df)
    df = df.drop_duplicates()
    X, y = df[FEATURES], df["label"].astype(int)
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=args.test_size, random_state=args.seed, stratify=y
    )

    candidates = {
        "logistic_regression_baseline": LogisticRegression(max_iter=2000, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=300, min_samples_leaf=3, class_weight="balanced", random_state=args.seed
        ),
    }
    results, fitted = {}, {}
    for name, est in candidates.items():
        pipe = build(est)
        pipe.fit(Xtr, ytr)
        results[name] = score(pipe, Xte, yte)
        fitted[name] = pipe

    # Selection rule declared before looking at the numbers: for a screening-style
    # task, missing a case is worse than a false alarm, so rank on recall and break
    # ties on F1. Not "whichever has the best accuracy".
    best = max(results, key=lambda k: (results[k]["recall_sensitivity"], results[k]["f1"]))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / "model.joblib"
    joblib.dump(fitted[best], artifact)

    activate = (not is_synthetic) and args.i_have_verified_provenance
    meta = {
        "version": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{best}",
        "algorithm": best,
        "is_active": activate,
        "prediction_task": (
            "binary classification of the dataset's own target column; this is NOT "
            "forecasting of future type 1 diabetes onset"
        ),
        "dataset_label": manifest.get("dataset_label", "unlabelled"),
        "dataset_is_synthetic": is_synthetic,
        "duplicates_dropped": before - len(df),
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "class_balance_test": {str(k): int(v) for k, v in yte.value_counts().items()},
        "features": FEATURES,
        "selection_rule": "highest recall, F1 as tie-break, declared before evaluation",
        "calibration_assessed": False,
        "metrics": results,
        "limitations": (
            "Trained on synthetic demonstration data. Metrics describe the generator, "
            "not type 1 diabetes."
        ) if is_synthetic else manifest.get("limitations", "Record limitations in the manifest."),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, default=str))
    (out_dir / "evaluation.json").write_text(json.dumps(results, indent=2, default=str))

    print(f"selected: {best}")
    for name, r in results.items():
        print(f"  {name}: recall={r['recall_sensitivity']:.3f} f1={r['f1']:.3f} "
              f"acc={r['accuracy']:.3f} auc={r.get('roc_auc', float('nan')):.3f}")
    if activate:
        print("model marked ACTIVE; the API will load it")
    else:
        reason = "dataset is synthetic" if is_synthetic else "--i-have-verified-provenance not passed"
        print(f"model marked INACTIVE ({reason}); the API will keep reporting 'no model available'")


if __name__ == "__main__":
    main()
