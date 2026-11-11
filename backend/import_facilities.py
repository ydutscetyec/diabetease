"""Import facility records from a CSV produced during fieldwork.

Usage:
    python import_facilities.py facilities_template.csv            # dry run
    python import_facilities.py facilities_template.csv --commit   # write

The same evidence rules the API enforces are enforced here, so a spreadsheet
cannot introduce a claim the web form would have rejected:

  * status is DERIVED, never read from the file. A record counts as verified
    only when it has a source AND a verified_on date AND at least one confirmed
    service. Everything else lands as unconfirmed.
  * a service is only marked confirmed when the row carries both a source and a
    date. "The nurse said they do HbA1c" with no date recorded is unconfirmed.
  * coordinates are validated against the study's bounding box, so a transposed
    latitude/longitude pair is caught rather than silently mapped into the sea.
  * rows that fail validation are reported and skipped; the rest still import.
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date, datetime
from pathlib import Path

from app.database import Base, SessionLocal, engine
from app.models import SERVICE_CODES, Facility, FacilityService, Municipality

# Sources that locate a facility but say nothing about which tests it runs.
# A directory listing proves a hospital exists; it does not prove the hospital
# does HbA1c. Rows citing only these keep the facility and drop the service
# claim, so the map never asserts a capability nobody checked.
NON_EVIDENCE_SOURCES = (
    "google places", "google maps", "places search", "openstreetmap",
    "rhu standard", "standard", "assumed", "typical", "usually", "likely",
    "presumed", "expected",
    # a source that describes itself as locating or as unverified cannot
    # evidence a service, however long the rest of the string is
    "location only", "listing only", "directory listing", "map listing",
    "not confirmed", "not verified", "unverified", "unconfirmed", "search",
)


def _self_negating(source: str) -> bool:
    low = source.lower()
    return any(k in low for k in ("not confirmed", "not verified", "unverified",
                                  "unconfirmed", "location only", "listing only"))


def evidences_a_service(source: str) -> bool:
    """True when the source could actually establish a service, not just a location."""
    low = (source or "").lower()
    if not low.strip():
        return False
    if _self_negating(low):
        return False
    # Strip the non-evidence parts; if anything substantive remains, accept it.
    remainder = low
    for bad in NON_EVIDENCE_SOURCES:
        remainder = remainder.replace(bad, "")
    return len(remainder.strip(" +,;-/&")) >= 4


# Generous box around the ten municipalities. Anything outside is a data error,
# not a facility in the study area.
LAT_RANGE = (6.05, 6.75)
LON_RANGE = (124.45, 125.25)

COLUMNS = [
    "name", "facility_type", "municipality", "address", "latitude", "longitude",
    "contact", "services_confirmed", "source", "verified_on", "notes",
]


# Only formats that cannot be read two ways. 04/11/2026 is 4 November in the
# Philippines and 11 April in the United States, and a spreadsheet will hand you
# either. Guessing between them silently backdates or postdates a verification,
# which is the one field a reviewer uses to judge whether a record is current.
UNAMBIGUOUS_DATE_FORMATS = (
    ("%Y-%m-%d", "2026-11-04"),
    ("%d-%b-%Y", "04-Nov-2026"),
    ("%d-%b-%y", "04-Nov-26"),
    ("%d %B %Y", "4 November 2026"),
    ("%d %b %Y", "4 Nov 2026"),
    ("%b %d, %Y", "Nov 4, 2026"),
    ("%B %d, %Y", "November 4, 2026"),
)

AMBIGUOUS_NUMERIC = re.compile(r"^\s*\d{1,2}([/.-])\d{1,2}\1\d{2,4}\s*$")


def parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None

    if AMBIGUOUS_NUMERIC.match(raw):
        raise ValueError(
            f"{raw!r} is ambiguous: a date like 04/11/2026 means 4 November here and "
            "11 April in the United States, and this importer will not guess. Write it "
            "as 2026-11-04 or 04-Nov-2026."
        )

    for fmt, _example in UNAMBIGUOUS_DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        if parsed > date.today():
            raise ValueError(
                f"{raw!r} is in the future. A verification date records when you "
                "checked, so it cannot be later than today."
            )
        if parsed.year < 2000:
            raise ValueError(f"{raw!r} parsed to {parsed.year}; check the year.")
        return parsed

    accepted = ", ".join(ex for _f, ex in UNAMBIGUOUS_DATE_FORMATS)
    raise ValueError(f"unreadable date {raw!r}. Accepted formats: {accepted}")


def parse_coord(raw: str, rng: tuple[float, float], label: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    value = float(raw)
    if not rng[0] <= value <= rng[1]:
        raise ValueError(
            f"{label} {value} is outside the study area {rng}. "
            "Check for transposed latitude and longitude."
        )
    return value


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    commit = "--commit" in sys.argv
    if not path.exists():
        raise SystemExit(f"no such file: {path}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    known = {m.name.lower(): m for m in db.query(Municipality).all()}
    if not known:
        raise SystemExit("run `python seed.py` first so the municipalities exist")

    added = skipped = verified = 0
    errors: list[str] = []
    downgraded: list[str] = []

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in ("name", "facility_type", "municipality") if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"CSV is missing required column(s): {missing}")

        for n, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            try:
                muni = known.get((row.get("municipality") or "").strip().lower())
                if muni is None:
                    raise ValueError(
                        f"'{row.get('municipality')}' is not one of the ten covered municipalities"
                    )
                lat = parse_coord(row.get("latitude", ""), LAT_RANGE, "latitude")
                lon = parse_coord(row.get("longitude", ""), LON_RANGE, "longitude")
                verified_on = parse_date(row.get("verified_on", ""))
                source = (row.get("source") or "").strip() or None

                codes = [
                    c.strip().lower()
                    for c in (row.get("services_confirmed") or "").replace(";", ",").split(",")
                    if c.strip()
                ]
                bad = [c for c in codes if c not in SERVICE_CODES]
                if bad:
                    raise ValueError(f"unknown service code(s) {bad}; allowed: {list(SERVICE_CODES)}")

                # Evidence gate, identical to the API's rule.
                has_evidence = bool(source and verified_on)
                if codes and not has_evidence:
                    raise ValueError(
                        "services were listed but the row has no source and/or verified_on date. "
                        "Record where you confirmed it and when, or leave services_confirmed empty."
                    )
                # Second gate: the source must be capable of evidencing a service.
                if codes and not evidences_a_service(source):
                    downgraded.append(
                        f"row {n} ({name}): service claim(s) {codes} dropped — "
                        f"source '{source}' locates the facility but does not establish "
                        "which tests it offers. Facility kept as unconfirmed."
                    )
                    codes = []
                    has_evidence = False

                if db.query(Facility).filter(
                    Facility.name == name, Facility.municipality_id == muni.id
                ).one_or_none():
                    errors.append(f"row {n}: '{name}' already exists in {muni.name}; skipped")
                    skipped += 1
                    continue

                status = "verified" if (codes and has_evidence) else "unconfirmed"
                facility = Facility(
                    name=name,
                    facility_type=(row.get("facility_type") or "").strip() or "Unspecified",
                    municipality_id=muni.id,
                    address=(row.get("address") or "").strip() or None,
                    latitude=lat, longitude=lon,
                    contact=(row.get("contact") or "").strip() or None,
                    source=source, verified_on=verified_on, status=status,
                    notes=(row.get("notes") or "").strip() or None,
                )
                for code in codes:
                    facility.services.append(FacilityService(
                        service_code=code, confirmed=True, source=source, verified_on=verified_on
                    ))
                db.add(facility)
                added += 1
                if status == "verified":
                    verified += 1
            except (ValueError, TypeError) as exc:
                errors.append(f"row {n} ({name or 'unnamed'}): {exc}")
                skipped += 1

    if commit:
        db.commit()
        print(f"committed: {added} record(s) added, {verified} verified, {skipped} skipped")
    else:
        db.rollback()
        print(f"DRY RUN: {added} record(s) would be added, {verified} verified, {skipped} skipped")
        print("re-run with --commit to write them")

    if downgraded:
        print(f"\n{len(downgraded)} service claim(s) downgraded to unconfirmed:")
        for d in downgraded:
            print("  " + d)
    if errors:
        print(f"\n{len(errors)} issue(s):")
        for e in errors:
            print("  " + e)
    db.close()


if __name__ == "__main__":
    main()
