"""Runtime wrapper around the trained ML model."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .generate_dataset import FEATURES
from .train_model import train

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "risk_model.joblib"
META_PATH = ROOT / "models" / "model_metadata.json"


def ensure_model() -> None:
    if not MODEL_PATH.exists() or not META_PATH.exists():
        train(ROOT)


def load_model():
    ensure_model()
    return joblib.load(MODEL_PATH)


def metadata() -> dict:
    ensure_model()
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def predict(features: dict) -> dict:
    model = load_model()
    row = {name: float(features.get(name, 0)) for name in FEATURES}
    frame = pd.DataFrame([row], columns=FEATURES)
    probs = model.predict_proba(frame)[0]
    pairs = sorted(zip(model.classes_, probs), key=lambda x: x[1], reverse=True)
    label = pairs[0][0]
    probability = float(pairs[0][1])

    # A transparent, local explanation: rank feature values by learned global importance
    # multiplied by normalized activation for this observation.
    meta = metadata()
    importances = meta.get("feature_importance", {})
    ranges = {
        "methane": (0, 3.5), "co": (0, 55), "temperature": (18, 100), "humidity": (20, 100),
        "dust": (0, 300), "vibration": (0, 12), "noise": (35, 120), "worker_count": (0, 90),
        "worker_hazard_distance": (0, 100), "ppe_violations": (0, 10), "equipment_temperature": (30, 110),
        "equipment_overheating": (0, 1), "equipment_health": (30, 100), "slope_stability": (20, 100),
        "wind_speed": (0, 50), "rainfall": (0, 50), "visibility": (0.5, 15),
    }
    activations = []
    for name in FEATURES:
        lo, hi = ranges[name]
        val = float(row[name])
        norm = np.clip((val - lo) / max(hi - lo, 1e-9), 0, 1)
        if name in {"worker_hazard_distance", "equipment_health", "slope_stability", "visibility"}:
            norm = 1 - norm
        activations.append((name, float(importances.get(name, 0)) * float(norm)))
    top_factors = [
        {"feature": name, "impact": round(score / max(sum(v for _, v in activations), 1e-9) * 100, 1)}
        for name, score in sorted(activations, key=lambda x: x[1], reverse=True)[:5]
    ]

    severity_score = {"LOW": 12, "MEDIUM": 38, "HIGH": 68, "CRITICAL": 92}
    risk_score = sum(float(p) * severity_score[str(k)] for k, p in pairs)

    return {
        "risk": label,
        "probability": round(probability, 4),
        "confidence": round(probability * 100, 1),
        "risk_score": round(float(risk_score), 1),
        "distribution": {str(k): round(float(v), 4) for k, v in pairs},
        "top_factors": top_factors,
        "model_type": meta["model_type"],
    }
