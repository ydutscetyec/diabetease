# Verification call sheet

38 candidate facilities are loaded, all **unconfirmed**. Google confirms a
facility exists and where it is. It does not say which tests it runs, so zero
service claims are recorded. That is the gap your phone calls close.

## What to ask

> "Good morning, I'm a senior high school researcher from Libertad National High
> School in Surallah. We're mapping where people can get tested for diabetes.
> May I ask three questions?
> 1. Do you offer fasting blood sugar testing?
> 2. Do you offer HbA1c?
> 3. Is a doctor's referral needed, and roughly what does it cost?"

Record the answer, the date, and who you spoke to. That is your `source`.

## Call these first

Highest chance of running the tests, so the best use of your first hour:

| Facility | Municipality | Number |
|---|---|---|
| Health Hub Laboratory & Medical Clinic | Surallah | +63 975 711 0248 |
| SOCCSKSARGEN General Hospital | Surallah | +63 83 238 5507 |
| Landero Clinic and Hospital | Surallah | +63 83 238 3187 |
| Norala District Hospital | Norala | +63 83 238 7611 |
| Howard Hubbard Memorial Hospital | Polomolok | +63 83 500 2183 |
| Heramil Hospital | Polomolok | +63 83 500 9247 |
| Adventist Hospital Tupi | Tupi | +63 83 822 0010 |
| Tampakan General Hospital | Tampakan | +63 83 878 0699 |
| Moorehouse Mission Hospital | T'boli | +63 83 237 1122 |
| Clinica Luntao, Inc. | Sto. Nino | +63 977 777 4366 |
| Rural Health Unit - T'boli | T'boli | +63 83 237 1010 |
| Municipal Health Office of Norala | Norala | +63 83 234 1303 |

Twelve of the 38 records have no phone number at all. Ask at the municipal hall.

## Data problems to resolve on the ground

These came out of the search and should be checked before the map is presented:

1. **Dagang Municipal Hospital and Moorehouse Mission Hospital (T'boli)** sit at
   coordinates 2 metres apart. Either they are the same site under two names, or
   one pin is wrong. Resolve before mapping both.
2. **Dr. Francisco C. Parcon Clinic (Banga)** — a public review states the pin
   location is wrong. Get the coordinates on site.
3. **Banga Super Health Center** — coordinates fall roughly 10 km south-east of
   Banga poblacion. Verify it is in Banga at all.
4. **Ned 1 Super Health Center (Lake Sebu)** — Barangay Ned is about 28 km west
   of the poblacion. Confirm it is inside the municipality.
5. **Birthing homes and maternity clinics** (Precious Moment, St. Monique,
   Tboli Birthing Home) are almost certainly not diabetes testing sites. Confirm
   and mark them `closed` or leave them with no services rather than deleting —
   "we checked and it does not offer this" is a finding.

## Recording the result

Verified, by phone:

```powershell
python import_facilities.py your_verified_file.csv --commit
```

with `services_confirmed`, `source` and `verified_on` filled. Or use the
verification endpoint to log a recheck on an existing record, which updates its
status and keeps the history:

```
POST /api/v1/facilities/{id}/verifications
{"checked_on":"2026-11-04","checked_by":"Rol","method":"phone_call","outcome":"confirmed"}
```

Outcomes: `confirmed`, `changed`, `unreachable`, `closed`. Unreachable numbers
are worth reporting in your results section, not hiding.
