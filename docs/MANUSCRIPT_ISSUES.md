# Manuscript issues to fix before submission

Found while building against the manuscript. Each one is checkable in your own file.

## Blocking

1. **"Data Management and Preprocessing" describes the wrong study.**
   The paragraph reads: *"...transform the collected raw **HIV datasets** into a
   structured, high-quality analytical dataset..."* and lists "mode of transmission"
   as a variable. This is pasted from a different paper. Rewrite it for diabetes
   variables, or delete it.

2. **Phase count contradicts itself.**
   "The study will be conducted in six major phases" is immediately followed by
   "The study will be conducted in seven major phases". Delete the first sentence.

3. **Title says "Forecasting"; the method cannot deliver it.**
   Forecasting future onset requires longitudinal data. The Methodology already
   concedes the point. Either secure longitudinal data or retitle. A reviewer
   will find this.

4. **Objective 1 needs rewriting for the current subject.**
   Its model inputs were written for the earlier version of the study. The
   inputs that matter now are the ones the ADA screening criteria use: age, BMI,
   ancestry, and the Table 2.5 risk factors. BMI is the one to be careful about
   — self-reported height and weight are not equivalent to measured, and the
   screening rule turns on a cut-off of 23.

5. **Check what the change of subject did to your ethics position.**
   The earlier version expected mostly minors. Screening adults from 35, and
   adults of any age at BMI 23 or above, means mostly adult respondents. That
   may change what the committee asks for. Confirm it; do not assume it.

## Citations — checked 11 November 2026

Checked by web search. "Confirmed" means a publisher's page or a bibliographic
record for that exact work was found. It does not mean the work says what your
sentence attributes to it; read each one before you cite it.

### Confirmed, with the full reference

| In your manuscript | Result |
|---|---|
| ADA Professional Practice Committee, 2026 | **Confirmed.** Section 2, *Diagnosis and Classification of Diabetes: Standards of Care in Diabetes—2026*. Diabetes Care 2026;49(Suppl 1):S27–S49. doi:10.2337/dc26-S002. Published 8 Dec 2025. |
| Waldock, Guni, Darzi, & Ashrafian (2026) | **Confirmed.** *Performance of predictive AI-based clinical decision support systems across clinical domains: A systematic review and meta-analysis.* PLOS Digital Health 5(3), March 2026. |
| Leyso & Umezaki (2024) | **Confirmed.** GeoJournal, doi:10.1007/s10708-024-11098-3. Nationwide, municipal-level, E2SFCA method, as you describe. |
| Salvacion (2022) | **Confirmed.** *Measuring Spatial Accessibility of Healthcare Facilities in Marinduque, Philippines.* ISPRS Int J Geo-Inf 2022;11(10):516. |
| Luo & Wang (2003) | **Confirmed** as a chapter in *Geographic Information Systems and Health Applications* (2003), pp. 260–278. Cite it as a book chapter, not a journal article. |

**An earlier version of this file doubted the first two.** That doubt was wrong:
both exist exactly as you cited them.

### Needs correcting

| In your manuscript | Problem | Fix |
|---|---|---|
| "Nichole S. et al. (2020)", twice | An author's first name is used as the surname | Correct the author name, and see the note below on whether to cite it at all |

### References to remove, now the subject has changed

Four of the works cited in the manuscript are about a different form of diabetes
and no longer support anything the study claims. Leaving them in a type 2
reference list is the kind of thing a panel notices:

- the presymptomatic-screening review (Bonifacio & Ziegler)
- the staging statement (Insel et al.)
- the paediatric staging consensus (Haller et al. / ISPAD)
- the insulin-dosing decision support system (the one miscited as "Nichole S.")

Replace them with the sources this build actually uses: **ADA Standards of Care
2026, Section 2** for the diagnostic cut-offs and the screening criteria
(S27–S49, doi:10.2337/dc26-S002), **Section 3** for prevention (S50–S60,
doi:10.2337/dc26-S003), and the **Diabetes Prevention Program** trial behind the
prevention figure (Knowler et al., N Engl J Med 2002;346(6):393–403,
doi:10.1056/NEJMoa012512). All three are registered in
`backend/app/data/sources.json`.

### Not checked

Katsarou et al. (2017), DiMeglio et al. (2018), Rajpurkar et al. (2022), Kelly
et al. (2019), Mao & Nekorchuk (2013), WHO (2021), IDF (2025), CDC (2024), and
ADA (2024, 2025). I did not search for these, so I can say nothing about them
either way.

## Placeholders still in the text

`ANG MODEL DRI`, `PICTURE DEI`, `(Kulangni)` — your own notes. Remove before
printing.

## Wording

- The Hypotheses section tests "no significant difference between the system's
  evaluated performance and the predefined evaluation criteria". A one-sample test
  against a fixed criterion is defensible, but state which test, which criterion
  value, and which alpha, before you collect data.
- The RRL repeatedly places the citation after the sentence's end punctuation
  ("...across different clinical domains. (Waldock et al. 2026)"). APA puts it
  inside. Mechanical, but a panel will mark it.
