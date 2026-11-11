# Collecting the testing-centre data

The paper specifies *where* facility data comes from. It does not contain the
data. This is the step that turns the empty map into a working one.

## What the paper commits you to

> "facility information will be gathered from official government directories,
> healthcare facility listings, institutional websites, and other reliable
> sources... cross-checked against available official records or direct
> confirmation from the facility when feasible."

So each record needs a **source** and a **date checked**. That is your own
methodology, and the software enforces it.

## Where to look, in order

1. **DOH National Health Facility Registry** — the authoritative list of
   licensed hospitals, RHUs, infirmaries and clinics, searchable by province.
   Gives you names and addresses; rarely gives you which tests are offered.
2. **Provincial Health Office, South Cotabato** — a request letter from your
   school usually gets a facility list faster than compiling it yourself.
3. **Each Municipal Health Office** — the only reliable way to learn whether an
   RHU actually runs glucose or HbA1c testing, and at what cost.
4. **PhilHealth accredited facility search** — useful cross-check for which
   facilities are operating.
5. **Phone calls** — for service availability, nothing else works. Ask:
   "Do you offer fasting blood sugar? HbA1c? Is a referral needed?"

I cannot browse, so I cannot confirm any facility exists, and I will not put a
name or a phone number on a health map from memory. A wrong number on a diabetes
testing map sends a sick person to the wrong place.

## What to record per facility

| Column | Notes |
|---|---|
| `name` | Official name as the registry spells it |
| `facility_type` | Hospital, Rural health unit, Diagnostic laboratory, Clinic |
| `municipality` | One of the ten, spelled as in the system (`Sto. Nino`, `T'boli`) |
| `address` | Barangay and purok if you have them |
| `latitude`, `longitude` | Decimal degrees. Read them off the facility pin in Google Maps, not the town centre |
| `contact` | Landline or mobile as given to you |
| `services_confirmed` | Comma-separated: `glucose`, `hba1c`, `ogtt`, `autoantibody`, `consultation`. **Only what you actually confirmed** |
| `source` | "phone call to records office", "DOH registry", "site visit" |
| `verified_on` | YYYY-MM-DD, the day you checked |
| `notes` | Anything that affects access: hours, referral needed, cost |

Leave `services_confirmed` empty when you have the facility but not its service
list. That record still imports, as unconfirmed, and it still helps.

## Importing

```powershell
cd backend
python import_facilities.py facilities_template.csv            # dry run
python import_facilities.py facilities_template.csv --commit   # write
```

The dry run reports what would happen and writes nothing. The importer applies
the same evidence rules as the web form, so a spreadsheet cannot introduce a
claim the API would have rejected:

* a row listing services without a source and a date is **refused**
* a municipality outside the ten is **refused**
* coordinates outside the study's bounding box are **refused**, which catches
  transposed latitude/longitude
* an unknown service code is **refused**
* duplicates of an existing name in the same municipality are skipped
* `status` is derived, never read from the file — verified requires a source,
  a date, and at least one confirmed service

Bad rows are reported by line number and skipped; the good rows still import.

## Expected effort

Ten municipalities, roughly 2 to 6 facilities each. Names and addresses from the
registry: an afternoon. Service availability by phone: the slow part, budget a
week of calls, and expect some numbers to be wrong or unanswered. Log those as
`unreachable` through the verification endpoint rather than deleting them —
"we called and could not reach them" is a finding worth reporting.
