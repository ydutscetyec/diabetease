"""Database schema.

Design notes that matter for the research write-up:

* `facilities.status` is never defaulted to "verified". A record that arrives
  without a source and a verification date is "unconfirmed", and the API will
  not let a service be marked confirmed without both.
* `facility_services.confirmed` is per service, not per facility. A hospital may
  have confirmed HbA1c testing and unconfirmed autoantibody testing; collapsing
  those into one flag is how fabricated capability claims get into a map.
* `assessment_sessions` stores no identifier of any kind and is only written when
  STORE_ASSESSMENTS is explicitly enabled.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

SERVICE_CODES = ("glucose", "hba1c", "ogtt", "autoantibody", "consultation",
                 "insulin", "glucose_supplies")
FACILITY_STATUSES = ("verified", "unconfirmed", "outdated")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Municipality(Base):
    __tablename__ = "municipalities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    province: Mapped[str] = mapped_column(String(64), default="South Cotabato")
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    centroid_lon: Mapped[float | None] = mapped_column(Float)
    centroid_is_approximate: Mapped[bool] = mapped_column(Boolean, default=True)
    facilities: Mapped[list["Facility"]] = relationship(back_populates="municipality")


class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    facility_type: Mapped[str] = mapped_column(String(64))
    municipality_id: Mapped[int] = mapped_column(ForeignKey("municipalities.id"), index=True)
    address: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    contact: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str | None] = mapped_column(String(300))
    verified_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="unconfirmed", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    municipality: Mapped[Municipality] = relationship(back_populates="facilities")
    services: Mapped[list["FacilityService"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan"
    )
    history: Mapped[list["FacilityVerification"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_facility_geo", "latitude", "longitude"),)


class FacilityService(Base):
    __tablename__ = "facility_services"
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True)
    service_code: Mapped[str] = mapped_column(String(32))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(300))
    verified_on: Mapped[date | None] = mapped_column(Date)
    facility: Mapped[Facility] = relationship(back_populates="services")
    __table_args__ = (UniqueConstraint("facility_id", "service_code", name="uq_facility_service"),)


class FacilityVerification(Base):
    __tablename__ = "facility_verification_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True)
    checked_on: Mapped[date] = mapped_column(Date)
    checked_by: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(120))       # phone call, site visit, registry
    outcome: Mapped[str] = mapped_column(String(32))       # confirmed, changed, unreachable
    notes: Mapped[str | None] = mapped_column(Text)
    facility: Mapped[Facility] = relationship(back_populates="history")


class ModelVersion(Base):
    """Registry of trained artifacts. `is_active` gates what inference will load."""
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    algorithm: Mapped[str] = mapped_column(String(64))
    prediction_task: Mapped[str] = mapped_column(String(120))
    dataset_label: Mapped[str] = mapped_column(String(200))
    dataset_is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    n_train: Mapped[int | None] = mapped_column(Integer)
    n_test: Mapped[int | None] = mapped_column(Integer)
    artifact_path: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    limitations: Mapped[str | None] = mapped_column(Text)
    evaluations: Mapped[list["ModelEvaluation"]] = relationship(
        back_populates="model_version", cascade="all, delete-orphan"
    )


class ModelEvaluation(Base):
    __tablename__ = "model_evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    metric: Mapped[str] = mapped_column(String(48))
    value: Mapped[float] = mapped_column(Float)
    split: Mapped[str] = mapped_column(String(32), default="test")
    model_version: Mapped[ModelVersion] = relationship(back_populates="evaluations")


class AssessmentSession(Base):
    """De-identified record, written only when STORE_ASSESSMENTS=true."""
    __tablename__ = "assessment_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    age_band: Mapped[str] = mapped_column(String(16))      # banded, never the exact age
    municipality: Mapped[str | None] = mapped_column(String(64))
    n_symptoms: Mapped[int] = mapped_column(Integer, default=0)
    n_urgent_signs: Mapped[int] = mapped_column(Integer, default=0)
    had_glucose: Mapped[bool] = mapped_column(Boolean, default=False)
    had_hba1c: Mapped[bool] = mapped_column(Boolean, default=False)
    autoantibody_status: Mapped[str] = mapped_column(String(32), default="none")
    triage_tier: Mapped[str] = mapped_column(String(32))
    model_version: Mapped[str | None] = mapped_column(String(64))
    purge_after: Mapped[date] = mapped_column(Date, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), index=True)


class Account(Base):
    """User accounts. Roles decide which pages and endpoints are reachable.

    Privacy note: creating an account necessarily makes stored assessments
    linkable to a person, which the anonymous flow deliberately avoided. Storage
    therefore stays opt-in per assessment AND gated by STORE_ASSESSMENTS, and
    every account can delete itself and its records.
    """
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(16), default="patient", index=True)
    display_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Self-registration only ever creates patients; staff roles are granted by an
    # existing admin, so nobody can promote themselves from the signup form.
    granted_by: Mapped[str | None] = mapped_column(String(64))


ROLES = ("patient", "researcher", "admin")


class AdminUser(Base):
    __tablename__ = "administrative_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(32), default="researcher")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
