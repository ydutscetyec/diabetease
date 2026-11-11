"""Model loading and inference.

Contract: if no active artifact exists, every call returns an explicit
unavailable status. There is no fallback path that invents a prediction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import get_settings

_cache: dict[str, Any] = {"loaded": False, "pipeline": None, "meta": None}

UNAVAILABLE_DETAIL = (
    "No predictive model is loaded, so no probability is produced. The result is "
    "derived from published diagnostic thresholds."
)


def _meta_path(artifact: Path) -> Path:
    return artifact.with_suffix(".meta.json")


def load_model(force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    if _cache["loaded"] and not force:
        return _cache
    artifact = Path(settings.model_path)
    _cache.update(loaded=True, pipeline=None, meta=None)
    if not artifact.exists():
        return _cache
    meta_file = _meta_path(artifact)
    if not meta_file.exists():
        # An artifact without provenance metadata is not loadable by policy.
        return _cache
    meta = json.loads(meta_file.read_text())
    if not meta.get("is_active"):
        return _cache
    try:
        import joblib
        _cache["pipeline"] = joblib.load(artifact)
        _cache["meta"] = meta
    except Exception:
        _cache["pipeline"] = None
        _cache["meta"] = None
    return _cache


def status() -> dict[str, Any]:
    cache = load_model()
    if cache["pipeline"] is None:
        return {
            "available": False,
            "status": "unavailable",
            "version": None,
            "prediction_task": None,
            "detail": UNAVAILABLE_DETAIL,
        }
    meta = cache["meta"] or {}
    return {
        "available": True,
        "status": "loaded",
        "version": meta.get("version"),
        "prediction_task": meta.get("prediction_task"),
        "detail": meta.get("limitations", "See the model registry for limitations."),
    }


def predict(features: dict[str, Any]) -> dict[str, Any] | None:
    """Return a prediction dict, or None when no model is available."""
    cache = load_model()
    if cache["pipeline"] is None:
        return None
    import pandas as pd
    frame = pd.DataFrame([features])
    pipeline = cache["pipeline"]
    out: dict[str, Any] = {"predicted_class": str(pipeline.predict(frame)[0])}
    meta = cache["meta"] or {}
    # A probability is returned only when the model produces one AND the metadata
    # records that calibration was assessed. Otherwise the number is not reportable.
    if hasattr(pipeline, "predict_proba") and meta.get("calibration_assessed"):
        out["probability"] = float(pipeline.predict_proba(frame)[0].max())
    out["version"] = meta.get("version")
    out["prediction_task"] = meta.get("prediction_task")
    return out
