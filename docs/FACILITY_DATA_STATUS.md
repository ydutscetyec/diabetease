# Facility data: what is in the database and how good it is

Imported 29 Oct 2026 from `facilities_google_candidates.csv`.

| | Count |
|---|---|
| Facility records | 38 |
| Verified (source + date + ≥1 confirmed service) | 22 |
| Unconfirmed | 16 |
| Confirmed glucose testing | 22 |
| Confirmed HbA1c testing | 14 |
| Municipalities with at least one confirmed-service facility | 9 of 10 |
| Municipality with none | **Tantangan** |

## 13 service claims were downgraded on import

Rows whose only source was a directory listing (`Google Places`,
`Google Places + RHU standard`) had their service claims dropped. The facility
itself was kept, as unconfirmed.

The reason: a places listing establishes that a facility exists and where it is.
It does not establish which tests that facility runs. "RHU standard" is an
assumption that rural health units generally offer glucose testing — probably
true, not a verification. If the map asserts that Mangilala Health Center does
blood glucose and a panel member asks how you know, "it was in Google Maps" is
not an answer.

The importer now enforces this. `evidences_a_service()` rejects sources that
only locate a facility, and a test pins the behaviour.

Downgraded: Polomolok Health Center Office, Polomolok East Community Clinic,
Banga Rural Health Unit, Dr. Vargas Health Center, Banga Super Health Center,
Municipal Health Office of Norala, Municipal Health Office - Lake Sebu,
Ned 1 Super Health Center, Rural Health Unit - T'boli, Tampakan Clinic,
Maltana Health Center, Tantangan Rural Health Unit, Mangilala Health Center.

Every one is a rural health unit or municipal health office. Those are exactly
the facilities most likely to serve people who cannot afford a private hospital,
so they are worth a phone call each. Thirteen calls closes the gap, including
the Tantangan hole.

## On "Web verification"

22 rows cite web verification, often alongside a PhilHealth accreditation. That
is a legitimate documentary source **if you actually opened the page and read
the service listed**. Two points to be ready for:

1. **Record which page.** "Web verification" alone does not tell a reviewer what
   was checked. Replace it with the URL or the document name, for example
   "PhilHealth Konsulta accredited provider list, accessed 2026-10-29".
2. **PhilHealth accreditation implies a benefit package, not a confirmed test on
   site.** Konsulta providers are expected to deliver certain laboratory tests.
   That is a stronger basis than a map pin, and weaker than someone at the desk
   telling you the machine works. Say which one you have.

## Suggested wording for the manuscript

> Facility records were compiled from publicly available directories and
> institutional listings and were classified by evidence type. Of 38 identified
> facilities, 22 had at least one diabetes testing service supported by a
> documentary source and were recorded as verified; 16 were retained as
> unconfirmed pending direct confirmation. Service availability for rural health
> units could not be established from available documentation and was not
> claimed.

That is defensible and does not overstate what you did.


## Update, 11 Nov 2026

Three Sto. Niño facilities were added from a follow-up places search:
ZMK Doctors Clinic & Hospital, St. Jude Clinic & Hospital, and Maglaya Medical
Center (`backend/facilities_sto_nino_additions.csv`). All three are unconfirmed.
Maglaya Medical Center's pin sits about 60 m from St. Jude's; confirm on the
ground that they are separate facilities.

Totals are now 41 testing centres, 22 with a confirmed service. The same search
found no additional pharmacy in Norala, Lake Sebu or Sto. Niño and no additional
clinic or laboratory in Tantangan.
