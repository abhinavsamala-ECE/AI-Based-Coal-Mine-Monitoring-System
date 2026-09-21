"""Generate realistic synthetic mine-safety observations for the prototype ML model.

This is explicitly synthetic demonstration data. It is not a substitute for validated
mine telemetry or regulatory safety limits.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = [
    "methane", "co", "temperature", "humidity", "dust", "vibration", "noise",
    "worker_count", "worker_hazard_distance", "ppe_violations",
    "equipment_temperature", "equipment_overheating", "equipment_health",
    "slope_stability", "wind_speed", "rainfall", "visibility",
]
LABEL = "risk_class"


def _risk_latent(df: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    # A noisy nonlinear synthetic process. The model must learn interactions,
    # rather than copying a single threshold table.
    m = df.methane.to_numpy()
    co = df.co.to_numpy()
    temp = df.temperature.to_numpy()
    humidity = df.humidity.to_numpy()
    dust = df.dust.to_numpy()
    vib = df.vibration.to_numpy()
    noise = df.noise.to_numpy()
    workers = df.worker_count.to_numpy()
    dist = df.worker_hazard_distance.to_numpy()
    ppe = df.ppe_violations.to_numpy()
    eqt = df.equipment_temperature.to_numpy()
    overheat = df.equipment_overheating.to_numpy()
    health = df.equipment_health.to_numpy()
    slope = df.slope_stability.to_numpy()
    wind = df.wind_speed.to_numpy()
    rain = df.rainfall.to_numpy()
    visibility = df.visibility.to_numpy()

    # Normalize into broad risk contributions, then add interactions.
    r = (
        11.0 * np.clip(m / 3.2, 0, 1.4)
        + 7.0 * np.clip(co / 45.0, 0, 1.4)
        + 10.0 * np.clip((temp - 25) / 70.0, 0, 1.4)
        + 2.5 * np.clip(humidity / 100.0, 0, 1)
        + 8.0 * np.clip(dust / 240.0, 0, 1.4)
        + 8.0 * np.clip(vib / 10.0, 0, 1.4)
        + 5.0 * np.clip(noise / 115.0, 0, 1.3)
        + 5.0 * np.clip(workers / 80.0, 0, 1.5)
        + 12.0 * np.clip(1.0 - dist / 80.0, 0, 1)
        + 6.0 * np.clip(ppe / 8.0, 0, 1)
        + 8.0 * np.clip((eqt - 45) / 65.0, 0, 1.4)
        + 8.0 * overheat
        + 7.0 * np.clip(1.0 - health / 100.0, 0, 1)
        + 12.0 * np.clip(1.0 - slope / 100.0, 0, 1)
        + 3.0 * np.clip((rain - 5) / 35.0, 0, 1)
        + 7.0 * np.clip(1.0 - visibility / 12.0, 0, 1)
        - 2.5 * np.clip(wind / 35.0, 0, 1)
    )

    # Interactions: combined hazards are materially more important than isolated ones.
    r += 10.0 * np.clip(m / 2.2, 0, 1.5) * np.clip((1.0 - slope / 100.0), 0, 1)
    r += 8.0 * np.clip(dust / 180.0, 0, 1.3) * np.clip(workers / 60.0, 0, 1.2)
    r += 7.0 * np.clip(vib / 7.0, 0, 1.4) * np.clip(overheat, 0, 1)
    r += 7.0 * np.clip((eqt - 50) / 45.0, 0, 1.5) * np.clip(1 - health / 100, 0, 1)
    r += rng.normal(0, 4.8, len(df))
    return np.clip(r, 0, 100)


def generate(rows: int = 7000, seed: int = 26024) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Mixture of operating regimes to avoid overly clean synthetic distributions.
    regimes = rng.choice([0, 1, 2, 3, 4, 5], size=rows, p=[.48, .18, .12, .09, .08, .05])
    n = rows
    df = pd.DataFrame(index=np.arange(n))
    df["methane"] = np.clip(rng.normal(0.8 + regimes * 0.20, 0.42), 0.02, 3.8)
    df["co"] = np.clip(rng.normal(11 + regimes * 2.3, 5.2), 0.2, 55)
    df["temperature"] = np.clip(rng.normal(35 + regimes * 4.8, 7.2), 18, 98)
    df["humidity"] = np.clip(rng.normal(57 + regimes * 4.2, 11), 20, 99)
    df["dust"] = np.clip(rng.lognormal(np.log(42 + regimes * 16), .42), 3, 320)
    df["vibration"] = np.clip(rng.normal(2.3 + regimes * .85, 1.25), .05, 12)
    df["noise"] = np.clip(rng.normal(62 + regimes * 6, 10), 35, 125)
    df["worker_count"] = np.clip(rng.normal(20 + regimes * 6, 11), 0, 95).round().astype(int)
    df["worker_hazard_distance"] = np.clip(rng.normal(45 - regimes * 5, 18), 2, 120)
    df["ppe_violations"] = np.clip(rng.poisson(.55 + regimes * .35), 0, 10)
    df["equipment_temperature"] = np.clip(rng.normal(48 + regimes * 5.2, 8.5), 28, 112)
    df["equipment_overheating"] = (df.equipment_temperature + rng.normal(0, 4, n) > 84).astype(int)
    df["equipment_health"] = np.clip(rng.normal(93 - regimes * 8, 8.5), 35, 100)
    df["slope_stability"] = np.clip(rng.normal(92 - regimes * 8, 10.0), 20, 100)
    df["wind_speed"] = np.clip(rng.normal(13 - regimes * .2, 6), 0, 55)
    df["rainfall"] = np.clip(rng.gamma(shape=1.5, scale=4.5, size=n) + regimes * .45, 0, 55)
    df["visibility"] = np.clip(rng.normal(10 - regimes * .55, 2.2), .6, 15)

    latent = _risk_latent(df, rng)
    # Slight label ambiguity intentionally creates overlapping classes.
    df[LABEL] = pd.cut(
        latent,
        bins=[-1, 28, 52, 74, 101],
        labels=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    ).astype(str)
    return df[FEATURES + [LABEL]]


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    out = root / "data" / "risk_training.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df = generate()
    df.to_csv(out, index=False)
    print(f"Generated {len(df):,} rows -> {out}")
