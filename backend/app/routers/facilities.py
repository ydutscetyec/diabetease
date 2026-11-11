from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Facility, FacilityService, FacilityVerification, Municipality
from ..schemas import (FacilityIn, FacilityListOut, FacilityOut, NearbyFacility,
                       NearbyOut, VerificationIn)
from .auth import require_role

router = APIRouter(prefix="/api/v1", tags=["facilities"])

ATTRIBUTION = (
    "Facility records are collected by the DiabetEASE research team from official "
    "directories, facility websites and direct confirmation. Each record carries its "
    "own source and verification date. Base map tiles: © OpenStreetMap contributors."
)


def _to_out(f: Facility) -> FacilityOut:
    return FacilityOut(
        id=f.id, name=f.name, facility_type=f.facility_type,
        municipality=f.municipality.name, address=f.address,
        latitude=f.latitude, longitude=f.longitude, contact=f.contact,
        source=f.source, verified_on=f.verified_on, status=f.status,
        services=[
            {"service_code": s.service_code, "confirmed": s.confirmed,
             "source": s.source, "verified_on": s.verified_on}
            for s in f.services
        ],
    )


@router.get("/municipalities")
def list_municipalities(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Municipality).order_by(Municipality.name).all()
    return {
        "note": "Centroids are approximate and are for map framing only, not facility locations.",
        "items": [
            {"id": m.id, "name": m.name, "province": m.province,
             "centroid": {"lat": m.centroid_lat, "lon": m.centroid_lon,
                          "approximate": m.centroid_is_approximate}}
            for m in rows
        ],
    }


@router.get("/facilities", response_model=FacilityListOut)
def list_facilities(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=120),
    municipality: str | None = Query(default=None, max_length=64),
    service: str | None = Query(default=None, max_length=32),
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    confirmed_only: bool = Query(default=False),
    kind: str | None = Query(default=None, pattern="^(testing|pharmacy)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> FacilityListOut:
    base = db.query(Facility).options(
        selectinload(Facility.services), selectinload(Facility.municipality)
    ).join(Municipality)

    if q:
        base = base.filter(Facility.name.ilike(f"%{q}%"))
    if municipality:
        base = base.filter(Municipality.name == municipality)
    if status_filter:
        base = base.filter(Facility.status == status_filter)
    if kind == "pharmacy":
        base = base.filter(Facility.facility_type == "Pharmacy")
    elif kind == "testing":
        base = base.filter(Facility.facility_type != "Pharmacy")
    if service:
        base = base.join(FacilityService).filter(FacilityService.service_code == service)
        if confirmed_only:
            base = base.filter(FacilityService.confirmed.is_(True))

    items = base.order_by(Facility.name).offset(offset).limit(limit).all()
    counts = {
        s: db.query(Facility).filter(Facility.status == s).count()
        for s in ("verified", "unconfirmed", "outdated")
    }
    return FacilityListOut(
        total=db.query(Facility).count(),
        verified=counts["verified"],
        unconfirmed=counts["unconfirmed"],
        outdated=counts["outdated"],
        attribution=ATTRIBUTION,
        items=[_to_out(f) for f in items],
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby_facilities(db: Session, municipality: str, kind: str, limit: int) -> NearbyOut | None:
    """Facilities for someone in `municipality`, most useful first.

    Order: confirmed-service facilities before unconfirmed ones, then by
    straight-line distance from the municipal centre. Distance is measured from
    an approximate centroid, not from the person, and says nothing about roads
    or travel time. That limit is returned with the data, not buried in docs.
    """
    muni = db.query(Municipality).filter(Municipality.name == municipality).one_or_none()
    if muni is None:
        return None

    base = db.query(Facility).options(
        selectinload(Facility.services), selectinload(Facility.municipality))
    if kind == "pharmacy":
        base = base.filter(Facility.facility_type == "Pharmacy")
    else:
        base = base.filter(Facility.facility_type != "Pharmacy")

    rows = []
    for f in base.all():
        has_confirmed = any(s.confirmed for s in f.services)
        dist = None
        if None not in (f.latitude, f.longitude, muni.centroid_lat, muni.centroid_lon):
            dist = round(_haversine_km(muni.centroid_lat, muni.centroid_lon,
                                       f.latitude, f.longitude), 1)
        rows.append((f, has_confirmed, dist))

    # confirmed first; unknown distance sorts last within its group
    rows.sort(key=lambda r: (not r[1], r[2] is None, r[2] if r[2] is not None else 0.0, r[0].name))

    return NearbyOut(
        municipality=muni.name,
        kind=kind,
        distance_basis=("Straight-line distance from the approximate centre of "
                        f"{muni.name}. It is not travel distance or travel time."),
        confirmed_in_municipality=sum(
            1 for f, ok, _ in rows if ok and f.municipality_id == muni.id),
        items=[NearbyFacility(facility=_to_out(f), distance_km=d,
                              same_municipality=f.municipality_id == muni.id)
               for f, _, d in rows[:limit]],
    )


@router.get("/facilities/nearby", response_model=NearbyOut)
def nearby(
    municipality: str = Query(max_length=64),
    kind: str = Query(default="testing", pattern="^(testing|pharmacy)$"),
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> NearbyOut:
    out = nearby_facilities(db, municipality, kind, limit)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"'{municipality}' is not one of the covered municipalities")
    return out


@router.get("/facilities/{facility_id}", response_model=FacilityOut)
def get_facility(facility_id: int, db: Session = Depends(get_db)) -> FacilityOut:
    f = db.query(Facility).options(
        selectinload(Facility.services), selectinload(Facility.municipality)
    ).filter(Facility.id == facility_id).one_or_none()
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "facility not found")
    return _to_out(f)


@router.post("/facilities", response_model=FacilityOut, status_code=201)
def create_facility(
    body: FacilityIn,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_role("researcher", "admin")),
) -> FacilityOut:
    muni = db.query(Municipality).filter(Municipality.name == body.municipality).one_or_none()
    if not muni:
        raise HTTPException(422,
                            f"'{body.municipality}' is outside the study coverage area")

    # Status is derived from evidence, never accepted from the client.
    has_confirmed = any(s.confirmed for s in body.services)
    derived = "verified" if (has_confirmed and body.source and body.verified_on) else "unconfirmed"

    f = Facility(
        name=body.name, facility_type=body.facility_type, municipality_id=muni.id,
        address=body.address, latitude=body.latitude, longitude=body.longitude,
        contact=body.contact, source=body.source, verified_on=body.verified_on,
        status=derived, notes=body.notes,
    )
    for s in body.services:
        f.services.append(FacilityService(
            service_code=s.service_code, confirmed=s.confirmed,
            source=s.source, verified_on=s.verified_on,
        ))
    db.add(f)
    db.commit()
    db.refresh(f)
    return _to_out(f)


@router.post("/facilities/{facility_id}/verifications", status_code=201)
def add_verification(
    facility_id: int,
    body: VerificationIn,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_role("researcher", "admin")),
) -> dict:
    f = db.query(Facility).filter(Facility.id == facility_id).one_or_none()
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "facility not found")
    db.add(FacilityVerification(
        facility_id=facility_id, checked_on=body.checked_on, checked_by=body.checked_by,
        method=body.method, outcome=body.outcome, notes=body.notes,
    ))
    if body.outcome == "confirmed":
        f.verified_on, f.status = body.checked_on, "verified"
    elif body.outcome in ("changed", "closed", "unreachable"):
        f.status = "outdated"
    db.commit()
    return {"facility_id": facility_id, "status": f.status, "verified_on": f.verified_on}


@router.get("/facilities/{facility_id}/verifications")
def list_verifications(facility_id: int, db: Session = Depends(get_db)) -> dict:
    rows = db.query(FacilityVerification).filter(
        FacilityVerification.facility_id == facility_id
    ).order_by(FacilityVerification.checked_on.desc()).all()
    return {"items": [
        {"checked_on": r.checked_on, "checked_by": r.checked_by, "method": r.method,
         "outcome": r.outcome, "notes": r.notes} for r in rows
    ]}
