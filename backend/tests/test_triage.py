"""Unit tests for the clinical rule engine. No HTTP, no database."""
from __future__ import annotations
import pytest
from app.services.triage import TriageInput, evaluate


def test_dka_pattern_returns_emergency_and_short_circuits():
    r = evaluate(TriageInput(age=12, symptoms=["thirst", "urination"],
                             urgent_signs=["vomiting", "rapid_breathing"]))
    assert r.tier == "emergency" and r.emergency is True


def test_emergency_wins_even_with_normal_labs():
    r = evaluate(TriageInput(age=9, symptoms=["thirst"],
                             urgent_signs=["vomiting", "drowsiness"],
                             glucose_test_type="fasting", glucose_mgdl=88))
    assert r.tier == "emergency"


def test_one_urgent_sign_alone_is_not_an_emergency():
    r = evaluate(TriageInput(age=30, symptoms=["fatigue"], urgent_signs=["abdominal_pain"]))
    assert r.tier != "emergency"


@pytest.mark.parametrize("ttype,value", [("fasting", 126.0), ("fasting", 300.0), ("random", 200.0)])
def test_glucose_at_or_above_cutoff_is_urgent(ttype, value):
    r = evaluate(TriageInput(age=14, glucose_test_type=ttype, glucose_mgdl=value))
    assert r.tier == "urgent"


def test_fasting_125_is_intermediate_not_urgent():
    r = evaluate(TriageInput(age=14, glucose_test_type="fasting", glucose_mgdl=125))
    assert r.tier == "followup"


def test_random_140_does_not_trip_the_fasting_cutoff():
    # 140 mg/dL fasting would be diagnostic; random it is not. The rule must not
    # apply the fasting threshold to a random sample.
    r = evaluate(TriageInput(age=20, glucose_test_type="random", glucose_mgdl=140))
    assert r.tier == "no_threshold"


def test_hba1c_boundaries():
    assert evaluate(TriageInput(age=20, hba1c_pct=6.5)).tier == "urgent"
    assert evaluate(TriageInput(age=20, hba1c_pct=6.4)).tier == "followup"
    assert evaluate(TriageInput(age=20, hba1c_pct=5.6)).tier == "no_threshold"


def test_two_autoantibodies_is_urgent_one_is_followup():
    assert evaluate(TriageInput(age=8, autoantibodies="two_or_more_positive")).tier == "urgent"
    assert evaluate(TriageInput(age=8, autoantibodies="one_positive")).tier == "followup"


def test_no_labs_at_all_returns_insufficient_not_reassurance():
    r = evaluate(TriageInput(age=25))
    assert r.tier == "insufficient"
    assert "cannot assess" in r.explanation


def test_no_threshold_result_explicitly_refuses_to_be_an_all_clear():
    r = evaluate(TriageInput(age=25, glucose_test_type="fasting", glucose_mgdl=85,
                             hba1c_pct=5.1, autoantibodies="negative"))
    assert r.tier == "no_threshold"
    assert "not a clean bill of health" in r.explanation


def test_family_history_plus_one_symptom_escalates_to_followup():
    assert evaluate(TriageInput(age=10, family_history_t1d="yes",
                                symptoms=["thirst"])).tier == "followup"
    assert evaluate(TriageInput(age=10, family_history_t1d="no",
                                symptoms=["thirst"])).tier == "insufficient"


def test_result_never_contains_a_probability_field():
    for inp in [TriageInput(age=12, hba1c_pct=9.0), TriageInput(age=12)]:
        d = evaluate(inp).__dict__
        assert not any(k in d for k in ("probability", "risk_score", "percentage"))


# --------------------------------------------------- below-normal glucose
def test_glucose_below_54_is_urgent():
    r = evaluate(TriageInput(age=15, glucose_test_type="random", glucose_mgdl=48))
    assert r.tier == "urgent"
    assert any("54 mg/dL" in x["text"] for x in r.reasons)


def test_glucose_between_54_and_70_is_followup():
    r = evaluate(TriageInput(age=15, glucose_test_type="fasting", glucose_mgdl=62))
    assert r.tier == "followup"
    assert any("under 70 mg/dL" in x["text"] for x in r.reasons)


def test_glucose_at_70_is_normal():
    r = evaluate(TriageInput(age=15, glucose_test_type="fasting", glucose_mgdl=70))
    assert r.tier == "no_threshold"


def test_low_glucose_result_does_not_carry_the_type1_type2_caveat():
    """That caveat is about high glucose. Attaching it to a low reading is wrong."""
    r = evaluate(TriageInput(age=15, glucose_test_type="random", glucose_mgdl=45))
    assert not any("type 1 or type 2" in x["text"] for x in r.reasons)


def test_emergency_still_outranks_low_glucose():
    r = evaluate(TriageInput(age=12, glucose_test_type="random", glucose_mgdl=45,
                             symptoms=["fatigue"], urgent_signs=["vomiting", "drowsiness"]))
    assert r.tier == "emergency"
