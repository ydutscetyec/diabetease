"""Answer "where can I get tested / buy insulin in <municipality>" from the database.

The research paper asks the assistant to help users find testing centres. This
does that from the facility table, which means every name it gives is a record
the team entered, and every service it mentions is one that was confirmed with a
source and a date. It never fills a gap: if nothing is confirmed, it says so.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..routers.facilities import nearby_facilities

# How people actually type these names, mapped to the stored spelling.
MUNICIPALITY_ALIASES = {
    "Surallah": ("surallah",),
    "Sto. Nino": ("sto nino", "sto. nino", "santo nino", "sto niño", "santo niño", "sto. niño"),
    "Lake Sebu": ("lake sebu", "lakesebu"),
    "Norala": ("norala",),
    "T'boli": ("tboli", "t'boli", "t boli", "t’boli"),
    "Banga": ("banga",),
    "Tampakan": ("tampakan",),
    "Tantangan": ("tantangan",),
    "Tupi": ("tupi",),
    "Polomolok": ("polomolok",),
}

PHARMACY_WORDS = ("pharmacy", "pharmacies", "botika", "drugstore", "drug store",
                  "buy insulin", "where to buy", "medicine", "gamot", "tambal",
                  "test strip", "glucometer", "glucose meter")
TESTING_WORDS = ("test", "tested", "testing", "hospital", "clinic", "laborator",
                 "check up", "checkup", "hba1c", "blood sugar", "glucose",
                 "magpa", "pa check", "health center", "health centre", "rhu")

# A municipality plus a medical word is not enough: "I live in Surallah, what is
# HbA1c?" is a question about HbA1c. A lookup needs a sign the person is trying
# to LOCATE something — a locating word, or a facility noun.
LOCATE_WORDS = ("where", "find", "near", "nearest", "nearby", "closest", "list",
                "which", "any ", "is there", "are there", "available", "location",
                "saan", "asa", "diin", "diri", "malapit", "duol")
FACILITY_NOUNS = ("pharmacy", "pharmacies", "botika", "drugstore", "drug store",
                  "hospital", "clinic", "laborator", "health center", "health centre",
                  "rhu", "testing center", "testing centre")

SERVICE_NAMES = {
    "glucose": "blood glucose testing", "hba1c": "HbA1c testing",
    "ogtt": "glucose tolerance testing", "autoantibody": "islet autoantibody testing",
    "consultation": "diabetes consultation", "insulin": "insulin",
    "glucose_supplies": "glucose meters and strips",
}


def find_municipality(text: str) -> str | None:
    low = text.lower()
    for stored, aliases in MUNICIPALITY_ALIASES.items():
        for a in aliases:
            if re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", low):
                return stored
    return None


def find_kind(text: str) -> str | None:
    low = text.lower()
    if any(w in low for w in PHARMACY_WORDS):
        return "pharmacy"
    if any(w in low for w in TESTING_WORDS):
        return "testing"
    return None


def answer(db: Session, text: str) -> str | None:
    """A reply built only from stored records, or None if this is not a lookup."""
    municipality = find_municipality(text)
    kind = find_kind(text)
    if municipality is None or kind is None:
        return None
    low = text.lower()
    if not (any(w in low for w in LOCATE_WORDS) or any(w in low for w in FACILITY_NOUNS)):
        return None

    # No cap: the list is sorted confirmed-first across ALL municipalities, so a
    # small limit let confirmed facilities elsewhere crowd out local unconfirmed
    # ones, which then vanished from the answer without a word.
    out = nearby_facilities(db, municipality, kind, limit=10_000)
    if out is None:
        return None

    local = [n for n in out.items if n.same_municipality]
    noun = "pharmacies" if kind == "pharmacy" else "testing centres"

    def confirmed_services(n) -> list[str]:
        return [SERVICE_NAMES.get(s.service_code, s.service_code)
                for s in n.facility.services if s.confirmed]

    confirmed = [n for n in local if confirmed_services(n)]
    unconfirmed = [n for n in local if not confirmed_services(n)]

    if not local:
        def place(n) -> str:
            return (f"{n.facility.name} in {n.facility.municipality}"
                    + (f", about {n.distance_km} km away in a straight line"
                       if n.distance_km is not None else ""))

        msg = f"I have no {noun} on record in {municipality}."
        elsewhere = [n for n in out.items if confirmed_services(n)][:3]
        if elsewhere:
            msg += " The nearest with a confirmed service are: " + "; ".join(
                place(n) for n in elsewhere) + "."
        else:
            # Nothing confirmed anywhere: still name the nearest on record, and
            # say plainly that nobody has checked what they offer.
            nearest = sorted((n for n in out.items if n.distance_km is not None),
                             key=lambda n: n.distance_km)[:3]
            if nearest:
                what = "stock insulin" if kind == "pharmacy" else "offer diabetes testing"
                msg += (" The nearest on record, none yet confirmed to " + what + ", are: "
                        + "; ".join(place(n) for n in nearest) + ".")
        return msg + " Your municipal health office can tell you what is available locally."

    parts: list[str] = []
    if confirmed:
        parts.append(f"In {municipality}, these have a confirmed service: " + "; ".join(
            f"{n.facility.name} ({', '.join(confirmed_services(n))}"
            + (f"; {n.facility.contact}" if n.facility.contact else "") + ")"
            for n in confirmed[:5]) + ".")
    if unconfirmed:
        names = ", ".join(n.facility.name for n in unconfirmed[:5])
        more = len(unconfirmed) - 5
        what = "stock insulin" if kind == "pharmacy" else "offer diabetes testing"
        lead = "Also on record" if confirmed else f"On record in {municipality}"
        parts.append(f"{lead}, but not yet confirmed to {what}: {names}"
                     + (f", and {more} more" if more > 0 else "") + ".")
    if kind == "pharmacy":
        parts.append("Insulin needs a prescription. Call ahead to check it is in stock.")
    else:
        parts.append("Call before you go to confirm the service and whether a referral is needed.")
    parts.append("The Testing centre map shows all of them.")
    return " ".join(parts)
