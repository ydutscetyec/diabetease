# What was verified, and how

Checked by web search on 11 November 2026. The machine-readable version is
`backend/app/data/sources.json`, served at `/api/v1/sources` and shown on the
Educational resources page.

## Clinical content

| Claim in the system | Source | How checked |
|---|---|---|
| Diabetes: A1C 6.5% or above, fasting glucose 126 mg/dL or above, random glucose with classic symptoms. Prediabetes: A1C 5.7–6.4%, fasting 100–125 mg/dL. Confirm with a second test | ADA Standards of Care 2026, Section 2 | Bibliographic record and text excerpts seen. The full article page refused automated access |
| Low glucose: level 1 below 70 and at or above 54 mg/dL; level 2 below 54 | ADA Standards of Care, Section 6; ADA clinician handout | ADA's own handout seen |
| Stages 1, 2 and 3 of early type 1 diabetes; single-antibody and multiple-antibody progression | ISPAD Guidelines 2024 (Haller et al.) | Publisher's page seen |
| About 1 in 300 generally and 1 in 20 with an affected relative; about 85% have no family history | Endotext; NIDDK *Diabetes in America* | Publisher's pages seen |
| DKA warning signs; that it can be the first sign of diabetes | CDC | CDC page seen |
| PhilHealth's primary care package lists FBS, OGTT and HbA1c | PhilHealth Circular 2024-0013, Annex B | PhilHealth document seen |

## What the checking changed

Verification was not a formality. Five statements in the system were wrong or
incomplete and have been corrected:

1. **Stage 3 was described as "symptomatic disease."** The current ISPAD
   guideline says stage 3 means meeting the diagnostic criteria and can occur
   without symptoms.
2. **The family-risk figures were stated as universal.** They come from US
   studies of young people. The system now says so, and says no Philippine
   figure exists.
3. **DKA was said to "develop within hours."** The CDC describes a slower onset
   followed by severe symptoms that can appear quickly. Reworded.
4. **A single autoantibody was waved off as "not a diagnosis."** True, but the
   guideline gives a number: roughly a 15% chance of clinical diabetes within
   15 years in children. The system now states it.
5. **Low-glucose levels were presented as general thresholds.** The ADA defines
   them for people with diabetes. They are now labelled as a reference band.

## Facility data

- **SOCCSKSARGEN General Hospital, Surallah** is a DOH hospital established by
  Republic Act No. 11102 (2018), located at Crossing Curva, Barangay Dajay.
  That is the one facility checked against a government source.
- **PhilHealth accreditation** does support access to glucose and HbA1c testing,
  as nine of your records assume. But a provider without its own laboratory
  refers the test to a partner. So "confirmed through PhilHealth" means the test
  is available through that provider, not necessarily performed there. Facility
  cards now say this.
- **The DOH National Health Facility Registry** is the official master list and
  is published at `nhfr.doh.gov.ph`. I located it but did not check your 41
  facilities against it one by one. That remains to be done.
- **Leyso and Umezaki** obtained facility coordinates and bed counts from the
  DOH's Knowledge Management and Information Technology Service. A request
  letter from your school to that office is a legitimate route to official data.

## Not verified

- No pharmacy's stock.
- No facility's service list, other than through your own CSV.
- Whether each source says what a given sentence attributes to it, beyond the
  claims listed above.
- Anything about the Philippines' own type 1 diabetes incidence. I found no
  figure and the system claims none.
