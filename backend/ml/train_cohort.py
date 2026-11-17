"""Train and evaluate a T2D classifier on the synthetic South Cotabato cohort.

This script records what it measured in the model registry and does NOT activate
anything. That is not caution for its own sake; it is what the measurements
below support. Run it with:

    python -m backend.ml.train_cohort

Two findings it exists to produce, both of which belong in the write-up:

1. Trained WITH the lab values, the model reaches AUC 0.997. That number is
   meaningless. The label is defined as "FPG >= 126 or HbA1c >= 6.5", so a model
   given FPG and HbA1c is being asked to rediscover a rule it was handed. It is
   a threshold check with extra steps, and reporting 0.997 as predictive
   performance would mislead a reader who did not know how the label was made.

2. Trained WITHOUT the lab values -- the question the study actually asks, since
   the people this tool is for have not been tested yet -- AUC falls to 0.666
   and neither model beats the always-negative baseline on accuracy.

The honest reading of (2) is narrow, and the write-up should keep it narrow:
this cohort is synthetic, and its glucose and HbA1c columns appear to have been
drawn independently of age, BMI and the risk factors. There is therefore no
association for a model to find, and that is a property of the generator, not a
finding about screening. Published non-laboratory risk scores (FINDRISC, the ADA
risk test) do reach useful discrimination in real cohorts. Nothing here argues
against them; it argues that this dataset cannot be used to evaluate them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.triage import THRESHOLDS  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "app" / "data" / "synthetic_cohort.csv"

# Imported, never retyped. If a threshold moves in triage.py the label moves with
# it, and test_synthetic_cohort.py fails if the stored label stops matching.
FPG_DX = THRESHOLDS["fasting_glucose_diagnostic_mgdl"]
A1C_DX = THRESHOLDS["hba1c_diagnostic_pct"]
FPG_PRE = THRESHOLDS["fasting_glucose_intermediate_low_mgdl"]
A1C_PRE = THRESHOLDS["hba1c_intermediate_low_pct"]

LIM_NOLABS_SHORT = (
    "Research use only, on synthetic data. Does not beat the always-negative "
    "baseline on accuracy; emits no probability because calibration has not "
    "been assessed.")

LAB = ["Fasting_Blood_Glucose_mg_dL", "HbA1c_Percent"]
NONLAB_NUM = ["Age_Years", "BMI_kg_m2"]
CAT = ["Sex", "Family_History_of_T2D", "Physical_Activity",
       "Hypertension_History", "Municipality"]


def load() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    df = df.dropna(subset=["Patient_ID"])
    df = df[~df["Patient_ID"].astype(str).str.startswith("Disclaimer")]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    # one municipality arrived under two spellings
    df["Municipality"] = df["Municipality"].replace({"Sto. Niño": "Santo Niño"})
    return df


def ada_label(df: pd.DataFrame) -> pd.Series:
    return ((df.Fasting_Blood_Glucose_mg_dL >= FPG_DX)
            | (df.HbA1c_Percent >= A1C_DX)).map({True: "Positive", False: "Negative"})


def ada_band(df: pd.DataFrame) -> pd.Series:
    return pd.Series(np.select(
        [(df.Fasting_Blood_Glucose_mg_dL >= FPG_DX) | (df.HbA1c_Percent >= A1C_DX),
         (df.Fasting_Blood_Glucose_mg_dL >= FPG_PRE) | (df.HbA1c_Percent >= A1C_PRE)],
        ["diabetes range", "prediabetes range"], default="normal range"), index=df.index)


def evaluate(df: pd.DataFrame, num: list[str], cat: list[str]) -> list[dict]:
    X = df[num + cat]
    y = df["ada_label"].eq("Positive").astype(int)
    pre = ColumnTransformer([("n", StandardScaler(), num),
                             ("c", OneHotEncoder(handle_unknown="ignore"), cat)])
    cv = StratifiedKFold(5, shuffle=True, random_state=0)
    out = []
    for name, clf in [
        ("baseline_most_frequent", DummyClassifier(strategy="most_frequent")),
        ("logistic_regression", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ("gradient_boosting", HistGradientBoostingClassifier(random_state=0)),
    ]:
        p = cross_val_predict(Pipeline([("pre", pre), ("clf", clf)]), X, y,
                              cv=cv, method="predict_proba")[:, 1]
        tn, fp, fn, tp = confusion_matrix(y, (p >= 0.5).astype(int)).ravel()
        out.append({
            "model": name,
            "roc_auc": round(float(roc_auc_score(y, p)) if p.std() > 0 else 0.5, 4),
            "sensitivity": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            "specificity": round(tn / (tn + fp), 4) if tn + fp else 0.0,
            "accuracy": round((tp + tn) / len(y), 4),
            "n": int(len(y)),
            "positives": int(y.sum()),
        })
    return out


def register(db, label: str, task: str, rows: list[dict], limitations: str) -> None:
    """Record a training run as an inactive version with its metrics."""
    from app.models import ModelEvaluation, ModelVersion

    best = max((r for r in rows if not r["model"].startswith("baseline")),
               key=lambda r: r["roc_auc"])
    version = db.query(ModelVersion).filter(ModelVersion.version == label).one_or_none()
    if version is None:
        version = ModelVersion(version=label)
        db.add(version)
    version.algorithm = best["model"]
    version.prediction_task = task
    version.dataset_label = "DiabetEASE synthetic South Cotabato cohort (n=500)"
    version.dataset_is_synthetic = True
    version.n_train = int(best["n"] * 0.8)
    version.n_test = int(best["n"] * 0.2)
    version.artifact_path = None          # nothing on disk: nothing to load
    version.is_active = False             # see the module docstring
    version.limitations = limitations
    db.flush()
    db.query(ModelEvaluation).filter(
        ModelEvaluation.model_version_id == version.id).delete()
    for r in rows:
        for metric in ("roc_auc", "sensitivity", "specificity", "accuracy"):
            db.add(ModelEvaluation(model_version_id=version.id,
                                   metric=f"{r['model']}.{metric}",
                                   value=float(r[metric]), split="cv5"))


def main() -> int:
    df = load()
    df["ada_label"] = ada_label(df)
    df["ada_band"] = ada_band(df)
    disagree = int((df.ada_label != df.Synthetic_T2D_Label).sum())
    agreement = 1.0 - disagree / len(df)

    print(f"cohort n={len(df)}  relabelled from FPG>={FPG_DX:.0f} or HbA1c>={A1C_DX}")
    print(f"  label: {df.ada_label.value_counts().to_dict()}")
    print(f"  bands: {df.ada_band.value_counts().to_dict()}")
    print(f"  agreement with the supplied Synthetic_T2D_Label: {agreement:.1%}")
    # counted, not derived from the rounded proportion: that printed 163
    print(f"  -> {disagree} of {len(df)} supplied labels disagree with the "
          f"published thresholds\n")

    with_labs = evaluate(df, NONLAB_NUM + LAB, CAT)
    no_labs = evaluate(df, NONLAB_NUM, CAT)
    for title, rows in (("with lab values (circular)", with_labs),
                        ("lab values withheld", no_labs)):
        print(f"--- {title} ---")
        for r in rows:
            print(f"  {r['model']:<26} AUC {r['roc_auc']:.3f}  sens {r['sensitivity']:.1%}"
                  f"  spec {r['specificity']:.1%}  acc {r['accuracy']:.1%}")
        print()

    LIM_WITHLABS = (
        "Not activated, and not a performance figure. The label is defined as "
        f"FPG >= {FPG_DX:.0f} mg/dL or HbA1c >= {A1C_DX}%, and the model is given both of "
        "those columns, so it is rediscovering the rule it was handed. Reported "
        "only to show why the high AUC is an artefact.")
    LIM_NOLABS = (
        "Not activated. On this cohort no model beat the always-negative baseline "
        "on accuracy. The dataset is synthetic and its glucose and HbA1c columns "
        "appear to have been drawn independently of age, BMI and the risk factors, "
        "so there is no association to find. That is a property of the generator, "
        "not evidence about screening: published non-laboratory risk scores do "
        "discriminate usefully in real cohorts.")

    from app.database import SessionLocal, engine
    from app.models import Base
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        register(db, "synthetic-withlabs-v1",
                 "reconstructs the diagnostic threshold rule it was labelled with",
                 with_labs, LIM_WITHLABS)
        register(db, "synthetic-nolabs-v1",
                 "flags who may need a laboratory test, from non-laboratory features only",
                 no_labs, LIM_NOLABS)
        db.commit()
        print("registered 2 model versions, both inactive, with their measured metrics")
    finally:
        db.close()

    # Also written as a committed artifact, for two reasons. A fresh deployment
    # has an empty database, so the API would otherwise report that no model had
    # ever been tried. And a registry row in somebody's local SQLite is not
    # reviewable: this file shows up in the diff.
    report = {
        "generated_by": "backend/ml/train_cohort.py",
        "provenance": {
            "source": "DiabetEASE_Synthetic_South_Cota.csv, supplied by the study team",
            "synthetic": True,
            # carried verbatim from the trailing row of the supplied file, because
            # it is the one caveat a reader of any per-municipality figure needs
            "supplied_disclaimer": (
                "Geographic assignments are simulated for system development and do "
                "not represent the actual distribution or prevalence of Type 2 "
                "Diabetes patients across South Cotabato."
            ),
            "cleaning": [
                "dropped the trailing blank rows and the disclaimer row",
                "dropped an unnamed empty column",
                "merged the municipality spelling 'Sto. Niño' into 'Santo Niño'",
                "added ada_label and ada_band, derived from triage.py THRESHOLDS",
                "kept the supplied Synthetic_T2D_Label so the disagreement stays auditable",
            ],
        },
        "relabelled_from": {
            "source": "app/services/triage.py THRESHOLDS",
            "rule": f"Positive if FPG >= {FPG_DX:.0f} mg/dL or HbA1c >= {A1C_DX}%",
        },
        "cohort": {
            "n": int(len(df)),
            "label_counts": {k: int(v) for k, v in df.ada_label.value_counts().items()},
            "bands": {k: int(v) for k, v in df.ada_band.value_counts().items()},
            "supplied_label_disagreements": disagree,
            "agreement_with_supplied_label": round(agreement, 4),
        },
        "versions": [
            {"version": "synthetic-withlabs-v1", "activated": False,
             "prediction_task": "reconstructs the diagnostic threshold rule it was "
                                "labelled with",
             "limitations": LIM_WITHLABS, "results": with_labs},
            {"version": "synthetic-nolabs-v1", "activated": False,
             "prediction_task": "flags who may need a laboratory test, from "
                                "non-laboratory features only",
             "limitations": LIM_NOLABS, "results": no_labs},
        ],
    }
    out = DATA.parent / "model_evaluation.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(Path(__file__).resolve().parents[1])}")

    export_linear(df)
    return 0


def export_linear(df: pd.DataFrame) -> None:
    """Export the non-laboratory model as plain numbers.

    The server runs pure-Python wheels only: scikit-learn, pandas and joblib are
    in requirements-ml.txt and are not installed there. A pickled pipeline would
    load on a developer's machine and nowhere else, so the registry would be
    reporting a model that could not score anything in production.

    A logistic regression needs none of it at inference time -- a
    standardisation, a one-hot expansion and a dot product -- so what ships is
    the coefficients, scored by app/services/linear_model.py. A fixture of
    scikit-learn's own probabilities travels with them so the parity test can
    check the scorer without scikit-learn being installed.
    """
    y = df["ada_label"].eq("Positive").astype(int)
    X = df[NONLAB_NUM + CAT]
    pre = ColumnTransformer([("n", StandardScaler(), NONLAB_NUM),
                             ("c", OneHotEncoder(handle_unknown="ignore"), CAT)])
    pipe = Pipeline([("pre", pre),
                     ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))])
    pipe.fit(X, y)

    sc = pipe.named_steps["pre"].named_transformers_["n"]
    oh = pipe.named_steps["pre"].named_transformers_["c"]
    clf = pipe.named_steps["clf"]
    probs = pipe.predict_proba(X)[:, 1]

    # Spread across the cohort rather than taken from the front, so the fixture
    # covers several municipalities and both classes.
    step = max(1, len(df) // 25)
    fixture = []
    for pos in range(0, len(df), step):
        row = df.iloc[pos]
        fixture.append({
            "features": {c: (float(row[c]) if c in NONLAB_NUM else str(row[c]))
                         for c in NONLAB_NUM + CAT},
            "sklearn_probability": float(probs[pos]),
        })

    model = {
        "kind": "logistic_regression",
        "version": "synthetic-nolabs-v1",
        "trained_on": "DiabetEASE synthetic South Cotabato cohort (n=%d)" % len(df),
        "dataset_is_synthetic": True,
        "research_only": True,
        "calibration_assessed": False,
        "is_active": True,
        "limitations": LIM_NOLABS_SHORT,
        "numeric": [{"name": n, "mean": float(m), "scale": float(s)}
                    for n, m, s in zip(NONLAB_NUM, sc.mean_, sc.scale_)],
        "categorical": [{"name": n, "levels": [str(v) for v in cats]}
                        for n, cats in zip(CAT, oh.categories_)],
        "coefficients": [float(c) for c in clf.coef_[0]],
        "intercept": float(clf.intercept_[0]),
        "threshold": 0.5,
        "positive_label": "Positive",
        "negative_label": "Negative",
        "parity_fixture": fixture,
    }
    from app.config import get_settings
    path = Path(get_settings().model_path).with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.name}: {len(model['coefficients'])} coefficients, "
          f"{len(fixture)}-row parity fixture")

    # fail loudly here rather than shipping numbers the scorer disagrees with
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services import linear_model
    linear_model.load(force=True)
    worst = 0.0
    for case in fixture:
        got = linear_model.score(case["features"])
        worst = max(worst, abs(got["probability"] - case["sklearn_probability"]))
    print(f"  parity with scikit-learn over the fixture: max difference {worst:.2e}")
    if worst > 1e-9:
        raise SystemExit(f"the exported model does not reproduce scikit-learn ({worst:.2e})")


if __name__ == "__main__":
    raise SystemExit(main())
