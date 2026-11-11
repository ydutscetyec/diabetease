"""The inference layer must never serve a prediction from an inactive artifact."""
from __future__ import annotations
import json
from pathlib import Path

import pytest

# These tests exercise artifact loading, which needs the optional ML stack.
# Skip cleanly when only requirements.txt is installed.
joblib = pytest.importorskip("joblib", reason="install requirements-ml.txt")
DummyClassifier = pytest.importorskip(
    "sklearn.dummy", reason="install requirements-ml.txt").DummyClassifier

from app.services import inference


def _write_artifact(tmp_path: Path, *, is_active: bool, with_meta: bool = True) -> Path:
    clf = DummyClassifier(strategy="constant", constant=1).fit([[0], [1]], [1, 1])
    artifact = tmp_path / "model.joblib"
    joblib.dump(clf, artifact)
    if with_meta:
        artifact.with_suffix(".meta.json").write_text(json.dumps({
            "version": "test-1", "is_active": is_active,
            "prediction_task": "test", "calibration_assessed": False}))
    return artifact


def test_missing_artifact_reports_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "nope.joblib"))
    inference.get_settings.cache_clear()
    inference.load_model(force=True)
    assert inference.status()["available"] is False
    assert inference.predict({"age": 10}) is None


def test_artifact_without_metadata_is_not_loaded(monkeypatch, tmp_path):
    artifact = _write_artifact(tmp_path, is_active=True, with_meta=False)
    monkeypatch.setenv("MODEL_PATH", str(artifact))
    inference.get_settings.cache_clear()
    inference.load_model(force=True)
    assert inference.status()["available"] is False


def test_inactive_artifact_is_not_loaded(monkeypatch, tmp_path):
    artifact = _write_artifact(tmp_path, is_active=False)
    monkeypatch.setenv("MODEL_PATH", str(artifact))
    inference.get_settings.cache_clear()
    inference.load_model(force=True)
    assert inference.status()["available"] is False
    assert inference.predict({"age": 10}) is None


def test_synthetic_training_run_produces_an_inactive_artifact():
    meta = Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "model.meta.json"
    if not meta.exists():
        pytest.skip("run ml/make_synthetic.py and ml/train.py first")
    data = json.loads(meta.read_text())
    assert data["dataset_is_synthetic"] is True
    assert data["is_active"] is False
