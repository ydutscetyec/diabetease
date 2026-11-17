"""Score an exported logistic regression without scikit-learn.

The runtime here is pure-Python wheels only, by deliberate choice: scikit-learn
and pandas are in requirements-ml.txt and are not installed on the server. A
pickled sklearn pipeline would therefore load nowhere except a developer's
machine, and the model registry would be reporting a model that could not
actually score anything.

A logistic regression needs none of that at inference time. It is a
standardisation, a one-hot expansion and a dot product, which is what this does.
`backend/ml/train_cohort.py` writes the numbers; a test asserts that this scorer
reproduces scikit-learn's own output on every row of the cohort, to 1e-9.

This module deliberately does NOT decide who may call it, and it is not wired
into the assessment. See inference.predict for the probability rule and
routers/admin.py for the access rule.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

def model_file() -> Path:
    """The configured artifact path, with a .json suffix.

    Deliberately derived from settings.model_path rather than a path of its own.
    test_model_interlock.py points MODEL_PATH at a refused artifact and asserts
    that nothing serves; a second model at a fixed location of its own would
    quietly defeat that, which is how the first version of this broke three
    interlock tests. One configured location, one gate.
    """
    from ..config import get_settings
    return Path(get_settings().model_path).with_suffix(".json")

_cache: dict[str, Any] = {"loaded": False, "model": None}


def load(force: bool = False) -> dict[str, Any] | None:
    if _cache["loaded"] and not force:
        return _cache["model"]
    _cache.update(loaded=True, model=None)
    path = model_file()
    if not path.exists():
        return None
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # An artifact missing any of these is not scoreable; refuse it rather than
    # scoring with defaults and reporting a number that means nothing.
    required = {"kind", "version", "numeric", "categorical", "coefficients", "intercept"}
    if not required <= set(model) or model["kind"] != "logistic_regression":
        return None
    # The same activation gate the pickled path uses. An artifact that does not
    # declare itself active does not serve, whatever else it contains.
    if not model.get("is_active"):
        return None
    width = len(model["numeric"]) + sum(len(c["levels"]) for c in model["categorical"])
    if width != len(model["coefficients"]):
        return None
    _cache["model"] = model
    return model


def feature_names() -> list[str]:
    model = load()
    if not model:
        return []
    return ([s["name"] for s in model["numeric"]]
            + [s["name"] for s in model["categorical"]])


def score(features: dict[str, Any]) -> dict[str, Any] | None:
    """The linear predictor, the probability, and the class.

    A feature the caller did not supply, or a categorical level the model never
    saw, contributes nothing -- which is exactly what scikit-learn's
    `handle_unknown="ignore"` does, and is why the parity test passes.
    """
    model = load()
    if not model:
        return None

    z = float(model["intercept"])
    i = 0
    missing: list[str] = []
    unseen: list[str] = []

    for spec in model["numeric"]:
        raw = features.get(spec["name"])
        if raw is None:
            missing.append(spec["name"])
        else:
            try:
                z += model["coefficients"][i] * (
                    (float(raw) - spec["mean"]) / spec["scale"])
            except (TypeError, ValueError):
                missing.append(spec["name"])
        i += 1

    for spec in model["categorical"]:
        raw = features.get(spec["name"])
        if raw is None:
            missing.append(spec["name"])
        else:
            text = str(raw)
            if text in spec["levels"]:
                z += model["coefficients"][i + spec["levels"].index(text)]
            else:
                unseen.append(f"{spec['name']}={text}")
        i += len(spec["levels"])

    probability = 1.0 / (1.0 + math.exp(-z)) if -700 < z < 700 else (0.0 if z < 0 else 1.0)
    threshold = float(model.get("threshold", 0.5))
    positive = probability >= threshold
    return {
        "version": model["version"],
        "linear_predictor": z,
        "probability": probability,
        "predicted_class": (model.get("positive_label", "Positive") if positive
                            else model.get("negative_label", "Negative")),
        "features_missing": missing,
        "levels_not_seen_in_training": unseen,
    }
