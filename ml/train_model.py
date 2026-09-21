"""Train and save the synthetic-prototype mine risk classifier."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from .generate_dataset import FEATURES, generate


def train(root: Path) -> dict:
    data_path = root / "data" / "risk_training.csv"
    model_dir = root / "models"
    model_dir.mkdir(exist_ok=True)

    if not data_path.exists():
        df = generate()
        df.to_csv(data_path, index=False)
    else:
        df = pd.read_csv(data_path)
        missing = [c for c in FEATURES + ["risk_class"] if c not in df.columns]
        if missing:
            df = generate()
            df.to_csv(data_path, index=False)

    X = df[FEATURES]
    y = df["risk_class"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.22, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=360,
        max_depth=12,
        min_samples_leaf=3,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    proba = model.predict_proba(X_test)

    report = classification_report(y_test, pred, output_dict=True, zero_division=0)
    metadata = {
        "model_type": "RandomForestClassifier",
        "features": FEATURES,
        "classes": list(model.classes_),
        "rows": int(len(df)),
        "validation_accuracy": round(float(accuracy_score(y_test, pred)), 4),
        "validation_balanced_accuracy": round(float(balanced_accuracy_score(y_test, pred)), 4),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_data": True,
        "note": "Prototype model trained on synthetic observations; not a certified mine-safety model.",
        "class_report": report,
        "feature_importance": {
            feature: round(float(importance), 5)
            for feature, importance in sorted(
                zip(FEATURES, model.feature_importances_), key=lambda x: x[1], reverse=True
            )
        },
    }
    joblib.dump(model, model_dir / "risk_model.joblib")
    (model_dir / "model_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    meta = train(root)
    print(json.dumps(meta, indent=2))
