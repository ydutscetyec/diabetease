# DiabetEASE

Type 1 diabetes risk information, testing-centre and pharmacy mapping, and
decision support for ten municipalities of South Cotabato: Surallah, Sto. Niño,
Lake Sebu, Norala, T'boli, Banga, Tampakan, Tantangan, Tupi and Polomolok.

Senior high school research project, Libertad National High School, Surallah.
Not clinically validated. No institution endorses it.

## Run it

```powershell
cd backend
pip install -r requirements.txt
python setup_env.py                 # once: creates .env, SECRET_KEY, your admin account
python seed.py                      # tables + the ten municipalities
python import_facilities.py facilities_google_candidates.csv --commit
python import_facilities.py facilities_sto_nino_additions.csv --commit
python import_facilities.py pharmacies_google_candidates.csv --commit
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000. API reference at `/api/docs`.

Every command runs from `backend`. `ModuleNotFoundError: No module named 'app'`
means you are one folder too high.

## What it does, and what it is based on

| Part | What happens | Based on |
|---|---|---|
| Assessment | Five steps. Entries are checked against diagnostic thresholds and a next step is returned | ADA glucose and HbA1c cut-offs; ISPAD staging; ADA hypoglycaemia levels |
| Result | The reasoning, your values on a minimum / normal / maximum scale, and the nearest testing centres for your municipality | The same thresholds; the facility database |
| Map | 41 testing centres and 17 pharmacies. Pin shape and glyph carry the verified/unconfirmed status, not colour alone | Your verified CSV; Google Places listings |
| Candie | Answers 31 reviewed topics, looks up facilities by municipality, and with a local model can converse freely | Reviewed corpus; the facility database; optionally Ollama |
| Education | Reference cards, an eight-question quiz, myth-and-fact cards | ADA, ISPAD, CDC |
| User guide | How to read each result tier, the map pin colours, and what the system cannot do | — |
| Accounts | Patient, researcher, admin. Roles are enforced on the server | — |

**It produces no probability and no risk score.** No model is trained, because
no dataset labelling Type 1 diabetes specifically has been secured. The result
is a rule check against published thresholds and says so on screen.

## Data status

| | |
|---|---|
| Testing centres on record | 41 |
| With at least one confirmed service | 22 |
| Municipalities with a confirmed testing centre | 9 of 10 — **Tantangan has none** |
| Pharmacies on record | 17, in 7 municipalities |
| Pharmacies confirmed to stock insulin | **0** |
| Municipalities with no pharmacy found | Norala, Lake Sebu, Sto. Niño |

A listing proves a facility exists. It does not prove what it offers. Records
whose only source is a listing are imported as unconfirmed, and the importer
refuses a service claim that cites one. `docs/CALL_SHEET.md` and
`docs/PHARMACIES.md` list who to call and what to ask.

## Candie

Order of checks, which is the safety property:

```
emergency → refusal → facility lookup → reviewed answer → generated answer → decline
```

- **Emergency** wording returns emergency guidance and nothing else.
- **Dosing, medication and diagnosis** requests are refused.
- **"Where can I get tested in Surallah"** is answered from the facility table.
  A service is named only if it was confirmed; unconfirmed facilities are listed
  as unconfirmed, never dropped and never promoted.
- **Reviewed topics** are answered from `app/data/faq.json`.
- **Anything else** needs a language model. Install Ollama, run
  `ollama pull llama3.2`, reload the page; it is detected automatically.
  Generated medical answers are labelled as unreviewed. Set
  `CLINICAL_OPEN_ANSWERS=false` in `.env` to restrict Candie to reviewed text.

The first answer after Ollama starts can take up to a minute while the model
loads. **Settings → Assistant → Test the model** times it and says what to do.

## First run

A four-step introduction appears once, after the loading screen. It exists to
set expectations before someone forms the wrong one: step two says plainly that
the system does not diagnose and produces no score, and step three that nothing
is stored. It asks for one thing, a municipality, which pre-selects the map and
assessment dropdowns and is kept on the device with the theme and text-size
settings.

It is skippable, and skipping counts as a decision: it does not return. The
user guide has a **Replay the introduction** button. It does not appear when a
link points at a specific page.

## Interface

The visual language follows a design reference supplied for the project:
breadcrumbs, eyebrow labels above page titles, a welcome card, tone-tinted stat
tiles, a reassurance aside on the assessment, and a result alert with an urgency
badge. The reference itself was a Next.js/Tailwind mockup with placeholder data;
only its look was taken. `tests/test_frontend_integrity.py` asserts that no
framework, no placeholder value and no new colour came with it.

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q            # 175 tests (172 without the optional ML packages)
python ..\docs\e2e_smoke.py          # against a running server
```

Covered: every threshold and its boundaries, emergency precedence, input
validation, role enforcement, the evidence rules for facility records, Candie's
routing and refusals, and the page markup itself — `test_frontend_integrity.py`
fails if the script references an element the page no longer has.

Not covered: nothing here renders a page in a browser, so layout, colours and
responsive behaviour are checked by eye only. Live language-model calls are
tested with a stand-in, not a real model.

## Layout

```
backend/
  app/
    main.py                 app, rate limit, error handling, static frontend
    config.py               settings from .env
    models.py  schemas.py   database tables, request and response shapes
    security.py             password hashing, signed tokens
    routers/                health, assessment, facilities, chatbot, auth, admin
    services/
      triage.py             the clinical rules; every threshold in one dict
      facility_lookup.py    Candie's database-backed answers
      llm.py                model detection, prompts, timeouts
      inference.py          trained-model loading and its safety interlock
    data/faq.json           the reviewed answers
  ml/                       training pipeline (needs requirements-ml.txt)
  tests/
  seed.py  setup_env.py  import_facilities.py
frontend/
  index.html  assets/app.js  assets/styles.css  assets/charts.js
docs/
```

## Before this is used for real

1. **Confirm services by phone.** 19 testing centres and all 17 pharmacies are
   unconfirmed. Tantangan has no confirmed testing centre.
2. **No trained model.** Objectives 1 and 2 of the paper cannot be reported as
   written without a Type 1 dataset. `diabetease-dataset-template.xlsx` gives
   the format.
3. **"Forecasting" in the title** needs data that follows people over time.
4. **Ethics clearance** before `STORE_ASSESSMENTS` is switched on. Most
   respondents will be minors.
5. **Sources.** The clinical thresholds were checked on 11 November 2026 against
   the ADA Standards of Care 2026, the ISPAD 2024 guideline, the CDC and
   PhilHealth; five statements were corrected as a result. See
   `docs/VERIFIED_SOURCES.md`. Facilities have not been checked against the DOH
   registry one by one.
6. **Deployment.** Not deployed. On a host with a temporary disk, use Postgres
   via `DATABASE_URL` or facility records are lost on redeploy.

Further detail: `docs/VERIFIED_SOURCES.md`, `docs/API.md`, `docs/CHATBOT_FREE_CONVERSATION.md`,
`docs/FACILITY_DATA_STATUS.md`, `docs/MANUSCRIPT_ISSUES.md`.
