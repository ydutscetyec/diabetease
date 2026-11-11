from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SYMPTOM_CODES = {"thirst", "urination", "weight_loss", "fatigue", "blurred_vision", "hunger"}
URGENT_CODES = {"vomiting", "abdominal_pain", "rapid_breathing", "drowsiness"}


# --------------------------------------------------------------------------- assessment
class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: int = Field(ge=1, le=120, description="Age in whole years.")
    sex: Literal["female", "male", "not_given"] = "not_given"
    municipality: str | None = Field(default=None, max_length=64)
    family_history_t1d: Literal["yes", "no", "unknown"] = "unknown"
    family_autoimmune: Literal["yes", "no", "unknown"] = "unknown"
    symptoms: list[str] = Field(default_factory=list, max_length=12)
    urgent_signs: list[str] = Field(default_factory=list, max_length=8)
    glucose_test_type: Literal["none", "fasting", "random"] = "none"
    glucose_mgdl: float | None = Field(default=None, ge=20, le=900)
    hba1c_pct: float | None = Field(default=None, ge=3, le=20)
    autoantibodies: Literal["none", "negative", "one_positive", "two_or_more_positive"] = "none"
    consent_to_store: bool = False

    @field_validator("symptoms")
    @classmethod
    def _check_symptoms(cls, v: list[str]) -> list[str]:
        bad = set(v) - SYMPTOM_CODES
        if bad:
            raise ValueError(f"unknown symptom code(s): {sorted(bad)}")
        return sorted(set(v))

    @field_validator("urgent_signs")
    @classmethod
    def _check_urgent(cls, v: list[str]) -> list[str]:
        bad = set(v) - URGENT_CODES
        if bad:
            raise ValueError(f"unknown urgent sign code(s): {sorted(bad)}")
        return sorted(set(v))

    @model_validator(mode="after")
    def _glucose_pairing(self):
        # A value without a test type is uninterpretable: 140 mg/dL is normal after
        # a meal and diagnostic when fasting. Reject rather than guess.
        if self.glucose_mgdl is not None and self.glucose_test_type == "none":
            raise ValueError("glucose_mgdl requires glucose_test_type of 'fasting' or 'random'")
        if self.glucose_test_type != "none" and self.glucose_mgdl is None:
            raise ValueError("glucose_test_type was set but no glucose_mgdl was supplied")
        return self


class ModelStatus(BaseModel):
    available: bool
    status: str
    version: str | None = None
    prediction_task: str | None = None
    detail: str


class TriageReason(BaseModel):
    label: str
    text: str


class AssessmentResponse(BaseModel):
    tier: str
    emergency: bool
    headline: str
    explanation: str
    reasons: list[TriageReason]
    source: Literal["rule_based_thresholds"] = "rule_based_thresholds"
    threshold_source: str
    model: ModelStatus
    stored: bool
    api_version: str


# --------------------------------------------------------------------------- facilities
class ServiceOut(BaseModel):
    service_code: str
    confirmed: bool
    source: str | None = None
    verified_on: date | None = None


class FacilityOut(BaseModel):
    id: int
    name: str
    facility_type: str
    municipality: str
    address: str | None
    latitude: float | None
    longitude: float | None
    contact: str | None
    source: str | None
    verified_on: date | None
    status: str
    services: list[ServiceOut]


class NearbyFacility(BaseModel):
    facility: FacilityOut
    distance_km: float | None = None
    same_municipality: bool


class NearbyOut(BaseModel):
    municipality: str
    kind: str
    distance_basis: str
    confirmed_in_municipality: int
    items: list[NearbyFacility]


class FacilityListOut(BaseModel):
    total: int
    verified: int
    unconfirmed: int
    outdated: int
    attribution: str
    items: list[FacilityOut]


class ServiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_code: Literal["glucose", "hba1c", "ogtt", "autoantibody", "consultation",
                          "insulin", "glucose_supplies"]
    confirmed: bool = False
    source: str | None = Field(default=None, max_length=300)
    verified_on: date | None = None

    @model_validator(mode="after")
    def _confirm_needs_evidence(self):
        if self.confirmed and not (self.source and self.verified_on):
            raise ValueError(
                "a service can only be marked confirmed with both a source and a verified_on date"
            )
        return self


class FacilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    facility_type: str = Field(max_length=64)
    municipality: str = Field(max_length=64)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    contact: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=300)
    verified_on: date | None = None
    notes: str | None = None
    services: list[ServiceIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_rules(self):
        if any(s.confirmed for s in self.services) and not (self.source and self.verified_on):
            raise ValueError(
                "a facility with confirmed services needs its own source and verified_on date"
            )
        return self


class VerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked_on: date
    checked_by: str = Field(max_length=120)
    method: Literal["phone_call", "site_visit", "official_registry", "facility_website"]
    outcome: Literal["confirmed", "changed", "unreachable", "closed"]
    notes: str | None = None


# --------------------------------------------------------------------------- chat
class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=500)
    # Context for follow-ups ("what about in children?"). Capped so a client
    # cannot grow the prompt without limit. Never persisted server-side.
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


class ChatResponse(BaseModel):
    reply: str
    mode: Literal["rule_based", "language_model"]
    matched_topic: str | None
    refused: bool = False
    disclaimer: str
    # How the answer was produced, so the UI can label it and evaluators can audit it.
    route: Literal["emergency", "refused", "grounded", "open", "declined", "suggestions"] = "grounded"
    grounded: bool = True


# --------------------------------------------------------------------------- admin
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class TokenResponse(BaseModel):
    token: str
    expires_in: int
    role: str


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    # 10 characters is the floor; length beats complexity rules for real security.
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=80)


class AccountOut(BaseModel):
    username: str
    role: str
    display_name: str | None = None
    is_env_admin: bool = False


class RoleGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    role: Literal["patient", "researcher", "admin"]
