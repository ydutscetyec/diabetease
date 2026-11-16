"""Unit tests for the clinical rule engine. No HTTP, no database."""
from __future__ import annotations
import re

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


def test_two_hour_ogtt_uses_its_own_cutoffs():
    # The 75 g OGTT is diagnostic at 200 and intermediate from 140, so a value
    # that is merely intermediate on an OGTT would be normal taken at random.
    assert evaluate(TriageInput(age=25, glucose_test_type="two_hour",
                                glucose_mgdl=205)).tier == "urgent"
    assert evaluate(TriageInput(age=25, glucose_test_type="two_hour",
                                glucose_mgdl=150)).tier == "followup"
    assert evaluate(TriageInput(age=25, glucose_test_type="random",
                                glucose_mgdl=150)).tier == "no_threshold"


def test_the_input_has_exactly_these_fields():
    """An allowlist, not a blocklist. Any field added or removed fails here, so
    an input that is not part of this study cannot be introduced quietly and a
    required one cannot vanish. Stronger than naming particular fields, because
    it catches the ones nobody thought of.
    """
    import dataclasses
    assert {f.name for f in dataclasses.fields(TriageInput)} == {
        "age", "family_history_t2d", "asian_ancestry", "bmi", "risk_factors",
        "symptoms", "urgent_signs", "glucose_test_type", "glucose_mgdl",
        "hba1c_pct",
    }


def test_unknown_inputs_are_refused(tmp_path):
    """Whatever is not in the allowlist above is rejected rather than ignored.
    A silently dropped keyword would mean a form field that appears to work.
    """
    with pytest.raises(TypeError):
        TriageInput(age=30, something_we_do_not_collect="yes")


def test_no_labs_at_all_returns_insufficient_not_reassurance():
    r = evaluate(TriageInput(age=25))
    assert r.tier == "insufficient"
    assert "cannot assess" in r.explanation


def test_no_threshold_result_explicitly_refuses_to_be_an_all_clear():
    r = evaluate(TriageInput(age=25, glucose_test_type="fasting", glucose_mgdl=85,
                             hba1c_pct=5.1))
    assert r.tier == "no_threshold"
    assert "not a clean bill of health" in r.explanation
    # Type 2 is slow and usually silent, so the refusal has to point at repeat
    # testing rather than at a single reassuring number.
    assert any("every 3 years" in x["text"] for x in r.reasons)


def test_family_history_plus_one_symptom_escalates_to_followup():
    assert evaluate(TriageInput(age=10, family_history_t2d="yes",
                                symptoms=["thirst"])).tier == "followup"
    assert evaluate(TriageInput(age=10, family_history_t2d="no",
                                symptoms=["thirst"])).tier == "insufficient"


def test_everyone_from_35_is_screened_regardless_of_risk_factors():
    # ADA 2.12b: universal screening from 35.
    r = evaluate(TriageInput(age=35))
    assert r.screening_indicated is True
    assert evaluate(TriageInput(age=34)).screening_indicated is False
    # and with no labs, "should be screened" has to become the recommendation
    assert r.tier == "followup"


def test_asian_ancestry_lowers_the_bmi_cutoff_to_23():
    # ADA Table 2.5: BMI >= 25, or >= 23 for individuals of Asian ancestry.
    base = dict(age=28, risk_factors=["physical_inactivity"])
    assert evaluate(TriageInput(**base, asian_ancestry="yes", bmi=23.5)).screening_indicated is True
    assert evaluate(TriageInput(**base, asian_ancestry="no", bmi=23.5)).screening_indicated is False
    assert evaluate(TriageInput(**base, asian_ancestry="no", bmi=25.5)).screening_indicated is True


def test_unknown_ancestry_takes_the_lower_cutoff():
    # The cohort is Filipino; erring toward "get tested" is the safer error.
    r = evaluate(TriageInput(age=28, bmi=23.5, risk_factors=["physical_inactivity"]))
    assert r.screening_indicated is True


def test_high_bmi_alone_is_not_enough_below_35():
    # 2.12a wants overweight AND at least one risk factor.
    r = evaluate(TriageInput(age=28, asian_ancestry="no", bmi=31.0))
    assert r.screening_indicated is False
    assert "at least one risk factor" in r.screening_reason


def test_asian_ancestry_is_itself_a_risk_factor():
    """The finding that matters most for this study's population.

    Table 2.5 lists high-risk ancestry — Asian American among its examples — as
    a risk factor in its own right, and separately lowers the BMI cut-off to 23
    for people of Asian ancestry. Both clauses land on the same cohort here, so
    for a Filipino adult the BMI cut-off is 23 AND the "one or more risk
    factors" condition is already satisfied by ancestry alone. In practice that
    means screening is indicated for any adult in this study at BMI 23 or
    above, at any age.
    """
    r = evaluate(TriageInput(age=19, asian_ancestry="yes", bmi=23.0))
    assert r.screening_indicated is True
    assert "Asian ancestry" in r.screening_reason
    # one point below the cut-off it is not, so the rule is doing real work
    assert evaluate(TriageInput(age=19, asian_ancestry="yes",
                                bmi=22.9)).screening_indicated is False


def test_missing_bmi_is_reported_as_unanswerable_not_as_no():
    r = evaluate(TriageInput(age=28, risk_factors=["physical_inactivity"]))
    assert r.screening_indicated is False
    assert "not entered" in r.screening_reason


def test_screening_never_overrides_an_emergency():
    r = evaluate(TriageInput(age=40, symptoms=["thirst"],
                             urgent_signs=["vomiting", "drowsiness"]))
    assert r.tier == "emergency" and r.emergency is True


def test_every_result_rests_on_the_registered_threshold_source():
    """No result may cite anything but the sources this study registered. That
    is the positive form of "nothing from outside the study appears here": the
    threshold source is fixed, and the glossary check below covers the prose.
    """
    from app.services.triage import THRESHOLD_SOURCE
    inputs = [
        TriageInput(age=40),
        TriageInput(age=25, glucose_test_type="fasting", glucose_mgdl=85, hba1c_pct=5.1),
        TriageInput(age=25, glucose_test_type="fasting", glucose_mgdl=130),
        TriageInput(age=25, hba1c_pct=6.0),
    ]
    for inp in inputs:
        r = evaluate(inp)
        assert r.threshold_source == THRESHOLD_SOURCE
        assert "American Diabetes Association" in r.threshold_source


def test_results_describe_only_this_study_subject():
    """Every mention of a diabetes form in a result must be the one this study
    covers. Built as an allowlist: any other form named here fails.
    """
    allowed = {"type 2"}
    inputs = [
        TriageInput(age=40),
        TriageInput(age=25, glucose_test_type="fasting", glucose_mgdl=85, hba1c_pct=5.1),
        TriageInput(age=25, glucose_test_type="fasting", glucose_mgdl=130),
        TriageInput(age=25, hba1c_pct=6.0),
        TriageInput(age=25, glucose_test_type="random", glucose_mgdl=45),
    ]
    for inp in inputs:
        r = evaluate(inp)
        blob = " ".join([r.headline, r.explanation, r.screening_reason]
                        + [x["text"] for x in r.reasons]).lower()
        for found in re.findall(r"type\s*\d+", blob):
            assert found.replace("  ", " ") in allowed, f"{found!r} named for {inp}"


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


def test_low_glucose_result_does_not_carry_the_which_type_caveat():
    """That caveat is about high glucose. Attaching it to a low reading is wrong."""
    r = evaluate(TriageInput(age=15, glucose_test_type="random", glucose_mgdl=45))
    assert not any("which type of diabetes" in x["text"] for x in r.reasons)


def test_emergency_still_outranks_low_glucose():
    r = evaluate(TriageInput(age=12, glucose_test_type="random", glucose_mgdl=45,
                             symptoms=["fatigue"], urgent_signs=["vomiting", "drowsiness"]))
    assert r.tier == "emergency"
