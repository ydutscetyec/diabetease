# Pharmacies

17 pharmacies, found by a places search on 5 Nov 2026, across 7 of the 10
municipalities. File: `backend/pharmacies_google_candidates.csv`.

```powershell
python import_facilities.py pharmacies_google_candidates.csv --commit
```

| Municipality | Pharmacies |
|---|---|
| Surallah | 7 |
| Polomolok | 5 |
| Banga, Tupi, T'boli, Tampakan, Tantangan | 1 each |
| Norala, Lake Sebu, Sto. Niño | **none found** |

Eight results were excluded because they are outside the coverage area:
four in Koronadal, two in General Santos, one in Isulan, one in Cotabato City.

## None is confirmed to stock insulin

A places listing shows that a pharmacy exists. It does not show what is on the
shelf. Every pharmacy is therefore imported with **no confirmed medicine**, and
the map shows "Insulin — not confirmed" rather than hiding the gap.

To confirm, call and ask:

1. Do you stock insulin? Which types?
2. Do you sell glucose meters and test strips?
3. Is a prescription required? (For insulin, the answer should be yes.)

Record the answer in the CSV under `services_confirmed` as `insulin` and/or
`glucose_supplies`, with `source` (e.g. "phone call to pharmacist") and
`verified_on`. The importer rejects a claim whose source only locates the
pharmacy.

**Mercury Drug Surallah** is the best first call: the national chain is the most
likely in the area to carry insulin.

## Data notes

- **Carlee Pharmacy, Polomolok** — phone number omitted. A public review says
  the listed number belongs to someone else.
- **Gloriel Drugstore, Botica Teresa, Pharma Cure, TGP Tantangan, Reca,
  Gem Life** — no phone number listed anywhere. Ask at the municipal hall or
  visit.

## Why "every pharmacy" is not claimed

A places search returns what is listed online. Small botikas that are not on
Google Maps will be missing, and those are common in barangays. The honest
claim is "17 pharmacies identified through a places search", not "every
pharmacy in South Cotabato". A DOH or FDA licensed-drugstore list from the
provincial health office would be the authoritative source if you can get it.
