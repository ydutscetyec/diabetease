"""Rule-based triage against published thresholds, for type 2 diabetes.

This module is NOT a predictive model. It is a deterministic rule check against
cut-offs published in the American Diabetes Association Standards of Care
(Section 2, Diagnosis and Classification). It produces no probability and no
risk score.

Two separate questions are answered here, and keeping them apart matters:

  1. Is a value already at or above a diagnostic cut-off? The cut-offs are the
     same whatever type of diabetes a person turns out to have, because they
     diagnose diabetes rather than classify it.

  2. Does this person meet the ADA criteria for being SCREENED in the first
     place? That question is specific to type 2 and prediabetes, and for most
     people it is the one that matters, because type 2 is usually silent for
     years before anything is abnormal.

Thresholds encoded here (verify against the edition you cite):
    fasting plasma glucose   >= 126 mg/dL   diagnostic range
    2-h plasma glucose       >= 200 mg/dL   diagnostic range (75 g OGTT)
    random plasma glucose    >= 200 mg/dL   diagnostic range (with symptoms)
    HbA1c                    >= 6.5 %       diagnostic range
    fasting plasma glucose   100-125 mg/dL  intermediate range
    2-h plasma glucose       140-199 mg/dL  intermediate range
    HbA1c                    5.7-6.4 %      intermediate range
    any plasma glucose       < 70 mg/dL     below normal (ADA level 1)
    any plasma glucose       < 54 mg/dL     clinically significant low (level 2)
    screening age            >= 35 years    screen everyone from here
    BMI                      >= 25 kg/m2    overweight, with >= 1 risk factor
    BMI                      >= 23 kg/m2    the same, for Asian ancestry
    rescreen interval        3 years        if results are normal

The BMI cut-off is the one to read twice for this study. The ADA sets it at
23 rather than 25 for people of Asian ancestry, and lists Asian ancestry as a
risk factor in its own right. For a Filipino cohort both apply, so the bar for
"should be screened" is lower here than the headline figure suggests.

Keep every threshold in THRESHOLDS so a reviewer can audit them in one place
and so they can be changed without touching the branching logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

THRESHOLDS = {
    "fasting_glucose_diagnostic_mgdl": 126.0,
    "fasting_glucose_intermediate_low_mgdl": 100.0,
    "two_hour_glucose_diagnostic_mgdl": 200.0,
    "two_hour_glucose_intermediate_low_mgdl": 140.0,
    "random_glucose_diagnostic_mgdl": 200.0,
    "hba1c_diagnostic_pct": 6.5,
    "hba1c_intermediate_low_pct": 5.7,
    "hyperglycaemic_emergency_signs_required": 2,
    # ADA glycaemic thresholds: below 70 mg/dL is the level 1 hypoglycaemia
    # alert value; below 54 mg/dL is level 2, clinically significant.
    "glucose_low_mgdl": 70.0,
    "glucose_very_low_mgdl": 54.0,
    # ADA screening criteria for type 2 and prediabetes.
    "screening_age_years": 35,
    "bmi_overweight_kgm2": 25.0,
    "bmi_overweight_asian_ancestry_kgm2": 23.0,
    "rescreen_interval_years": 3,
}

THRESHOLD_SOURCE = (
    "Diagnostic and prediabetes cut-offs, and the screening criteria in Table 2.5: "
    "American Diabetes Association, Standards of Care in Diabetes—2026, Section 2 "
    "(Diabetes Care 49, Suppl 1, S27–S49). Universal screening from age 35 is "
    "recommendation 2.12b; risk-based screening at a lower age is 2.12a; the "
    "three-year rescreening interval and the BMI cut-offs of 25 kg/m2, or 23 kg/m2 "
    "for individuals of Asian ancestry, are from the same section. Low-glucose "
    "levels: the same Standards, Section 6 (S132–S149); that classification is "
    "written for people with diabetes and is used here as a reference band. "
    "Sources checked 16 November 2026."
)

# Table 2.5, verbatim in substance. A person needs overweight or obesity AND at
# least one of these before the age of 35 for screening to be indicated; from 35
# it is indicated regardless.
RISK_FACTORS = {
    "family_history": "First-degree relative with diabetes",
    "high_risk_ancestry": (
        "High-risk race, ethnicity or ancestry (including Asian ancestry, which "
        "applies to this study's population)"
    ),
    "cardiovascular_disease": "History of cardiovascular disease",
    "hypertension": "Hypertension (at or above 130/80 mmHg, or on treatment for it)",
    "dyslipidaemia": "HDL cholesterol below 35 mg/dL and/or triglycerides above 250 mg/dL",
    "physical_inactivity": "Physical inactivity",
    "pcos": "Polycystic ovary syndrome",
    "insulin_resistance_signs": (
        "Another condition associated with insulin resistance, such as severe "
        "obesity or acanthosis nigricans"
    ),
    "prior_gestational_diabetes": "Diabetes during a previous pregnancy",
    "prediabetes": "A previous result in the prediabetes range",
}

Tier = Literal["emergency", "urgent", "followup", "insufficient", "no_threshold"]


@dataclass
class TriageInput:
    age: int
    family_history_t2d: str = "unknown"      # yes | no | unknown
    asian_ancestry: str = "unknown"          # yes | no | unknown
    bmi: float | None = None
    risk_factors: list[str] = field(default_factory=list)   # keys of RISK_FACTORS
    symptoms: list[str] = field(default_factory=list)
    urgent_signs: list[str] = field(default_factory=list)
    glucose_test_type: str = "none"          # none | fasting | two_hour | random
    glucose_mgdl: float | None = None
    hba1c_pct: float | None = None


@dataclass
class TriageResult:
    tier: Tier
    headline: str
    explanation: str
    reasons: list[dict]
    emergency: bool
    thresholds_used: dict
    threshold_source: str
    screening_indicated: bool = False
    screening_reason: str = ""


def _bmi_cutoff(i: TriageInput) -> float:
    """The overweight cut-off that applies to this person.

    Asian ancestry lowers it from 25 to 23. "unknown" takes the lower cut-off
    deliberately: in a Filipino cohort the lower one is the likely correct
    answer, and erring toward "get tested" is the safer error for a screening
    tool to make.
    """
    if i.asian_ancestry in ("yes", "unknown"):
        return THRESHOLDS["bmi_overweight_asian_ancestry_kgm2"]
    return THRESHOLDS["bmi_overweight_kgm2"]


def _collected_risk_factors(i: TriageInput) -> list[str]:
    keys = [k for k in i.risk_factors if k in RISK_FACTORS]
    if i.family_history_t2d == "yes" and "family_history" not in keys:
        keys.append("family_history")
    if i.asian_ancestry == "yes" and "high_risk_ancestry" not in keys:
        keys.append("high_risk_ancestry")
    return keys


def screening_assessment(i: TriageInput) -> tuple[bool, str]:
    """Does the ADA recommend testing this person? Returns (indicated, why).

    This is recommendations 2.12a and 2.12b as a rule check, not a risk score.
    """
    if i.age >= THRESHOLDS["screening_age_years"]:
        return True, (
            f"The ADA recommends screening every adult from age "
            f"{THRESHOLDS['screening_age_years']}, whatever their other risk factors, "
            f"and repeating it at least every {THRESHOLDS['rescreen_interval_years']} "
            "years while results stay normal."
        )

    cutoff = _bmi_cutoff(i)
    factors = _collected_risk_factors(i)
    if i.bmi is not None and i.bmi >= cutoff and factors:
        named = "; ".join(RISK_FACTORS[k] for k in factors)
        return True, (
            f"Below age {THRESHOLDS['screening_age_years']} the ADA recommends testing "
            f"at a BMI of {cutoff:g} kg/m2 or above together with at least one risk "
            f"factor. This BMI is {i.bmi:g}, and these apply: {named}."
        )

    if i.bmi is None:
        return False, (
            "Whether screening is recommended below age "
            f"{THRESHOLDS['screening_age_years']} depends on BMI, which was not "
            "entered, so this cannot be answered here."
        )
    if i.bmi >= cutoff and not factors:
        return False, (
            f"BMI is at or above the {cutoff:g} kg/m2 cut-off, but the ADA also asks "
            "for at least one risk factor before testing someone under "
            f"{THRESHOLDS['screening_age_years']}, and none was reported."
        )
    return False, (
        f"Under age {THRESHOLDS['screening_age_years']}, with a BMI below "
        f"{cutoff:g} kg/m2, routine screening is not what the ADA recommends. That "
        "says nothing about any symptom you may have now."
    )


def _glucose_diagnostic(i: TriageInput) -> bool:
    if i.glucose_mgdl is None:
        return False
    if i.glucose_test_type == "fasting":
        return i.glucose_mgdl >= THRESHOLDS["fasting_glucose_diagnostic_mgdl"]
    if i.glucose_test_type == "two_hour":
        return i.glucose_mgdl >= THRESHOLDS["two_hour_glucose_diagnostic_mgdl"]
    if i.glucose_test_type == "random":
        return i.glucose_mgdl >= THRESHOLDS["random_glucose_diagnostic_mgdl"]
    return False


def _glucose_intermediate(i: TriageInput) -> bool:
    if i.glucose_mgdl is None:
        return False
    if i.glucose_test_type == "fasting":
        return (
            THRESHOLDS["fasting_glucose_intermediate_low_mgdl"]
            <= i.glucose_mgdl
            < THRESHOLDS["fasting_glucose_diagnostic_mgdl"]
        )
    if i.glucose_test_type == "two_hour":
        return (
            THRESHOLDS["two_hour_glucose_intermediate_low_mgdl"]
            <= i.glucose_mgdl
            < THRESHOLDS["two_hour_glucose_diagnostic_mgdl"]
        )
    return False


def _glucose_very_low(i: TriageInput) -> bool:
    return i.glucose_mgdl is not None and i.glucose_mgdl < THRESHOLDS["glucose_very_low_mgdl"]


def _glucose_low(i: TriageInput) -> bool:
    return (i.glucose_mgdl is not None
            and THRESHOLDS["glucose_very_low_mgdl"] <= i.glucose_mgdl < THRESHOLDS["glucose_low_mgdl"])


def _hba1c_diagnostic(i: TriageInput) -> bool:
    return i.hba1c_pct is not None and i.hba1c_pct >= THRESHOLDS["hba1c_diagnostic_pct"]


def _hba1c_intermediate(i: TriageInput) -> bool:
    if i.hba1c_pct is None:
        return False
    return (
        THRESHOLDS["hba1c_intermediate_low_pct"]
        <= i.hba1c_pct
        < THRESHOLDS["hba1c_diagnostic_pct"]
    )


def evaluate(i: TriageInput) -> TriageResult:
    """Return a next-step recommendation. Deterministic; no randomness, no scoring."""
    reasons: list[dict] = []
    n_symptoms = len(i.symptoms)
    n_urgent = len(i.urgent_signs)

    at_or_above_diagnostic = _glucose_diagnostic(i) or _hba1c_diagnostic(i)
    intermediate = _glucose_intermediate(i) or _hba1c_intermediate(i)
    no_labs = i.glucose_mgdl is None and i.hba1c_pct is None
    screen, screen_why = screening_assessment(i)

    def result(**kw) -> TriageResult:
        kw.setdefault("thresholds_used", THRESHOLDS)
        kw.setdefault("threshold_source", THRESHOLD_SOURCE)
        kw.setdefault("screening_indicated", screen)
        kw.setdefault("screening_reason", screen_why)
        return TriageResult(**kw)

    # 1. Emergency always wins and is evaluated first. Medical-safety requirement:
    #    emergency guidance must never sit behind a score, a model, or a form step.
    if n_urgent >= THRESHOLDS["hyperglycaemic_emergency_signs_required"] and (
        n_symptoms >= 1 or at_or_above_diagnostic
    ):
        return result(
            tier="emergency",
            headline="Seek emergency care now",
            explanation=(
                "The signs reported here can together indicate a hyperglycaemic "
                "emergency, which is life-threatening and can develop quickly. This "
                "result overrides everything else in the system."
            ),
            reasons=[{
                "label": "What to do",
                "text": (
                    "Go to the nearest emergency department immediately, or call 911. "
                    "Do not wait for a clinic appointment and do not wait for a "
                    "laboratory result."
                ),
            }],
            emergency=True,
        )

    very_low = _glucose_very_low(i)
    low = _glucose_low(i)

    # 2. A value in the diagnostic range, or a clinically significant low glucose.
    if at_or_above_diagnostic or very_low:
        if at_or_above_diagnostic:
            reasons.append({
                "label": "Why",
                "text": (
                    "A value entered is at or above a published diagnostic cut-off: "
                    "fasting glucose 126 mg/dL, 2-hour or random glucose 200 mg/dL, or "
                    "HbA1c 6.5%. A single reading is not a diagnosis; it has to be "
                    "confirmed, usually by repeating the test on another day."
                ),
            })
            reasons.append({
                "label": "Important",
                "text": (
                    "These thresholds identify abnormal glucose. They do not establish "
                    "which type of diabetes it is. Type 2 is the most common by a wide "
                    "margin, but telling the types apart is a clinician's judgement and "
                    "sometimes needs further testing."
                ),
            })
        if very_low:
            reasons.append({
                "label": "Why",
                "text": (
                    "Blood glucose below 54 mg/dL is classed as clinically significant "
                    "low glucose. It can cause shakiness, sweating, confusion and, if it "
                    "falls further, loss of consciousness. If the person is drowsy or "
                    "confused now, treat it as an emergency."
                ),
            })
        return result(
            tier="urgent",
            headline="See a doctor promptly",
            explanation=(
                "At least one finding is at or above a published threshold that "
                "requires a clinician to confirm and act on."
            ),
            reasons=reasons,
            emergency=False,
        )

    # 3. Enough to justify a test, nothing at a cut-off.
    if intermediate or low or n_symptoms >= 2 or (i.family_history_t2d == "yes" and n_symptoms >= 1) or (screen and no_labs):
        if intermediate:
            reasons.append({
                "label": "Why",
                "text": (
                    "Glucose or HbA1c sits in the intermediate range below the "
                    "diagnostic cut-off — what the ADA calls prediabetes. That range "
                    "warrants repeat testing, and it is the point at which changes to "
                    "diet and activity do the most good."
                ),
            })
        if low:
            reasons.append({
                "label": "Why",
                "text": (
                    "Blood glucose is under 70 mg/dL, the level the ADA uses as its low-"
                    "glucose alert value for people with diabetes. One low "
                    "reading can follow a long fast or heavy exercise, but it is worth "
                    "raising with a clinician, particularly if it recurs or comes with "
                    "shakiness, sweating or confusion."
                ),
            })
        if n_symptoms >= 2:
            reasons.append({
                "label": "Why",
                "text": (
                    f"{n_symptoms} of the symptoms that can accompany type 2 "
                    "diabetes were reported. None is specific on its own, which is "
                    "exactly why a glucose test is the sensible next step. Type 2 often "
                    "produces no symptoms at all, so their absence would not have been "
                    "reassuring either."
                ),
            })
        if i.family_history_t2d == "yes":
            reasons.append({
                "label": "Family history",
                "text": (
                    "A parent or sibling with type 2 diabetes is one of the risk factors "
                    "the ADA lists for earlier screening. It raises risk substantially, "
                    "though most people with an affected relative do not go on to "
                    "develop it. No figure specific to the Philippines is available "
                    "here, so none is quoted."
                ),
            })
        if screen and no_labs:
            reasons.append({"label": "Screening", "text": screen_why})
        return result(
            tier="followup",
            headline="Worth getting tested",
            explanation=(
                "Nothing entered crosses a diagnostic threshold, but there is enough "
                "here to justify a blood glucose test rather than waiting."
            ),
            reasons=reasons,
            emergency=False,
        )

    # 4. Nothing to work with.
    if no_labs:
        return result(
            tier="insufficient",
            headline="Not enough information to say anything useful",
            explanation=(
                "No laboratory result was entered and the reported symptoms do not "
                "form a pattern. This system cannot assess anyone from demographics "
                "alone and will not pretend otherwise."
            ),
            reasons=[
                {
                    "label": "What would help",
                    "text": (
                        "A fasting blood glucose test or an HbA1c. Either is "
                        "inexpensive, widely available, and settles the question in a "
                        "way this form cannot."
                    ),
                },
                {"label": "Screening", "text": screen_why},
            ],
            emergency=False,
        )

    # 5. Values present, none crossing a threshold. Explicitly not an all-clear.
    return result(
        tier="no_threshold",
        headline="Nothing here crosses a threshold",
        explanation=(
            "The values and symptoms entered do not meet any published cut-off. That "
            "is reassuring about today. It is not a clean bill of health."
        ),
        reasons=[
            {
                "label": "Why this is not an all-clear",
                "text": (
                    "Type 2 diabetes develops gradually, often over years, and usually "
                    "without symptoms until glucose is already high. A normal result "
                    "describes today only. The ADA's answer to that is not a single "
                    "test but repeat testing at least every "
                    f"{THRESHOLDS['rescreen_interval_years']} years."
                ),
            },
            {
                "label": "Come back if",
                "text": (
                    "Thirst, frequent urination, blurred vision, fatigue, or slow-"
                    "healing cuts or infections appear or worsen — or simply when the "
                    "next screening interval comes round."
                ),
            },
        ],
        emergency=False,
    )
