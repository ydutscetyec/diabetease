from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import AssessmentSession
from ..schemas import AssessmentRequest, AssessmentResponse
from ..services import inference
from ..services.triage import TriageInput, evaluate

router = APIRouter(prefix="/api/v1", tags=["assessment"])


def _age_band(age: int) -> str:
    for lo, hi in ((0, 4), (5, 9), (10, 14), (15, 19), (20, 29), (30, 44), (45, 64)):
        if lo <= age <= hi:
            return f"{lo}-{hi}"
    return "65+"


@router.post("/assessments", response_model=AssessmentResponse)
def create_assessment(payload: AssessmentRequest, db: Session = Depends(get_db)) -> AssessmentResponse:
    settings = get_settings()
    result = evaluate(TriageInput(
        age=payload.age,
        family_history_t1d=payload.family_history_t1d,
        family_autoimmune=payload.family_autoimmune,
        symptoms=payload.symptoms,
        urgent_signs=payload.urgent_signs,
        glucose_test_type=payload.glucose_test_type,
        glucose_mgdl=payload.glucose_mgdl,
        hba1c_pct=payload.hba1c_pct,
        autoantibodies=payload.autoantibodies,
    ))

    model_status = inference.status()

    stored = False
    # Storage requires BOTH an operator setting and the respondent's consent, and is
    # skipped entirely for emergency results so nobody is delayed by a database write.
    if settings.store_assessments and payload.consent_to_store and not result.emergency:
        db.add(AssessmentSession(
            age_band=_age_band(payload.age),
            municipality=payload.municipality,
            n_symptoms=len(payload.symptoms),
            n_urgent_signs=len(payload.urgent_signs),
            had_glucose=payload.glucose_mgdl is not None,
            had_hba1c=payload.hba1c_pct is not None,
            autoantibody_status=payload.autoantibodies,
            triage_tier=result.tier,
            model_version=model_status.get("version"),
            purge_after=date.today() + timedelta(days=settings.assessment_retention_days),
        ))
        db.commit()
        stored = True

    return AssessmentResponse(
        tier=result.tier,
        emergency=result.emergency,
        headline=result.headline,
        explanation=result.explanation,
        reasons=result.reasons,
        threshold_source=result.threshold_source,
        model=model_status,
        stored=stored,
        api_version=settings.api_version,
    )


@router.get("/assessments/thresholds")
def thresholds() -> dict:
    from ..services.triage import THRESHOLD_SOURCE, THRESHOLDS
    return {"thresholds": THRESHOLDS, "source": THRESHOLD_SOURCE}
