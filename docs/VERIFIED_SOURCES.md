# What was verified, and how

Clinical content checked by web search: the diagnostic and low-glucose claims on
11 November 2026, the type 2 screening criteria and the prevention claims on
16 November 2026. The machine-readable version is
`backend/app/data/sources.json`, served at `/api/v1/sources` and shown on the
Educational resources page.

## Clinical content

| Claim in the system | Source | How checked |
|---|---|---|
| Diabetes: A1C 6.5% or above, fasting glucose 126 mg/dL or above, random glucose with classic symptoms. Prediabetes: A1C 5.7–6.4%, fasting 100–125 mg/dL. Confirm with a second test | ADA Standards of Care 2026, Section 2 | Bibliographic record and text excerpts seen. The full article page refused automated access |
| Low glucose: level 1 below 70 and at or above 54 mg/dL; level 2 below 54 | ADA Standards of Care, Section 6; ADA clinician handout | ADA's own handout seen |
| Screening: all adults from 35, repeat at least every 3 years; below 35, overweight or obesity plus one or more risk factors; BMI 25, or 23 for individuals of Asian ancestry; high-risk ancestry is itself a listed risk factor | ADA Standards of Care 2026, Section 2, Table 2.5 and recs. 2.11–2.13 | Recommendation text and Table 2.5 seen across several independent reproductions that agree; the publisher's own article page refused automated access |
| Prevention: refer adults at high risk to a programme targeting at least 5–7% weight loss; greater benefit at 7–10% | ADA Standards of Care 2026, Section 3 | Publisher's PDF excerpt and the DOI record seen |
| About 58% fewer new cases with intensive lifestyle intervention, about 31% with metformin | Diabetes Prevention Program (Knowler et al., 2002) | Bibliographic record seen; full text not read |
| 2-hour OGTT: 200 mg/dL diagnostic, 140–199 intermediate | ADA Standards of Care 2026, Section 2 | As above |
| Hyperglycaemic emergencies — ketoacidosis and the hyperosmolar state — and their warning signs | ADA Standards of Care 2026, Section 6; CDC | Section title and CDC page seen |
| PhilHealth's primary care package lists FBS, OGTT and HbA1c | PhilHealth Circular 2024-0013, Annex B | PhilHealth document seen |

## What the checking changed

Verification was not a formality. Five statements in the system were wrong or
incomplete and have been corrected:

1. **Emergency onset was said to "develop within hours."** The CDC describes a
   slower onset followed by severe symptoms that can appear quickly. Reworded.
2. **Low-glucose levels were presented as general thresholds.** The ADA defines
   them for people with diabetes. They are now labelled as a reference band.
3. **The family-history answer quoted figures from foreign studies.** No
   comparable Philippine figure was found, so the answer now quotes no number at
   all rather than borrowing one. A test enforces this.
4. **The screening BMI cut-off was the headline 25.** The guideline sets it at 23
   for people of Asian ancestry and separately lists high-risk ancestry as a
   risk factor, so both clauses apply to this study's population. Encoded at 23,
   and the system says why.
5. **Prevention was described as impossible.** That was written for a different
   form of diabetes. For type 2 the guideline recommends an actual intervention
   with an actual effect size, and the system now gives it.

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
- Any figure for diabetes prevalence or incidence in the Philippines, or in
  South Cotabato. None was found that could be cited with confidence, and the
  system claims none.
- Whether the BMI cut-off of 23, which is drawn from a guideline written for a
  US population of Asian ancestry, is the right one for this specific cohort.
  It is the published recommendation and is applied as such; a local validation
  study is a different piece of work.
