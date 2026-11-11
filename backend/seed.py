"""Create tables and seed the ten municipalities. Seeds NO facilities.

Centroids are approximate, used only to frame the map. They are not facility
coordinates and are flagged as approximate in the database and the API.
"""
from __future__ import annotations
import sys
from app.database import Base, SessionLocal, engine
from app.models import AdminUser, Municipality
from app.security import hash_password

MUNICIPALITIES = [
    ("Surallah", 6.374, 124.747), ("Banga", 6.422, 124.779), ("Norala", 6.526, 124.659),
    ("Sto. Nino", 6.444, 124.620), ("Lake Sebu", 6.223, 124.705), ("T'boli", 6.282, 124.813),
    ("Tampakan", 6.473, 124.934), ("Tantangan", 6.565, 124.766), ("Tupi", 6.332, 124.950),
    ("Polomolok", 6.217, 125.063),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    added = 0
    for name, lat, lon in MUNICIPALITIES:
        if not db.query(Municipality).filter(Municipality.name == name).one_or_none():
            db.add(Municipality(name=name, centroid_lat=lat, centroid_lon=lon,
                                centroid_is_approximate=True))
            added += 1
    db.commit()
    print(f"municipalities: {added} added, {db.query(Municipality).count()} total")
    print("facilities: 0 seeded by design; add them through POST /api/v1/facilities "
          "once each one is verified")

    if "--seed-rhu-candidates" in sys.argv:
        # Every Philippine municipality operates a Rural Health Unit under the
        # Local Government Code of 1991. That structural fact is defensible; the
        # unit's exact name, address, contact number and service list are NOT,
        # so each record is created unconfirmed with no coordinates and no phone
        # number, purely as a fieldwork worklist. Nothing here claims a service.
        from app.models import Facility
        added = 0
        for name, _lat, _lon in MUNICIPALITIES:
            label = f"Rural Health Unit / Municipal Health Office – {name}"
            if db.query(Facility).filter(Facility.name == label).one_or_none():
                continue
            muni = db.query(Municipality).filter(Municipality.name == name).one()
            db.add(Facility(
                name=label, facility_type="Rural health unit",
                municipality_id=muni.id, status="unconfirmed",
                notes=("Candidate record only. Every municipality operates an RHU under "
                       "the Local Government Code, but this entry has NOT been verified: "
                       "confirm the official name, address, coordinates, contact number "
                       "and which diabetes tests are actually offered, then record the "
                       "source and date."),
            ))
            added += 1
        db.commit()
        print(f"RHU candidate records: {added} added, all unconfirmed with no services claimed")

    if len(sys.argv) >= 3 and sys.argv[1] == "--create-admin":
        username = sys.argv[2]
        password = input("password for %s: " % username)
        if len(password) < 12:
            raise SystemExit("use at least 12 characters")
        db.add(AdminUser(username=username, password_hash=hash_password(password)))
        db.commit()
        print(f"admin user '{username}' created")
    db.close()


if __name__ == "__main__":
    main()
