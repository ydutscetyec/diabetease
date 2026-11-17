"""The synthetic cohort, and the line it must not cross.

The dataset arrived with a Synthetic_T2D_Label that disagrees with the published
diagnostic thresholds in 164 of its 500 rows. 102 people who meet a diagnostic
threshold are labelled Negative, including HbA1c 7.3, 7.2 and 7.1. The other 62
are labelled Positive without meeting one: 39 sit in the prediabetes range and
23 have entirely normal fasting glucose and HbA1c, down to HbA1c 4.2. A classifier trained on it reached AUC 0.734 while calling 71% of the
people who already met a diagnostic threshold not-positive, because it had
learned to weight BMI five times more heavily than HbA1c.

The column is now relabelled from THRESHOLDS, and these tests hold three things:
the relabel still matches the thresholds it was derived from, the original label
is kept so the disagreement stays auditable rather than quietly corrected, and
no model trained on this data can reach a person.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.services.triage import THRESHOLDS

COHORT = Path(__file__).resolve().parents[1] / "app" / "data" / "synthetic_cohort.csv"
REPORT = Path(__file__).resolve().parents[1] / "app" / "data" / "model_evaluation.json"
FPG_DX = THRESHOLDS["fasting_glucose_diagnostic_mgdl"]
A1C_DX = THRESHOLDS["hba1c_diagnostic_pct"]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    with COHORT.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("Patient_ID")]


def test_the_cohort_is_present_and_whole(rows):
    assert len(rows) == 500, f"expected 500 records, found {len(rows)}"
    required = {"Patient_ID", "Municipality", "Age_Years", "BMI_kg_m2",
                "Fasting_Blood_Glucose_mg_dL", "HbA1c_Percent",
                "Synthetic_T2D_Label", "ada_label", "ada_band"}
    assert required <= set(rows[0]), f"missing columns: {required - set(rows[0])}"


def test_one_municipality_per_spelling(rows):
    """"Sto. Niño" and "Santo Niño" are the same place; it arrived as both.

    Left alone it splits that municipality's records in two, which would understate
    it in every per-municipality figure the study reports.
    """
    names = {r["Municipality"] for r in rows}
    assert "Sto. Niño" not in names, "the duplicate spelling is back; records will split"
    # ten municipalities plus Koronadal City
    assert len(names) == 11, f"expected 11 geographies, found {len(names)}: {sorted(names)}"


def test_the_relabel_still_matches_the_thresholds_it_came_from(rows):
    """If a threshold moves in triage.py, this fails rather than drifting.

    The stored label is not an independent fact. It is a function of
    THRESHOLDS, and nothing else should be able to change one without the other.
    """
    wrong = []
    for r in rows:
        fpg, a1c = float(r["Fasting_Blood_Glucose_mg_dL"]), float(r["HbA1c_Percent"])
        expected = "Positive" if (fpg >= FPG_DX or a1c >= A1C_DX) else "Negative"
        if r["ada_label"] != expected:
            wrong.append(f"{r['Patient_ID']}: FPG {fpg}, HbA1c {a1c} -> "
                         f"stored {r['ada_label']}, thresholds say {expected}")
    assert not wrong, (
        f"{len(wrong)} stored labels no longer match the thresholds. Re-run "
        f"`python -m ml.train_cohort`.\n  " + "\n  ".join(wrong[:5]))


def test_the_supplied_label_is_kept_for_audit(rows):
    """Keeping it is the point: the disagreement is a finding, not a defect to hide."""
    assert all(r.get("Synthetic_T2D_Label") for r in rows), (
        "Synthetic_T2D_Label has been dropped; the disagreement between the "
        "supplied label and the published thresholds is no longer auditable")
    disagree = sum(1 for r in rows if r["Synthetic_T2D_Label"] != r["ada_label"])
    assert disagree > 0, "expected the supplied label to disagree somewhere"
    # the number belongs in the write-up, so it is pinned here
    assert disagree == 164, f"disagreement count moved from 164 to {disagree}"


def test_no_model_trained_on_synthetic_data_is_ever_active():
    """The invariant the whole registry exists to enforce.

    A model trained on this cohort predicts the generator, not the disease. One
    reached AUC 0.997 purely by rediscovering the threshold rule it was labelled
    with. Activation has to stay impossible while the data is synthetic.

    This reads the committed report rather than the database on purpose. The
    first version of this test queried the live registry, and conftest.py points
    DATABASE_URL at an empty temp file -- so it was asserting over zero rows and
    passed happily when a version was marked active. A test that cannot fail is
    worse than no test, because it reads as cover.
    """
    doc = json.loads(REPORT.read_text(encoding="utf-8"))
    active = [v["version"] for v in doc["versions"] if v.get("activated")]
    assert not active, f"a model trained on synthetic data is activated: {active}"


def test_every_registered_version_records_why_it_is_not_activated():
    doc = json.loads(REPORT.read_text(encoding="utf-8"))
    assert doc["versions"], "the report lists no versions"
    missing = [v["version"] for v in doc["versions"]
               if not (v.get("limitations") or "").strip()]
    assert not missing, (
        "an inactive version with no stated limitation reads as an oversight "
        f"rather than a decision: {missing}")


def test_the_report_matches_the_relabelling_rule_it_claims(rows):
    """The report's headline numbers have to match the file they describe."""
    doc = json.loads(REPORT.read_text(encoding="utf-8"))
    assert doc["cohort"]["n"] == len(rows)
    disagree = sum(1 for r in rows if r["Synthetic_T2D_Label"] != r["ada_label"])
    assert doc["cohort"]["supplied_label_disagreements"] == disagree
    positives = sum(1 for r in rows if r["ada_label"] == "Positive")
    assert doc["cohort"]["label_counts"]["Positive"] == positives
    assert f"{FPG_DX:.0f}" in doc["relabelled_from"]["rule"]
    assert str(A1C_DX) in doc["relabelled_from"]["rule"]


def test_the_lab_model_is_not_presented_as_performance(rows):
    """AUC 0.997 is the circularity, and the report must say so where it is shown.

    A reader who saw that number without the explanation beside it would
    reasonably conclude the tool had a working classifier.
    """
    doc = json.loads(REPORT.read_text(encoding="utf-8"))
    withlabs = next(v for v in doc["versions"] if "withlabs" in v["version"])
    best = max((r for r in withlabs["results"]
                if not r["model"].startswith("baseline")),
               key=lambda r: r["roc_auc"])
    assert best["roc_auc"] > 0.95, (
        "the with-labs model no longer scores near-perfectly; if the label or the "
        "features changed, the circularity argument needs rechecking")
    lim = (withlabs.get("limitations") or "").lower()
    for phrase in ("not a performance figure", "rule it was handed"):
        assert phrase in lim, f"the limitation text no longer explains why: missing {phrase!r}"


def test_the_trainer_never_writes_a_loadable_artifact():
    """inference.py loads an artifact if one exists with active metadata.

    The trainer therefore must not leave one on disk; the registry row is the
    whole output.
    """
    src = (Path(__file__).resolve().parents[1] / "ml" / "train_cohort.py").read_text()
    assert "artifact_path = None" in src.replace("version.", ""), (
        "the trainer should set artifact_path to None; an artifact on disk is "
        "one metadata flag away from being served")
    for bad in ("joblib.dump", "pickle.dump", "is_active = True", "is_active=True"):
        assert bad not in src, f"the trainer contains `{bad}`"


def test_the_assessment_never_returns_a_score_or_probability():
    """The rule this project set itself, checked against the response schema."""
    from app import schemas

    fields = set(schemas.AssessmentResponse.model_fields)
    banned = {"probability", "risk_score", "score", "risk", "confidence",
              "likelihood", "percent_risk", "prediction"}
    assert not (fields & banned), (
        f"the assessment response exposes {sorted(fields & banned)}; this tool "
        f"reports a threshold check, never a score")

def test_metrics_endpoint_reports_the_feasibility_study(client, admin_token):
    """A reviewer signing in must see that a model was tried, and what happened.

    Before this the endpoint dropped every inactive version, so the research view
    said "No metric is reported because none has been measured" -- which stopped
    being true once the pipeline had run.
    """
    body = client.get("/api/v1/admin/metrics",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert body["model"]["status"] == "no active model"
    ev = body.get("evaluated_not_activated")
    assert ev, "the endpoint reports no evaluated versions; the study is invisible"
    versions = {e["version"] for e in ev}
    assert {"synthetic-withlabs-v1", "synthetic-nolabs-v1"} <= versions
    for e in ev:
        assert e["activated"] is False
        assert e["dataset_is_synthetic"] is True
        assert e["metrics"], f"{e['version']} carries no measurements"
        # the always-negative baseline has to travel with the models: an AUC
        # without it invites the reader to assume the model beat chance
        assert any(k.startswith("baseline") for k in e["metrics"]), (
            f"{e['version']} reports model metrics with no baseline beside them")
