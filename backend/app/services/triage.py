"""Rule-based triage against published diagnostic thresholds.

This module is NOT a predictive model. It is a deterministic rule check against
cut-offs published in the American Diabetes Association Standards of Care
(Section 2, Diagnosis and Classification) and the ISPAD consensus guidelines on
staging presymptomatic type 1 diabetes.

It exists so that DiabetEASE can give a defensible next step today, while no
trained model is available. It produces no probability and no risk score.

Thresholds encoded here (verify against the edition you cite):
    fasting plasma glucose  >= 126 mg/dL   diagnostic range
    random plasma glucose   >= 200 mg/dL   diagnostic range (with symptoms)
    HbA1c                   >= 6.5 %       diagnostic range
    fasting plasma glucose  100-125 mg/dL  intermediate range
    any plasma glucose      < 70 mg/dL     below normal (ADA level 1 hypoglycaemia)
    any plasma glucose      < 54 mg/dL     clinically significant low (ADA level 2)
    HbA1c                   5.7-6.4 %      intermediate range
    >= 2 persistent islet autoantibodies   defines early-stage type 1 diabetes

Keep every threshold in THRESHOLDS so a reviewer can audit them in one place and
so they can be changed without touching the branching logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

THRESHOLDS = {
    "fasting_glucose_diagnostic_mgdl": 126.0,
    "fasting_glucose_intermediate_low_mgdl": 100.0,
    "random_glucose_diagnostic_mgdl": 200.0,
    "hba1c_diagnostic_pct": 6.5,
    "hba1c_intermediate_low_pct": 5.7,
    "autoantibodies_defining_early_stage": 2,
    "dka_signs_required_for_emergency": 2,
    # ADA glycaemic thresholds: below 70 mg/dL is the level 1 hypoglycaemia
    # alert value; below 54 mg/dL is level 2, clinically significant.
    "glucose_low_mgdl": 70.0,
    "glucose_very_low_mgdl": 54.0,
}

THRESHOLD_SOURCE = (
    "Diagnostic and prediabetes cut-offs: American Diabetes Association, Standards of "
    "Care in Diabetes—2026, Section 2 (Diabetes Care 49, Suppl 1, S27–S49). "
    "Low-glucose levels: the same Standards, Section 6 (S132–S149); that "
    "classification is written for people with diabetes and is used here as a "
    "reference band. Staging of early type 1 diabetes: ISPAD Clinical Practice "
    "Consensus Guidelines 2024 (Haller et al., Horm Res Paediatr 97(6), 529–545). "
    "Sources checked 11 November 2026."
)

Tier = Literal["emergency", "urgent", "followup", "insufficient", "no_threshold"]


@dataclass
class TriageInput:
    age: int
    family_history_t1d: str = "unknown"      # yes | no | unknown
    family_autoimmune: str = "unknown"       # yes | no | unknown
    symptoms: list[str] = field(default_factory=list)
    urgent_signs: list[str] = field(default_factory=list)
    glucose_test_type: str = "none"          # none | fasting | random
    glucose_mgdl: float | None = None
    hba1c_pct: float | None = None
    autoantibodies: str = "none"             # none | negative | one_positive | two_or_more_positive


@dataclass
class TriageResult:
    tier: Tier
    headline: str
    explanation: str
    reasons: list[dict]
    emergency: bool
    thresholds_used: dict
    threshold_source: str


def _glucose_diagnostic(i: TriageInput) -> bool:
    if i.glucose_mgdl is None:
        return False
    if i.glucose_test_type == "fasting":
        return i.glucose_mgdl >= THRESHOLDS["fasting_glucose_diagnostic_mgdl"]
    if i.glucose_test_type == "random":
        return i.glucose_mgdl >= THRESHOLDS["random_glucose_diagnostic_mgdl"]
    return False


def _glucose_intermediate(i: TriageInput) -> bool:
    if i.glucose_mgdl is None or i.glucose_test_type != "fasting":
        return False
    return (
        THRESHOLDS["fasting_glucose_intermediate_low_mgdl"]
        <= i.glucose_mgdl
        < THRESHOLDS["fasting_glucose_diagnostic_mgdl"]
    )


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
    aab_positive = i.autoantibodies in ("one_positive", "two_or_more_positive")
    aab_staging = i.autoantibodies == "two_or_more_positive"
    no_labs = i.glucose_mgdl is None and i.hba1c_pct is None and i.autoantibodies == "none"

    # 1. Emergency always wins and is evaluated first. Medical-safety requirement:
    #    emergency guidance must never sit behind a score, a model, or a form step.
    if n_urgent >= THRESHOLDS["dka_signs_required_for_emergency"] and (
        n_symptoms >= 1 or at_or_above_diagnostic
    ):
        return TriageResult(
            tier="emergency",
            headline="Seek emergency care now",
            explanation=(
                "The signs reported here can together indicate diabetic ketoacidosis, "
                "a life-threatening complication whose severe symptoms can appear quickly. This "
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
            thresholds_used=THRESHOLDS,
            threshold_source=THRESHOLD_SOURCE,
        )

    very_low = _glucose_very_low(i)
    low = _glucose_low(i)

    # 2. A value in the diagnostic range, antibody staging, or a clinically
    #    significant low glucose.
    if at_or_above_diagnostic or aab_staging or very_low:
        if at_or_above_diagnostic:
            reasons.append({
                "label": "Why",
                "text": (
                    "A value entered is at or above a published diagnostic cut-off: "
                    "fasting glucose 126 mg/dL, random glucose 200 mg/dL, or HbA1c 6.5%. "
                    "A single reading is not a diagnosis; it has to be confirmed."
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
        if aab_staging:
            reasons.append({
                "label": "Why",
                "text": (
                    "Two or more persistently positive islet autoantibodies define "
                    "early-stage type 1 diabetes. Staging needs repeat testing and a "
                    "glucose assessment ordered by a clinician."
                ),
            })
        if at_or_above_diagnostic or aab_staging:
            reasons.append({
                "label": "Important",
                "text": (
                    "These thresholds identify abnormal glucose. They do not establish "
                    "whether it is type 1 or type 2 diabetes; that distinction requires "
                    "antibody testing and clinical judgement."
                ),
            })
        return TriageResult(
            tier="urgent",
            headline="See a doctor promptly",
            explanation=(
                "At least one finding is at or above a published threshold that "
                "requires a clinician to confirm and act on."
            ),
            reasons=reasons,
            emergency=False,
            thresholds_used=THRESHOLDS,
            threshold_source=THRESHOLD_SOURCE,
        )

    # 3. Enough to justify a test, nothing at a cut-off.
    if aab_positive or n_symptoms >= 2 or (i.family_history_t1d == "yes" and n_symptoms >= 1) or intermediate or low:
        if n_symptoms >= 2:
            reasons.append({
                "label": "Why",
                "text": (
                    f"{n_symptoms} of the symptoms that commonly accompany new type 1 "
                    "diabetes were reported. None is specific on its own, which is "
                    "exactly why a glucose test is the sensible next step."
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
        if intermediate:
            reasons.append({
                "label": "Why",
                "text": (
                    "Glucose or HbA1c sits in the intermediate range below the "
                    "diagnostic cut-off. That range warrants repeat testing."
                ),
            })
        if aab_positive and not aab_staging:
            reasons.append({
                "label": "Why",
                "text": (
                    "A single positive islet autoantibody needs confirmation on a "
                    "repeat sample. One antibody alone is not early-stage type 1 "
                    "diabetes: in children it carries roughly a 15% chance of "
                    "clinical diabetes within 15 years, far below the risk with "
                    "two or more. It is not staging and is not a diagnosis."
                ),
            })
        if i.family_history_t1d == "yes":
            reasons.append({
                "label": "Family history",
                "text": (
                    "A parent or sibling with type 1 diabetes raises lifetime risk to "
                    "roughly 1 in 20, against about 1 in 300 in the general population. Those "
                    "figures come from studies in the United States; none exists for the "
                    "Philippines. "
                    "Most such relatives still never develop it."
                ),
            })
        return TriageResult(
            tier="followup",
            headline="Worth getting tested",
            explanation=(
                "Nothing entered crosses a diagnostic threshold, but there is enough "
                "here to justify a blood glucose test rather than waiting."
            ),
            reasons=reasons,
            emergency=False,
            thresholds_used=THRESHOLDS,
            threshold_source=THRESHOLD_SOURCE,
        )

    # 4. Nothing to work with.
    if no_labs:
        return TriageResult(
            tier="insufficient",
            headline="Not enough information to say anything useful",
            explanation=(
                "No laboratory result was entered and the reported symptoms do not "
                "form a pattern. This system cannot assess anyone from demographics "
                "alone and will not pretend otherwise."
            ),
            reasons=[{
                "label": "What would help",
                "text": (
                    "A fasting or random blood glucose test. It is inexpensive, widely "
                    "available, and settles the question in a way this form cannot."
                ),
            }],
            emergency=False,
            thresholds_used=THRESHOLDS,
            threshold_source=THRESHOLD_SOURCE,
        )

    # 5. Values present, none crossing a threshold. Explicitly not an all-clear.
    return TriageResult(
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
                    "The autoimmune process behind type 1 diabetes begins months to "
                    "years before glucose becomes abnormal. A normal glucose result "
                    "cannot detect early-stage disease; only islet autoantibody "
                    "testing can."
                ),
            },
            {
                "label": "Come back if",
                "text": (
                    "Thirst, urination, weight loss or fatigue appear or worsen. "
                    "Symptoms in type 1 diabetes can go from mild to an emergency "
                    "within weeks, sometimes days."
                ),
            },
        ],
        emergency=False,
        thresholds_used=THRESHOLDS,
        threshold_source=THRESHOLD_SOURCE,
    )
