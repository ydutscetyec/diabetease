# API reference

Interactive docs at `/api/docs` when the server is running. Summary:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness, database reachability, model state |
| POST | `/api/v1/assessments` | none | Triage an assessment. Returns tier, reasons, model status |
| GET | `/api/v1/assessments/thresholds` | none | The cut-offs in use, for audit |
| GET | `/api/v1/municipalities` | none | The 10 covered municipalities and approximate centroids |
| GET | `/api/v1/facilities` | none | Filter by `q`, `municipality`, `service`, `status`, `confirmed_only` |
| GET | `/api/v1/facilities/{id}` | none | One record |
| POST | `/api/v1/facilities` | bearer | Create. Status is derived from evidence, not accepted |
| POST | `/api/v1/facilities/{id}/verifications` | bearer | Log a verification; updates status |
| GET | `/api/v1/facilities/{id}/verifications` | none | Verification history |
| POST | `/api/v1/chat` | none | Retrieval over the reviewed corpus |
| GET | `/api/v1/chat/topics` | none | Topic ids |
| POST | `/api/v1/admin/login` | none | Returns an 8-hour bearer token |
| GET | `/api/v1/admin/metrics` | bearer | Facility counts, model registry, evaluation status |

## Assessment response shape

```json
{
  "tier": "urgent",
  "emergency": false,
  "headline": "See a doctor promptly",
  "explanation": "...",
  "reasons": [{"label": "Why", "text": "..."}],
  "source": "rule_based_thresholds",
  "threshold_source": "American Diabetes Association ...",
  "model": {"available": false, "status": "unavailable", "version": null,
            "prediction_task": null, "detail": "No trained model is loaded..."},
  "stored": false,
  "api_version": "v1"
}
```

There is no `probability` field and no `score` field. When a model becomes
active, a `prediction` block is added alongside the rule result; the rule result
does not disappear, because the two answer different questions.

## Error shape

```json
{"error": "validation_failed", "detail": "One or more fields were rejected.",
 "fields": [{"field": "hba1c_pct", "message": "Input should be less than or equal to 20"}]}
```

Submitted values are never echoed back.

## Seeding facility candidates

```powershell
python seed.py --seed-rhu-candidates
```

Creates one **unconfirmed** record per municipality: "Rural Health Unit /
Municipal Health Office – <name>". Every Philippine municipality operates an RHU
under the Local Government Code of 1991, so the existence of the unit is a
structural fact rather than an invention. Everything else about it is not: the
records carry no coordinates, no contact number and no claimed service, and each
one's note says what has to be confirmed before it counts.

This is a fieldwork worklist, not data. Running it does not increase your
verified count by one.
