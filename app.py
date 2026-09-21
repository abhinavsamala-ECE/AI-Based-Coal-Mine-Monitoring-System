from __future__ import annotations
from services.memory import init_db, save_message, get_history
import os
import csv
import math
import random
import threading
import time
import json
import requests
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, Response, stream_with_context,render_template

from data.sample_data import (
    INITIAL_ALERTS,
    INITIAL_AUDIT_LOG,
    INITIAL_COMPLIANCE_CHECKS,
    INITIAL_ZONE_OBSERVATIONS,
    INITIAL_ZONE_STATUS,
    MINE_ZONES,
)
from ml.risk_model import metadata as model_metadata
from ml.risk_model import predict as ml_predict
from ml.risk_model import ensure_model
from ml.train_model import train

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
SENSOR_HISTORY_PATH = DATA_DIR / "sensor_history.csv"
CAMERA_HISTORY_PATH = DATA_DIR / "camera_events.csv"
INCIDENT_HISTORY_PATH = DATA_DIR / "incident_history.csv"
SEISMIC_HISTORY_PATH = DATA_DIR / "seismic_events.csv"

# ---------------------------------------------------------------------
# Prototype state. Historical telemetry is persisted to CSV so the model
# has a transparent, inspectable data trail. This is not production storage.
# ---------------------------------------------------------------------
zone_status = dict(INITIAL_ZONE_STATUS)
zone_observations = {zone: dict(values) for zone, values in INITIAL_ZONE_OBSERVATIONS.items()}
alerts = [dict(alert) for alert in INITIAL_ALERTS]
compliance_checks = [dict(item) for item in INITIAL_COMPLIANCE_CHECKS]
audit_log = [dict(entry) for entry in INITIAL_AUDIT_LOG]
alert_counter = len(alerts)
incident_counter = 0
live_tick = 0
last_zone_risk = dict(zone_status)
last_incident = None
training_rows_since_retrain = 0
last_retrain_at = None
state_lock = threading.Lock()
# ---------------------------------------------------------------------
# Seismic monitoring simulator
# Prototype-only simulated seismic state.
# This is not a validated geotechnical/seismological safety model.
# ---------------------------------------------------------------------

SEISMIC_ZONE_COORDS = {
    "North Pit": (18.0, 12.0),
    "South Pit": (-16.0, -11.0),
    "Conveyor Zone": (2.0, -3.0),
    "Processing Area": (12.0, -18.0),
    "Storage Area": (-12.0, 18.0),
}

seismic_state = {}

seismic_event_counter = 0

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
ZONES = {
    "North Pit": {"area": "1.8 km²", "depth": "145 m", "equipment": 5},
    "South Pit": {"area": "2.2 km²", "depth": "172 m", "equipment": 4},
    "Conveyor Zone": {"area": "0.9 km²", "depth": "68 m", "equipment": 3},
    "Processing Area": {"area": "1.1 km²", "depth": "52 m", "equipment": 4},
    "Storage Area": {"area": "0.7 km²", "depth": "41 m", "equipment": 2},
}


def current_time() -> str:
    return datetime.now().strftime("%H:%M:%S")


def current_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_audit_entry(event: str, detail: str) -> None:
    audit_log.insert(0, {"timestamp": current_time(), "event": event, "detail": detail})
    del audit_log[40:]


def make_new_alert_id() -> str:
    global alert_counter
    alert_counter += 1
    return f"ALERT-{alert_counter:04d}"


def make_incident_id() -> str:
    global incident_counter
    incident_counter += 1
    return f"INC-{incident_counter:04d}"


def count_alerts_by_severity():
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for alert in alerts:
        if alert["status"] != "Resolved":
            counts[alert["severity"]] += 1
    return counts


def compliance_summary():
    summary = {"Compliant": 0, "Warning": 0, "Pending": 0}
    for check in compliance_checks:
        status = check.get("status", "Pending")
        summary[status] = summary.get(status, 0) + 1
    return summary


def feature_row_from_observation(observation: dict) -> dict:
    return {
        "methane": float(observation.get("methane", 0)),
        "co": float(observation.get("co", 0)),
        "temperature": float(observation.get("temperature", 0)),
        "humidity": float(observation.get("humidity", 0)),
        "dust": float(observation.get("dust", 0)),
        "vibration": float(observation.get("vibration", 0)),
        "noise": float(observation.get("noise", 0)),
        "worker_count": float(observation.get("worker_count", 0)),
        "worker_hazard_distance": float(observation.get("worker_hazard_distance", 100)),
        "ppe_violations": float(observation.get("ppe_violations", 0)),
        "equipment_temperature": float(observation.get("equipment_temperature", 45)),
        "equipment_overheating": float(observation.get("equipment_overheating", 0)),
        "equipment_health": float(observation.get("equipment_health", 95)),
        "slope_stability": float(observation.get("slope_stability", 95)),
        "wind_speed": float(observation.get("wind_speed", 12)),
        "rainfall": float(observation.get("rainfall", 0)),
        "visibility": float(observation.get("visibility", 10)),
    }


def append_csv(path: Path, row: dict) -> None:
    # Vercel's deployed application filesystem is read-only.
    # Keep CSV persistence locally, but skip runtime file writes
    # on Vercel so live telemetry can still be returned.
    if os.getenv("VERCEL") == "1":
        return

    new_file = not path.exists()

    with path.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(row.keys()),
        )

        if new_file:
            writer.writeheader()

        writer.writerow(row)

def latent_ground_truth(observation: dict) -> float:
    """Hidden simulator outcome used to create synthetic labels.

    This is deliberately not the runtime risk logic. It is only a synthetic-world
    generator so the model can learn from noisy outcomes in the prototype.
    """
    x = feature_row_from_observation(observation)
    r = (
        16 * min(x["methane"] / 3.2, 1.3)
        + 10 * min(x["co"] / 45, 1.3)
        + 13 * min(max(x["temperature"] - 25, 0) / 70, 1.3)
        + 8 * min(x["dust"] / 250, 1.2)
        + 9 * min(x["vibration"] / 10, 1.2)
        + 8 * min(x["noise"] / 115, 1.2)
        + 5 * min(x["worker_count"] / 80, 1.3)
        + 11 * max(0, 1 - x["worker_hazard_distance"] / 75)
        + 8 * min(x["ppe_violations"] / 7, 1.1)
        + 10 * min(max(x["equipment_temperature"] - 45, 0) / 65, 1.2)
        + 7 * (1 if x["equipment_overheating"] else 0)
        + 8 * max(0, 1 - x["equipment_health"] / 100)
        + 12 * max(0, 1 - x["slope_stability"] / 100)
        + 8 * max(0, 1 - x["visibility"] / 12)
        + 5 * min(x["rainfall"] / 40, 1)
        + 3 * min(x["humidity"] / 100, 1)
    )
    r += 14 * min(x["methane"] / 2.1, 1.5) * max(0, 1 - x["slope_stability"] / 100)
    r += 10 * min(x["dust"] / 180, 1.3) * min(x["worker_count"] / 60, 1.2)
    r += 8 * min(x["vibration"] / 7, 1.2) * (1 if x["equipment_overheating"] else 0)
    return max(0, min(100, r + random.gauss(0, 4)))


def class_from_ground_truth(score: float) -> str:
    if score < 28:
        return "LOW"
    if score < 52:
        return "MEDIUM"
    if score < 74:
        return "HIGH"
    return "CRITICAL"


def update_compliance_from_observation(observation: dict) -> None:
    ppe = int(observation.get("ppe_violations", 0))
    ventilation = observation.get("ventilation_status", "good")
    equip_health = float(observation.get("equipment_health", 95))
    slope = float(observation.get("slope_stability", 95))

    for check in compliance_checks:
        name = check["check"]

        if name == "PPE inspection":
            check["status"] = "Warning" if ppe >= 3 else "Compliant"
            check["action"] = (
                "Review PPE compliance" if ppe >= 3 else "-"
            )

        elif name == "Ventilation check":
            check["status"] = (
                "Warning" if ventilation == "poor" else "Compliant"
            )
            check["action"] = (
                "Inspect ventilation" if ventilation == "poor" else "-"
            )

        elif name == "Equipment inspection":
            check["status"] = (
                "Pending" if equip_health < 75 else "Compliant"
            )
            check["action"] = (
                "Inspect equipment" if equip_health < 75 else "-"
            )

        elif name == "Safety checklist":
            check["status"] = (
                "Warning" if slope < 70 else "Compliant"
            )
            check["action"] = (
                "Inspect slope conditions" if slope < 70 else "-"
            )

        check["last_checked"] = "Just now"


# ---------------------------------------------------------------------
# Seismic simulation
# ---------------------------------------------------------------------

def _seismic_next_event_id() -> str:
    global seismic_event_counter

    seismic_event_counter += 1

    return f"SEIS-{seismic_event_counter:05d}"


def _seismic_distance_km(
    zone: str,
    event_x: float,
    event_y: float,
) -> float:
    """
    Calculate horizontal distance from the event origin to the monitored
    zone reference point.

    Coordinates are prototype mine-local coordinates.
    """

    zone_x, zone_y = SEISMIC_ZONE_COORDS.get(
        zone,
        (0.0, 0.0),
    )

    horizontal_distance = math.sqrt(
        (event_x - zone_x) ** 2
        + (event_y - zone_y) ** 2
    )

    # Convert the prototype coordinate scale into an approximate
    # local seismic distance and prevent zero-distance singularities.
    return max(0.05, horizontal_distance / 10.0)


def _seismic_pga(
    magnitude: float,
    distance_km: float,
    depth_m: float,
) -> float:
    """
    Approximate peak ground acceleration.

    This is a conceptual prototype attenuation relationship.
    It is NOT a validated mine-specific seismic hazard equation.
    """

    depth_factor = math.exp(-depth_m / 180.0)

    log10_pga = (
        -3.0
        + (0.55 * magnitude)
        - (0.90 * math.log10(distance_km + 0.10))
    )

    pga_g = (10 ** log10_pga) * depth_factor

    return round(
        max(0.001, min(0.35, pga_g)),
        4,
    )


def _seismic_ground_velocity(
    pga_g: float,
    frequency_hz: float,
) -> float:
    """
    Approximate ground velocity from PGA and dominant frequency.

    Returned in mm/s.
    """

    frequency_hz = max(0.5, frequency_hz)

    acceleration = pga_g * 9.80665

    velocity_m_s = (
        acceleration
        / (2 * math.pi * frequency_hz)
    )

    velocity_mm_s = velocity_m_s * 1000

    return round(
        max(0.1, min(250.0, velocity_mm_s)),
        2,
    )


def _seismic_severity(
    pga: float,
    ground_velocity: float,
    frequency: float,
    duration: float,
    recent_events: int,
) -> tuple[str, float]:
    """
    Determine seismic status from measured/simulated ground motion.

    Magnitude alone does NOT determine local severity.
    """

    score = 0.0

    # PGA contribution
    if pga >= 0.15:
        score += 12
    elif pga >= 0.08:
        score += 9
    elif pga >= 0.03:
        score += 5
    elif pga >= 0.01:
        score += 2

    # Ground velocity contribution
    if ground_velocity >= 100:
        score += 5
    elif ground_velocity >= 50:
        score += 3
    elif ground_velocity >= 20:
        score += 1

    # Frequency contribution
    if 2.0 <= frequency <= 10.0:
        score += 1.5

    # Longer shaking adds exposure
    if duration >= 12:
        score += 2
    elif duration >= 7:
        score += 1

    # Repeated activity contributes to the local condition
    if recent_events >= 5:
        score += 3
    elif recent_events >= 3:
        score += 1.5

    score = min(20.0, score)

    if score >= 15:
        severity = "CRITICAL"
    elif score >= 10:
        severity = "HIGH"
    elif score >= 5:
        severity = "ELEVATED"
    else:
        severity = "NORMAL"

    return severity, round(score, 2)


def simulate_seismic_state() -> dict:
    """
    Generate one coherent seismic state for every mine zone.

    This is a software simulation for the prototype.
    It is not a validated geotechnical/seismological safety model.
    """

    global seismic_state

    generated_events = []

    # Make sure every zone has an initialized state.
    for zone in MINE_ZONES:
        if zone not in seismic_state:
            seismic_state[zone] = {
                "event_id": None,
                "timestamp": None,
                "x": SEISMIC_ZONE_COORDS.get(zone, (0.0, 0.0))[0],
                "y": SEISMIC_ZONE_COORDS.get(zone, (0.0, 0.0))[1],
                "depth": 0.0,
                "magnitude": 0.0,
                "frequency": 1.0,
                "dominant_frequency": 1.0,
                "pga": 0.001,
                "ground_velocity": 0.1,
                "duration": 0.0,
                "severity": "NORMAL",
                "status": "NORMAL",
                "risk_contribution": 0.0,
                "event_age": 999,
                "recent_events": 0,
                "active": False,
            }

    for zone in MINE_ZONES:
        state = seismic_state[zone]

        # Age the current event.
        state["event_age"] = state.get("event_age", 999) + 1

        # -------------------------------------------------------------
        # Decide whether a new seismic event begins.
        # -------------------------------------------------------------

        event_probability = 0.07

        current_risk = zone_status.get(zone, "LOW")

        if current_risk == "MEDIUM":
            event_probability += 0.02
        elif current_risk == "HIGH":
            event_probability += 0.035
        elif current_risk == "CRITICAL":
            event_probability += 0.05

        new_event = (
            not state.get("active", False)
            and random.random() < event_probability
        )

        if new_event:
            zone_x, zone_y = SEISMIC_ZONE_COORDS.get(
                zone,
                (0.0, 0.0),
            )

            event_x = zone_x + random.uniform(-4.0, 4.0)
            event_y = zone_y + random.uniform(-4.0, 4.0)

            magnitude = round(
                random.choices(
                    [
                        random.uniform(0.7, 1.5),
                        random.uniform(1.5, 2.4),
                        random.uniform(2.4, 3.3),
                        random.uniform(3.3, 3.9),
                    ],
                    weights=[58, 28, 11, 3],
                    k=1,
                )[0],
                2,
            )

            depth = round(
                random.uniform(25, 180),
                1,
            )

            frequency = round(
                random.uniform(1.5, 12.0),
                2,
            )

            duration = round(
                random.uniform(3.0, 18.0),
                1,
            )

            distance = _seismic_distance_km(
                zone,
                event_x,
                event_y,
            )

            pga = _seismic_pga(
                magnitude,
                distance,
                depth,
            )

            ground_velocity = _seismic_ground_velocity(
                pga,
                frequency,
            )

            state["event_id"] = _seismic_next_event_id()
            state["timestamp"] = current_iso()
            state["x"] = round(event_x, 2)
            state["y"] = round(event_y, 2)
            state["depth"] = depth
            state["magnitude"] = magnitude
            state["frequency"] = frequency
            state["dominant_frequency"] = frequency
            state["pga"] = pga
            state["ground_velocity"] = ground_velocity
            state["duration"] = duration
            state["event_age"] = 0
            state["active"] = True

            state["recent_events"] = min(
                20,
                state.get("recent_events", 0) + 1,
            )

            severity, contribution = _seismic_severity(
                pga,
                ground_velocity,
                frequency,
                duration,
                state["recent_events"],
            )

            state["severity"] = severity
            state["status"] = severity
            state["risk_contribution"] = contribution

            append_csv(
                SEISMIC_HISTORY_PATH,
                {
                    "event_id": state["event_id"],
                    "timestamp": state["timestamp"],
                    "zone": zone,
                    "x": state["x"],
                    "y": state["y"],
                    "depth": state["depth"],
                    "magnitude": state["magnitude"],
                    "frequency": state["frequency"],
                    "dominant_frequency": state[
                        "dominant_frequency"
                    ],
                    "pga": state["pga"],
                    "ground_velocity": state[
                        "ground_velocity"
                    ],
                    "duration": state["duration"],
                    "severity": state["severity"],
                    "status": state["status"],
                    "risk_contribution": state[
                        "risk_contribution"
                    ],
                },
            )

            generated_events.append(dict(state))

        # -------------------------------------------------------------
        # Active event decay.
        # -------------------------------------------------------------

        elif state.get("active", False):
            progress = state["event_age"] / max(
                state.get("duration", 5),
                1,
            )

            if progress >= 1.0:
                state["active"] = False
                state["status"] = "NORMAL"
                state["severity"] = "NORMAL"

                state["pga"] = round(
                    state["pga"] * 0.35,
                    4,
                )

                state["ground_velocity"] = round(
                    state["ground_velocity"] * 0.35,
                    2,
                )

                state["risk_contribution"] = round(
                    state["risk_contribution"] * 0.35,
                    2,
                )

            else:
                # Envelope: rise toward peak, then decay.
                if progress < 0.25:
                    envelope = progress / 0.25
                else:
                    envelope = max(
                        0.05,
                        1.0
                        - ((progress - 0.25) / 0.75),
                    )

                envelope = max(
                    0.05,
                    min(1.0, envelope),
                )

                state["pga"] = round(
                    max(
                        0.001,
                        state["pga"] * envelope,
                    ),
                    4,
                )

                state["ground_velocity"] = round(
                    max(
                        0.1,
                        state["ground_velocity"] * envelope,
                    ),
                    2,
                )

                severity, contribution = _seismic_severity(
                    state["pga"],
                    state["ground_velocity"],
                    state["frequency"],
                    state["duration"],
                    state["recent_events"],
                )

                state["severity"] = severity
                state["status"] = severity
                state["risk_contribution"] = contribution

        # -------------------------------------------------------------
        # Quiet/background period.
        # -------------------------------------------------------------

        else:
            state["pga"] = round(
                max(
                    0.001,
                    state.get("pga", 0.001) * 0.92,
                ),
                4,
            )

            state["ground_velocity"] = round(
                max(
                    0.1,
                    state.get("ground_velocity", 0.1) * 0.92,
                ),
                2,
            )

            background_frequency = round(
                random.uniform(1.0, 5.0),
                2,
            )

            state["frequency"] = background_frequency
            state["dominant_frequency"] = background_frequency
            state["status"] = "NORMAL"
            state["severity"] = "NORMAL"

            state["risk_contribution"] = round(
                min(
                    2.0,
                    state["pga"] * 20,
                ),
                2,
            )

        # -------------------------------------------------------------
        # Slowly forget old events.
        # -------------------------------------------------------------

        if state.get("event_age", 999) > 25:
            state["recent_events"] = max(
                0,
                state.get("recent_events", 0) - 1,
            )

    return {
        "zones": {
            zone: dict(seismic_state[zone])
            for zone in MINE_ZONES
        },
        "events": generated_events,
    }


def current_zone_workers(
    zone: str,
    observation: dict,
) -> list[dict]:

    count = int(observation.get("worker_count", 0))

    base = {
        "North Pit": 101,
        "South Pit": 201,
        "Conveyor Zone": 301,
        "Processing Area": 401,
        "Storage Area": 501,
    }[zone]

    people = []

    for i in range(min(count, 18)):
        angle = (
            i / max(1, min(count, 18))
        ) * math.tau

        radius = 5 + (i % 4) * 1.5

        people.append(
            {
                "id": f"W-{base + i:04d}",
                "x": round(
                    math.cos(angle) * radius,
                    2,
                ),
                "z": round(
                    math.sin(angle) * radius,
                    2,
                ),
                "distance_to_hazard": round(
                    max(
                        2,
                        float(
                            observation.get(
                                "worker_hazard_distance",
                                80,
                            )
                        )
                        + random.uniform(-5, 5),
                    ),
                    1,
                ),
                "ppe": (
                    "OK"
                    if i >= int(
                        observation.get(
                            "ppe_violations",
                            0,
                        )
                    )
                    else "VIOLATION"
                ),
            }
        )

    return people


def simulate_observation(zone: str) -> dict:
    base = zone_observations[zone]

    risk = zone_status.get(zone, "LOW")
    regime = RISK_ORDER.get(risk, 1)

    def drift(name, amount, lo, hi):
        center = float(
            base.get(
                name,
                (lo + hi) / 2,
            )
        )

        return round(
            max(
                lo,
                min(
                    hi,
                    center + random.uniform(
                        -amount,
                        amount,
                    ),
                ),
            ),
            2,
        )

    # Mostly stable telemetry with correlated excursions.
    hazard_burst = random.random() < (
        0.08 + regime * 0.035
    )

    methane = drift(
        "methane",
        0.16 if not hazard_burst else 0.55,
        0.05,
        3.6,
    )

    temperature = drift(
        "temperature",
        2.0 if not hazard_burst else 6.0,
        20,
        98,
    )

    dust = drift(
        "dust",
        8 if not hazard_burst else 30,
        3,
        320,
    )

    vibration = drift(
        "vibration",
        0.45 if not hazard_burst else 1.6,
        0.05,
        12,
    )

    if hazard_burst:
        methane = min(
            3.6,
            methane + random.uniform(0.25, 0.8),
        )

        temperature = min(
            98,
            temperature + random.uniform(3, 11),
        )

        dust = min(
            320,
            dust + random.uniform(15, 65),
        )

        vibration = min(
            12,
            vibration + random.uniform(0.4, 2.8),
        )

    ventilation = base.get(
        "ventilation_status",
        "good",
    )

    if hazard_burst and random.random() < 0.34:
        ventilation = random.choice(
            ["moderate", "poor"]
        )
    elif random.random() < 0.08:
        ventilation = random.choice(
            ["good", "moderate"]
        )

    obs = {
        "methane": methane,

        "co": drift(
            "co",
            1.8 if not hazard_burst else 5,
            0.2,
            55,
        ),

        "temperature": round(
            temperature,
            2,
        ),

        "humidity": drift(
            "humidity",
            3.5,
            20,
            99,
        ),

        "dust": round(
            dust,
            2,
        ),

        "vibration": round(
            vibration,
            2,
        ),

        "noise": drift(
            "noise",
            4 if not hazard_burst else 10,
            35,
            125,
        ),

        "worker_count": int(
            max(
                0,
                min(
                    95,
                    round(
                        float(
                            base.get(
                                "worker_count",
                                20,
                            )
                        )
                        + random.randint(-3, 4)
                    ),
                ),
            )
        ),

        "worker_hazard_distance": drift(
            "worker_hazard_distance",
            7 if not hazard_burst else 18,
            2,
            120,
        ),

        "ppe_violations": int(
            max(
                0,
                min(
                    10,
                    int(
                        base.get(
                            "ppe_violations",
                            0,
                        )
                    )
                    + random.choice(
                        [-1, 0, 0, 1, 2]
                        if hazard_burst
                        else [-1, 0, 0, 0, 1]
                    ),
                ),
            )
        ),

        "equipment_temperature": drift(
            "equipment_temperature",
            3.5 if not hazard_burst else 9,
            28,
            112,
        ),

        "equipment_health": drift(
            "equipment_health",
            2.5 if not hazard_burst else 6,
            35,
            100,
        ),

        "slope_stability": drift(
            "slope_stability",
            2.5 if not hazard_burst else 7,
            20,
            100,
        ),

        "wind_speed": drift(
            "wind_speed",
            3.5,
            0,
            55,
        ),

        "rainfall": drift(
            "rainfall",
            4 if not hazard_burst else 9,
            0,
            55,
        ),

        "visibility": drift(
            "visibility",
            0.7 if not hazard_burst else 2.4,
            0.6,
            15,
        ),

        "ventilation_status": ventilation,
    }

    obs["equipment_overheating"] = (
        1
        if obs["equipment_temperature"] >= 84
        else 0
    )

    obs["last_analysis"] = current_time()

    return obs


def camera_event_for_zone(
    zone: str,
    observation: dict,
    risk: str,
) -> dict:

    ppe = int(
        observation.get(
            "ppe_violations",
            0,
        )
    )

    restricted = (
        float(
            observation.get(
                "worker_hazard_distance",
                100,
            )
        )
        < 15
    )

    event_type = "Routine movement"
    confidence = random.randint(88, 97)
    severity = "INFO"

    if ppe > 0:
        event_type = "PPE violation"
        severity = (
            "HIGH"
            if ppe >= 3
            else "MEDIUM"
        )

    elif restricted:
        event_type = "Restricted-zone proximity"
        severity = "HIGH"

    elif risk in {"HIGH", "CRITICAL"}:
        event_type = "Hazardous activity pattern"
        severity = risk

    return {
        "timestamp": current_time(),
        "camera": (
            f"CAM-{3 + MINE_ZONES.index(zone):02d}"
        ),
        "zone": zone,
        "event": event_type,
        "severity": severity,
        "confidence": confidence,
        "ppe_detected": ppe == 0,
        "restricted_zone": restricted,
    }


def maybe_retrain_model() -> None:
    global training_rows_since_retrain
    global last_retrain_at

    if training_rows_since_retrain < 50:
        return

    try:
        train(ROOT)

        training_rows_since_retrain = 0
        last_retrain_at = current_time()

    except Exception as exc:
        add_audit_entry(
            "Model retraining failed",
            str(exc),
        )


def build_incident_replay(zone: str) -> dict:
    obs = zone_observations[zone]

    confidence = obs.get(
        "ai_confidence",
        75,
    )

    return {
        "id": make_incident_id(),
        "timestamp": current_time(),
        "zone": zone,
        "severity": zone_status[zone],
        "summary": (
            f"AI detected a "
            f"{zone_status[zone].lower()}-risk pattern "
            f"in {zone} with "
            f"{confidence:.0f}% confidence."
        ),
        "events": [
            {
                "at": "T-00:30",
                "event": "Baseline telemetry captured",
                "detail": (
                    "Sensor stream within operating band."
                ),
            },
            {
                "at": "T-00:20",
                "event": "Hazard indicators drifted",
                "detail": (
                    "Environmental and operational variables "
                    "moved away from baseline."
                ),
            },
            {
                "at": "T-00:10",
                "event": "Worker proximity changed",
                "detail": (
                    "Personnel detected closer to the "
                    "affected hazard region."
                ),
            },
            {
                "at": "T-00:04",
                "event": "Camera event correlated",
                "detail": (
                    "Simulated camera flagged an associated "
                    "safety condition."
                ),
            },
            {
                "at": "T-00:00",
                "event": (
                    f"AI risk → {zone_status[zone]}"
                ),
                "detail": (
                    "Prediction crossed the operator "
                    "escalation threshold."
                ),
            },
        ],
    }


def update_live_state() -> dict:
    global live_tick
    global last_incident
    global training_rows_since_retrain

    ensure_model()

    live_tick += 1

    newly_critical = []

    previous = dict(zone_status)

    camera_events = []

    # Update the simulated seismic system before
    # processing the normal mine telemetry.
    seismic_update = simulate_seismic_state()

    last_incident = None

    for zone in MINE_ZONES:
        observation = simulate_observation(zone)

        # ---------------------------------------------------------
        # Add seismic information to the observation.
        # ---------------------------------------------------------

        seismic_zone = seismic_update["zones"].get(
            zone,
            {},
        )

        observation.update(
            {
                "seismic_status": seismic_zone.get(
                    "status",
                    "NORMAL",
                ),
                "seismic_severity": seismic_zone.get(
                    "severity",
                    "NORMAL",
                ),
                "seismic_magnitude": seismic_zone.get(
                    "magnitude",
                    0.0,
                ),
                "seismic_depth": seismic_zone.get(
                    "depth",
                    0.0,
                ),
                "seismic_pga": seismic_zone.get(
                    "pga",
                    0.001,
                ),
                "seismic_ground_velocity": seismic_zone.get(
                    "ground_velocity",
                    0.1,
                ),
                "seismic_frequency": seismic_zone.get(
                    "frequency",
                    1.0,
                ),
                "seismic_duration": seismic_zone.get(
                    "duration",
                    0.0,
                ),
                "seismic_risk_contribution": seismic_zone.get(
                    "risk_contribution",
                    0.0,
                ),
            }
        )

        prediction = ml_predict(
            feature_row_from_observation(
                observation
            )
        )

        zone_observations[zone] = observation

        zone_status[zone] = prediction["risk"]

        observation.update(
            {
                "ai_risk": prediction["risk"],
                "ai_probability": prediction["probability"],
                "ai_confidence": prediction["confidence"],
                "ai_score": prediction["risk_score"],
                "top_factors": prediction["top_factors"],
                "distribution": prediction["distribution"],
            }
        )

        gt = latent_ground_truth(
            observation
        )

        label = class_from_ground_truth(gt)
        training_row = feature_row_from_observation(
            observation
        )

        training_row["risk_class"] = label

        # Vercel's deployed filesystem is read-only.
        # Keep live telemetry generation working without
        # trying to persist runtime data into the repository.
        if os.getenv("VERCEL") != "1":
            append_csv(
                DATA_DIR / "risk_training.csv",
                training_row,
            )

        training_rows_since_retrain += 1

        if os.getenv("VERCEL") != "1":
            append_csv(
                SENSOR_HISTORY_PATH,
                {
                    "timestamp": current_iso(),
                    "zone": zone,
                    **training_row,
                    "model_risk": prediction["risk"],
                    "model_confidence": prediction["confidence"],
                    "synthetic_outcome": label,
                },
            )

        cam = camera_event_for_zone(
            zone,
            observation,
            prediction["risk"],
        )

        camera_events.append(cam)

        append_csv(
            CAMERA_HISTORY_PATH,
            cam,
        )

        # Alert only on a transition into HIGH/CRITICAL
        # to avoid alert spam.
        if (
            prediction["risk"] in {"HIGH", "CRITICAL"}
            and RISK_ORDER[prediction["risk"]]
            > RISK_ORDER.get(
                previous.get(zone, "LOW"),
                1,
            )
        ):
            alert = {
                "id": make_new_alert_id(),
                "timestamp": current_time(),
                "zone": zone,
                "severity": prediction["risk"],
                "rule_ids": [],
                "reason": "; ".join(
                    f"{x['feature'].replace('_', ' ').title()} elevated"
                    for x in prediction["top_factors"][:3]
                ),
                "action": (
                    "Restrict access and review the "
                    "AI risk explanation before "
                    "response escalation."
                ),
                "status": "Open",
                "ai_confidence": prediction["confidence"],
            }

            alerts.insert(
                0,
                alert,
            )

            add_audit_entry(
                "AI alert generated",
                f"{alert['id']} "
                f"({alert['severity']}) for {zone}.",
            )

            if prediction["risk"] == "CRITICAL":
                newly_critical.append(zone)

    # A simulated incident is formed only from
    # HIGH/CRITICAL conditions with people nearby.
    incident_zone = next(
        (
            z
            for z in newly_critical
            if float(
                zone_observations[z].get(
                    "worker_count",
                    0,
                )
            ) > 0
        ),
        None,
    )

    if incident_zone:
        last_incident = build_incident_replay(
            incident_zone
        )

        append_csv(
            INCIDENT_HISTORY_PATH,
            {
                "incident_id": last_incident["id"],
                "timestamp": last_incident["timestamp"],
                "zone": incident_zone,
                "severity": last_incident["severity"],
                "summary": last_incident["summary"],
            },
        )

    update_compliance_from_observation(
        zone_observations.get(
            "Processing Area",
            {},
        )
    )

    # maybe_retrain_model()

    max_risk = max(
        zone_status.values(),
        key=lambda x: RISK_ORDER[x],
    )

    active_people = sum(
        int(
            zone_observations[z].get(
                "worker_count",
                0,
            )
        )
        for z in MINE_ZONES
    )

    active_equipment = sum(
        ZONES[z]["equipment"]
        for z in MINE_ZONES
    )

    open_alerts = len(
        [
            a
            for a in alerts
            if a["status"] != "Resolved"
        ]
    )

    compliance = compliance_summary()

    compliance_pct = round(
        compliance.get("Compliant", 0)
        / max(
            sum(compliance.values()),
            1,
        )
        * 100
    )

    return {
        "tick": live_tick,
        "timestamp": current_time(),
        "zones": zone_status,
        "observations": zone_observations,
        "max_risk": max_risk,
        "mine_probability": round(
            sum(
                zone_observations[z].get(
                    "ai_probability",
                    0,
                )
                for z in MINE_ZONES
            )
            / len(MINE_ZONES),
            4,
        ),
        "mine_score": round(
            sum(
                zone_observations[z].get(
                    "ai_score",
                    0,
                )
                for z in MINE_ZONES
            )
            / len(MINE_ZONES),
            1,
        ),
        "active_personnel": active_people,
        "active_equipment": active_equipment,
        "open_alerts": open_alerts,
        "compliance": compliance_pct,
        "camera_events": camera_events,
        "newly_critical": newly_critical,
        "last_incident": last_incident,
        "model": model_metadata(),
        "seismic": seismic_update,
    }



def build_incident_replay(zone: str) -> dict:
    obs = zone_observations[zone]
    confidence = obs.get("ai_confidence", 75)
    return {
        "id": make_incident_id(),
        "timestamp": current_time(),
        "zone": zone,
        "severity": zone_status[zone],
        "summary": f"AI detected a {zone_status[zone].lower()}-risk pattern in {zone} with {confidence:.0f}% confidence.",
        "events": [
            {"at": "T-00:30", "event": "Baseline telemetry captured", "detail": "Sensor stream within operating band."},
            {"at": "T-00:20", "event": "Hazard indicators drifted", "detail": "Environmental and operational variables moved away from baseline."},
            {"at": "T-00:10", "event": "Worker proximity changed", "detail": "Personnel detected closer to the affected hazard region."},
            {"at": "T-00:04", "event": "Camera event correlated", "detail": "Simulated camera flagged an associated safety condition."},
            {"at": "T-00:00", "event": f"AI risk → {zone_status[zone]}", "detail": "Prediction crossed the operator escalation threshold."},
        ],
    }


def evacuation_plan(zone: str) -> dict:
    observation = zone_observations.get(zone, {})
    workers = current_zone_workers(zone, observation)
    route_map = {
        "North Pit": ["North Bench", "Main Ramp", "North Exit"],
        "South Pit": ["South Bench", "Haul Road 02", "South Exit"],
        "Conveyor Zone": ["Conveyor Corridor", "Maintenance Road", "West Exit"],
        "Processing Area": ["Processing Plant", "Conveyor Corridor", "North Exit"],
        "Storage Area": ["Storage Yard", "Service Road", "East Exit"],
    }
    danger = zone_status.get(zone, "LOW")
    time_min = max(2.4, 2.4 + len(workers) * .065 + (0.9 if danger == "CRITICAL" else 0.4 if danger == "HIGH" else 0))
    return {
        "zone": zone,
        "risk": danger,
        "workers": len(workers),
        "route": route_map.get(zone, ["Primary Access Road", "Nearest Safe Exit"]),
        "eta_minutes": round(time_min, 1),
        "workers_detail": workers,
        "generated_at": current_time(),
    }


def common_page_context():
    severity_counts = count_alerts_by_severity()
    open_alerts = [a for a in alerts if a["status"] != "Resolved"]
    return {
        "zone_status": zone_status,
        "zone_observations": zone_observations,
        "severity_counts": severity_counts,
        "open_alerts": open_alerts,
        "total_zones": len(MINE_ZONES),
        "active_rules": 0,
        "compliance_summary": compliance_summary(),
        "last_analysis": zone_observations.get("Processing Area", {}).get("last_analysis") or "No analysis",
    }


@app.route("/")
def dashboard():
    context = common_page_context()
    context["recent_audit"] = audit_log[:6]
    context["model_info"] = model_metadata()
    return render_template("dashboard.html", **context)


@app.route("/analyze")
def analyze_page():
    return render_template("analyze.html", zones=MINE_ZONES, zone_status=zone_status, active_rules=0, model_info=model_metadata())


@app.route("/alerts")
def alerts_page():
    counts = count_alerts_by_severity()
    return render_template(
        "alerts.html", alerts=alerts,
        open_count=len([a for a in alerts if a["status"] != "Resolved"]),
        critical_count=counts["CRITICAL"],
        acknowledged_count=len([a for a in alerts if a["status"] == "Acknowledged"]),
        resolved_count=len([a for a in alerts if a["status"] == "Resolved"]),
    )


@app.route("/compliance")
def compliance_page():
    return render_template("compliance.html", checks=compliance_checks, summary=compliance_summary())


@app.route("/audit")
def audit_page():
    return render_template("audit.html", audit_log=audit_log)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    payload = request.get_json(silent=True) or {}
    zone = payload.get("zone", "Unknown Zone")
    try:
        features = feature_row_from_observation(payload)
        result = ml_predict(features)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    if zone in MINE_ZONES:
        zone_status[zone] = result["risk"]
        zone_observations[zone] = {**payload, **features, **result, "last_analysis": current_time()}
        update_compliance_from_observation(zone_observations[zone])

    add_audit_entry("AI risk analysis performed", f"Zone: {zone} | Result: {result['risk']} | Confidence: {result['confidence']:.1f}%")
    if result["risk"] in {"HIGH", "CRITICAL"}:
        alert = {
            "id": make_new_alert_id(), "timestamp": current_time(), "zone": zone,
            "severity": result["risk"], "rule_ids": [],
            "reason": "; ".join(f"{x['feature'].replace('_',' ').title()} elevated" for x in result["top_factors"][:3]),
            "action": "Review the AI explanation and initiate the appropriate safety response.",
            "status": "Open", "ai_confidence": result["confidence"],
        }
        alerts.insert(0, alert)
        result["alert_id"] = alert["id"]
    result.update({"zone": zone, "analyzed_at": current_time()})
    return jsonify(result)


@app.route("/api/live_state")
def api_live_state():
    with state_lock:
        return jsonify(update_live_state())


@app.route("/api/what_if", methods=["POST"])
def api_what_if():
    payload = request.get_json(silent=True) or {}
    zone = payload.get("zone", "Processing Area")
    base = dict(zone_observations.get(zone, {}))
    overrides = payload.get("overrides", {})
    base.update(overrides)
    try:
        result = ml_predict(feature_row_from_observation(base))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"zone": zone, **result, "inputs": feature_row_from_observation(base)})


@app.route("/api/evacuation", methods=["POST"])
def api_evacuation():
    payload = request.get_json(silent=True) or {}
    zone = payload.get("zone") or max(zone_status, key=lambda z: RISK_ORDER[zone_status[z]])
    plan = evacuation_plan(zone)
    add_audit_entry("Evacuation simulation", f"Route generated for {zone}: {' → '.join(plan['route'])}.")
    return jsonify(plan)


@app.route("/api/incident_replay")
def api_incident_replay():
    return jsonify(last_incident or build_incident_replay("Processing Area"))


# ---------------------------------------------------------------------
# Safety Copilot
# Context-aware, deterministic response engine.
# Uses the live mine state instead of hard-coded responses.
# ---------------------------------------------------------------------

COPILOT_ZONE_ALIASES = {
    "north": "North Pit",
    "north pit": "North Pit",
    "south": "South Pit",
    "south pit": "South Pit",
    "conveyor": "Conveyor Zone",
    "conveyor zone": "Conveyor Zone",
    "processing": "Processing Area",
    "processing area": "Processing Area",
    "plant": "Processing Area",
    "storage": "Storage Area",
    "storage area": "Storage Area",
}

COPILOT_SENSOR_LABELS = {
    "methane": ("methane", "Methane"),
    "co": ("co", "CO"),
    "carbon monoxide": ("co", "CO"),
    "temperature": ("temperature", "Temperature"),
    "humidity": ("humidity", "Humidity"),
    "dust": ("dust", "Dust"),
    "vibration": ("vibration", "Vibration"),
    "noise": ("noise", "Noise"),
    "worker hazard distance": ("worker_hazard_distance", "Worker-hazard distance"),
    "ppe": ("ppe_violations", "PPE violations"),
    "ppe violations": ("ppe_violations", "PPE violations"),
    "equipment temperature": ("equipment_temperature", "Equipment temperature"),
    "equipment health": ("equipment_health", "Equipment health"),
    "slope": ("slope_stability", "Slope stability"),
    "slope stability": ("slope_stability", "Slope stability"),
    "wind": ("wind_speed", "Wind speed"),
    "wind speed": ("wind_speed", "Wind speed"),
    "rain": ("rainfall", "Rainfall"),
    "rainfall": ("rainfall", "Rainfall"),
    "visibility": ("visibility", "Visibility"),
    "ventilation": ("ventilation_status", "Ventilation"),
}


def _copilot_clean(text: str) -> str:
    """Normalize user input for intent and zone detection."""
    return " ".join(str(text).strip().lower().split())


def _copilot_percentage(value) -> float:
    """Convert either 0-1 or 0-100 values to a percentage."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    if 0 <= number <= 1:
        return number * 100

    return number


def _copilot_pretty_feature(feature: str) -> str:
    """Turn model feature names into readable labels."""
    labels = {
        "methane": "Methane",
        "co": "CO",
        "temperature": "Temperature",
        "humidity": "Humidity",
        "dust": "Dust",
        "vibration": "Vibration",
        "noise": "Noise",
        "worker_count": "Worker count",
        "worker_hazard_distance": "Worker-hazard distance",
        "ppe_violations": "PPE violations",
        "equipment_temperature": "Equipment temperature",
        "equipment_overheating": "Equipment overheating",
        "equipment_health": "Equipment health",
        "slope_stability": "Slope stability",
        "wind_speed": "Wind speed",
        "rainfall": "Rainfall",
        "visibility": "Visibility",
    }

    return labels.get(
        str(feature),
        str(feature).replace("_", " ").title()
    )


def _copilot_find_zone(question: str, default_zone: str) -> str:
    """
    Detect the zone mentioned in the question.
    If no zone is mentioned, use the currently selected zone.
    """
    q = _copilot_clean(question)

    # Longest phrases first.
    for alias in sorted(COPILOT_ZONE_ALIASES, key=len, reverse=True):
        if alias in q:
            return COPILOT_ZONE_ALIASES[alias]

    if default_zone in MINE_ZONES:
        return default_zone

    return max(
        zone_status,
        key=lambda z: RISK_ORDER.get(zone_status.get(z, "LOW"), 1)
    )


def _copilot_top_factors(zone: str, limit: int = 3) -> list[str]:
    """Return readable names of the model's strongest contributing factors."""
    observation = zone_observations.get(zone, {})
    factors = observation.get("top_factors") or []

    names = []

    for factor in factors[:limit]:
        if isinstance(factor, dict):
            feature = factor.get("feature")
        else:
            feature = factor

        if feature:
            names.append(_copilot_pretty_feature(feature))

    return names


def _copilot_risk_zones() -> list[tuple[str, str]]:
    """Return zones ordered by current simulated risk."""
    return sorted(
        (
            (zone, zone_status.get(zone, "LOW"))
            for zone in MINE_ZONES
        ),
        key=lambda item: RISK_ORDER.get(item[1], 1),
        reverse=True,
    )


def _copilot_detect_intent(question: str) -> str:
    """
    Score the question against several Copilot intents.
    This allows different phrasings to reach the same reasoning path.
    """
    q = _copilot_clean(question)

    scores = {
        "evacuation": 0,
        "compliance": 0,
        "alerts": 0,
        "workers": 0,
        "equipment": 0,
        "sensors": 0,
        "comparison": 0,
        "model": 0,
        "action": 0,
        "risk": 0,
        "summary": 0,
    }

    keyword_weights = {
        "evacuation": [
            ("evacuate", 5),
            ("evacuation", 5),
            ("evacuate workers", 7),
            ("evacuation plan", 7),
            ("exit route", 6),
            ("escape route", 6),
            ("emergency route", 6),
            ("get out", 4),
        ],

        "compliance": [
            ("compliance", 6),
            ("compliant", 5),
            ("ppe", 5),
            ("inspection", 4),
            ("checklist", 4),
            ("ventilation", 3),
        ],

        "alerts": [
            ("alert", 5),
            ("alerts", 5),
            ("warning", 4),
            ("warnings", 4),
            ("incident", 5),
            ("open alert", 6),
            ("critical alert", 7),
            ("unresolved", 4),
        ],

        "workers": [
            ("worker", 5),
            ("workers", 5),
            ("personnel", 5),
            ("people", 3),
            ("manpower", 4),
            ("exposure", 5),
            ("exposed", 5),
            ("hazard distance", 6),
            ("how many people", 6),
        ],

        "equipment": [
            ("equipment", 5),
            ("machine", 4),
            ("machines", 4),
            ("overheating", 6),
            ("equipment health", 7),
            ("equipment temperature", 7),
            ("health of equipment", 6),
        ],

        "sensors": [
            ("sensor", 5),
            ("sensors", 5),
            ("telemetry", 5),
            ("methane", 6),
            ("carbon monoxide", 6),
            (" co ", 5),
            ("temperature", 4),
            ("humidity", 4),
            ("dust", 4),
            ("vibration", 5),
            ("noise", 4),
            ("visibility", 4),
            ("rainfall", 4),
            ("wind", 4),
            ("reading", 4),
        ],

        "comparison": [
            ("compare", 7),
            ("comparison", 7),
            ("highest risk", 8),
            ("lowest risk", 8),
            ("most dangerous", 8),
            ("safest zone", 8),
            ("highest score", 8),
            ("lowest score", 8),
            ("which zone", 6),
            ("what zone", 5),
            ("rank", 5),
        ],

        "model": [
            ("model", 6),
            ("ai model", 7),
            ("confidence", 6),
            ("prediction confidence", 7),
            ("probability", 6),
            ("algorithm", 6),
            ("random forest", 7),
            ("training", 5),
            ("prediction", 5),
        ],

        "action": [
            ("what should i do", 10),
            ("what should we do", 10),
            ("what do we do", 9),
            ("what action", 8),
            ("next step", 8),
            ("how should we respond", 9),
            ("how do we respond", 9),
            ("recommended action", 9),
            ("recommendation", 7),
            ("respond", 6),
            ("response", 5),
        ],

        "risk": [
            ("risk", 5),
            ("danger", 5),
            ("dangerous", 5),
            ("hazard", 5),
            ("critical", 5),
            ("high risk", 7),
            ("risk score", 7),
            ("risk level", 7),
            ("why is", 3),
            ("why", 3),
            ("cause", 5),
            ("causing", 5),
            ("factor", 4),
            ("factors", 4),
            ("driver", 4),
            ("drivers", 4),
        ],

        "summary": [
            ("summary", 7),
            ("overview", 7),
            ("overall status", 8),
            ("mine status", 7),
            ("mine-wide", 7),
            ("whole mine", 6),
            ("what's happening", 7),
            ("what is happening", 7),
            ("current situation", 7),
        ],
    }

    # Add a little padding around the question so " co " can be detected.
    padded_q = f" {q} "

    for intent, terms in keyword_weights.items():
        for term, weight in terms:
            if term in padded_q:
                scores[intent] += weight

    # More specific intents should win ties over generic risk questions.
    priority = [
        "evacuation",
        "compliance",
        "alerts",
        "workers",
        "equipment",
        "sensors",
        "comparison",
        "model",
        "action",
        "risk",
        "summary",
    ]

    best_intent = "summary"
    best_score = 0

    for intent in priority:
        score = scores[intent]
        if score > best_score:
            best_score = score
            best_intent = intent

    # A direct "why" question is much more useful as a risk explanation.
    if q.startswith("why "):
        return "risk"

    return best_intent


def _copilot_sensor_response(zone: str, question: str) -> str:
    observation = zone_observations.get(zone, {})
    risk = zone_status.get(zone, "LOW")

    requested_key = None
    requested_label = None

    for phrase, (key, label) in sorted(
        COPILOT_SENSOR_LABELS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if phrase in question:
            requested_key = key
            requested_label = label
            break

    if requested_key:
        value = observation.get(requested_key, "N/A")

        if requested_key == "ventilation_status":
            reading = str(value).title()
        elif requested_key == "worker_hazard_distance":
            reading = f"{float(value):.1f} m"
        elif requested_key == "equipment_health":
            reading = f"{float(value):.1f}%"
        elif requested_key == "ppe_violations":
            reading = str(int(value))
        elif requested_key in {"temperature", "equipment_temperature"}:
            reading = f"{float(value):.1f} °C"
        elif requested_key == "humidity":
            reading = f"{float(value):.1f}%"
        elif requested_key == "visibility":
            reading = f"{float(value):.1f}"
        elif requested_key == "wind_speed":
            reading = f"{float(value):.1f}"
        elif requested_key == "rainfall":
            reading = f"{float(value):.1f}"
        else:
            reading = f"{float(value):.2f}"

        factors = _copilot_top_factors(zone)

        response = (
            f"{zone} — {requested_label}: {reading}\n"
            f"Current risk: {risk}."
        )

        if factors:
            response += (
                f"\nThe model's strongest current contributors are "
                f"{', '.join(factors)}."
            )

        return response

    # Generic sensor/telemetry question.
    factor_names = _copilot_top_factors(zone, 4)

    response = (
        f"{zone} — current telemetry\n"
        f"Methane: {float(observation.get('methane', 0)):.2f}\n"
        f"CO: {float(observation.get('co', 0)):.2f}\n"
        f"Temperature: {float(observation.get('temperature', 0)):.1f} °C\n"
        f"Dust: {float(observation.get('dust', 0)):.1f}\n"
        f"Vibration: {float(observation.get('vibration', 0)):.2f}\n"
        f"Visibility: {float(observation.get('visibility', 0)):.1f}\n"
        f"Ventilation: {str(observation.get('ventilation_status', 'unknown')).title()}\n"
        f"Risk: {risk}"
    )

    if factor_names:
        response += (
            f"\n\nModel attention is currently strongest on: "
            f"{', '.join(factor_names)}."
        )

    return response


def _copilot_response(question: str, selected_zone: str) -> tuple[str, str]:
    """
    Main reasoning layer.
    Returns: (answer, zone_used)
    """
    q = _copilot_clean(question)
    zone = _copilot_find_zone(q, selected_zone)
    intent = _copilot_detect_intent(q)

    observation = zone_observations.get(zone, {})
    risk = zone_status.get(zone, "LOW")

    confidence = _copilot_percentage(
        observation.get("ai_confidence", 0)
    )

    probability = _copilot_percentage(
        observation.get("ai_probability", 0)
    )

    score = float(observation.get("ai_score", 0))

    workers = int(observation.get("worker_count", 0))
    hazard_distance = float(
        observation.get("worker_hazard_distance", 0)
    )

    factors = _copilot_top_factors(zone)

    # ---------------------------------------------------------------
    # 1. WHY / RISK EXPLANATION
    # ---------------------------------------------------------------
    if intent == "risk":
        factor_text = ", ".join(factors) if factors else "the current telemetry pattern"

        answer = (
            f"{zone} — {risk} risk\n\n"
            f"Why: The model is responding most strongly to {factor_text}.\n"
            f"Risk score: {score:.0f}/100\n"
            f"Prediction probability: {probability:.0f}%\n"
            f"Model confidence: {confidence:.0f}%"
        )

        if workers > 0:
            answer += (
                f"\nPersonnel in zone: {workers}\n"
                f"Worker-hazard distance: {hazard_distance:.1f} m"
            )

        answer += (
            "\n\nThis is a model-based assessment of the simulated "
            "mine state; verify the relevant field evidence before acting."
        )

        return answer, zone

    # ---------------------------------------------------------------
    # 2. WORKER / EXPOSURE
    # ---------------------------------------------------------------
    if intent == "workers":
        answer = (
            f"{zone} currently has {workers} active personnel "
            f"in the simulated stream.\n"
            f"Worker-hazard distance: {hazard_distance:.1f} m\n"
            f"Current zone risk: {risk}"
        )

        ppe = int(observation.get("ppe_violations", 0))
        if ppe:
            answer += (
                f"\nPPE violations: {ppe}"
            )

        if risk in {"HIGH", "CRITICAL"}:
            answer += (
                "\n\nBecause the zone is currently elevated-risk, "
                "personnel exposure should be reviewed alongside the "
                "site's established safety procedures."
            )

        return answer, zone

    # ---------------------------------------------------------------
    # 3. SENSOR / TELEMETRY
    # ---------------------------------------------------------------
    if intent == "sensors":
        return _copilot_sensor_response(zone, q), zone

    # ---------------------------------------------------------------
    # 4. EQUIPMENT
    # ---------------------------------------------------------------
    if intent == "equipment":
        equipment_health = float(
            observation.get("equipment_health", 0)
        )
        equipment_temp = float(
            observation.get("equipment_temperature", 0)
        )
        overheating = bool(
            observation.get("equipment_overheating", 0)
        )

        status_text = "overheating flag is ACTIVE" if overheating else "no overheating flag is active"

        answer = (
            f"{zone} — equipment status\n"
            f"Equipment health: {equipment_health:.1f}%\n"
            f"Equipment temperature: {equipment_temp:.1f} °C\n"
            f"Status: {status_text}\n"
            f"Zone risk: {risk}"
        )

        if equipment_health < 75 or overheating:
            answer += (
                "\n\nThe simulated state indicates an equipment-related "
                "condition that should be inspected and correlated with "
                "the other telemetry before escalation."
            )
        else:
            answer += (
                "\n\nNo equipment-overheating condition is currently "
                "flagged in the simulated state."
            )

        return answer, zone

    # ---------------------------------------------------------------
    # 5. COMPLIANCE
    # ---------------------------------------------------------------
    if intent == "compliance":
        summary = compliance_summary()

        compliant = summary.get("Compliant", 0)
        warning = summary.get("Warning", 0)
        pending = summary.get("Pending", 0)

        answer = (
            f"Mine compliance status\n"
            f"Compliant: {compliant}\n"
            f"Warnings: {warning}\n"
            f"Pending: {pending}\n"
        )

        issue_lines = []

        for check in compliance_checks:
            status = check.get("status", "Pending")

            if status != "Compliant":
                name = check.get("check", "Unknown check")
                action = check.get("action", "Review required")

                issue_lines.append(
                    f"{name}: {status} — {action}"
                )

        if issue_lines:
            answer += "\nCurrent items requiring attention:\n"
            answer += "\n".join(issue_lines)
        else:
            answer += "\nNo current compliance item is flagged as requiring attention."

        return answer, zone

    # ---------------------------------------------------------------
    # 6. ALERTS
    # ---------------------------------------------------------------
    if intent == "alerts":
        open_alerts = [
            alert for alert in alerts
            if alert.get("status") != "Resolved"
        ]

        if not open_alerts:
            return (
                "There are currently no open alerts in the simulated mine state.",
                zone,
            )

        severity_rank = {
            "CRITICAL": 4,
            "HIGH": 3,
            "MEDIUM": 2,
            "LOW": 1,
            "INFO": 0,
        }

        open_alerts.sort(
            key=lambda a: severity_rank.get(a.get("severity", "LOW"), 1),
            reverse=True,
        )

        answer = (
            f"Open alerts: {len(open_alerts)}\n\n"
        )

        for alert in open_alerts[:6]:
            answer += (
                f"{alert.get('severity', 'UNKNOWN')} — "
                f"{alert.get('zone', 'Unknown zone')}\n"
                f"{alert.get('reason', 'No reason recorded')}\n"
                f"Status: {alert.get('status', 'Unknown')}\n\n"
            )

        if len(open_alerts) > 6:
            answer += (
                f"{len(open_alerts) - 6} additional open alert(s) "
                f"are not shown here."
            )

        return answer.strip(), zone

    # ---------------------------------------------------------------
    # 7. ZONE COMPARISON
    # ---------------------------------------------------------------
    if intent == "comparison":
        ranked = _copilot_risk_zones()

        highest_zone, highest_risk = ranked[0]
        lowest_zone, lowest_risk = ranked[-1]

        answer = (
            "Current zone comparison\n\n"
            f"Highest current risk: {highest_zone} — {highest_risk}\n"
            f"Lowest current risk: {lowest_zone} — {lowest_risk}\n\n"
            "All zones:\n"
        )

        for zone_name, zone_risk in ranked:
            zone_obs = zone_observations.get(zone_name, {})
            zone_score = float(zone_obs.get("ai_score", 0))
            zone_workers = int(zone_obs.get("worker_count", 0))

            answer += (
                f"{zone_name}: {zone_risk} | "
                f"Score {zone_score:.0f}/100 | "
                f"Personnel {zone_workers}\n"
            )

        return answer.strip(), zone

    # ---------------------------------------------------------------
    # 8. MODEL / AI
    # ---------------------------------------------------------------
    if intent == "model":
        metadata = model_metadata()

        model_name = metadata.get("model", "Configured model")
        training_data = metadata.get(
            "training_data",
            metadata.get("dataset", "Configured training data"),
        )

        answer = (
            f"AI model information\n"
            f"Model: {model_name}\n"
            f"Training data: {training_data}\n"
            f"Current zone: {zone}\n"
            f"Risk: {risk}\n"
            f"Prediction probability: {probability:.0f}%\n"
            f"Model confidence: {confidence:.0f}%\n"
            f"Risk score: {score:.0f}/100"
        )

        return answer, zone

    # ---------------------------------------------------------------
    # 9. EVACUATION
    # ---------------------------------------------------------------
    if intent == "evacuation":
        plan = evacuation_plan(zone)

        route = " → ".join(plan.get("route", []))
        eta = float(plan.get("eta_minutes", 0))
        worker_count = int(plan.get("workers", 0))

        answer = (
            f"Evacuation simulation — {zone}\n\n"
            f"Current risk: {plan.get('risk', risk)}\n"
            f"Personnel: {worker_count}\n"
            f"Route: {route}\n"
            f"Estimated evacuation time: {eta:.1f} minutes\n"
        )

        if risk in {"HIGH", "CRITICAL"}:
            answer += (
                "\nThe simulated condition is elevated. The evacuation "
                "route shown here is a prototype simulation and should "
                "not replace the mine's approved emergency procedures."
            )
        else:
            answer += (
                "\nThis is a simulated route generated from the current "
                "prototype state."
            )

        return answer, zone

    # ---------------------------------------------------------------
    # 10. ACTION / RESPONSE
    # ---------------------------------------------------------------
    if intent == "action":
        factor_text = ", ".join(factors) if factors else "the current telemetry"

        if risk == "CRITICAL":
            response_level = (
                "The zone is currently CRITICAL. Restrict unnecessary "
                "entry, verify the relevant sensor and camera evidence, "
                "and follow the mine's established emergency escalation "
                "procedure."
            )
        elif risk == "HIGH":
            response_level = (
                "The zone is currently HIGH risk. Review the active "
                "risk contributors, verify the underlying field readings, "
                "and apply the site's prescribed response procedure."
            )
        elif risk == "MEDIUM":
            response_level = (
                "The zone is currently MEDIUM risk. Continue monitoring "
                "the contributing conditions and verify any worsening trend."
            )
        else:
            response_level = (
                "The zone is currently LOW risk. Continue normal monitoring "
                "and review the telemetry for meaningful changes."
            )

        answer = (
            f"{zone} — {risk} risk\n\n"
            f"Main model contributors: {factor_text}\n\n"
            f"Recommended response:\n{response_level}\n\n"
            "This Copilot provides decision support; operators should "
            "use the mine's actual safety procedures and field evidence "
            "for operational decisions."
        )

        return answer, zone

    # ---------------------------------------------------------------
    # 11. MINE-WIDE SUMMARY
    # ---------------------------------------------------------------
    ranked = _copilot_risk_zones()

    highest_zone, highest_risk = ranked[0]

    total_workers = sum(
        int(zone_observations.get(z, {}).get("worker_count", 0))
        for z in MINE_ZONES
    )

    avg_score = (
        sum(
            float(zone_observations.get(z, {}).get("ai_score", 0))
            for z in MINE_ZONES
        )
        / max(len(MINE_ZONES), 1)
    )

    mine_probability = (
        sum(
            _copilot_percentage(
                zone_observations.get(z, {}).get("ai_probability", 0)
            )
            for z in MINE_ZONES
        )
        / max(len(MINE_ZONES), 1)
    )

    compliance = compliance_summary()

    open_alert_count = len([
        alert for alert in alerts
        if alert.get("status") != "Resolved"
    ])

    answer = (
        "Mine-wide status\n\n"
        f"Highest current risk: {highest_zone} — {highest_risk}\n"
        f"Average risk score: {avg_score:.0f}/100\n"
        f"Average prediction probability: {mine_probability:.0f}%\n"
        f"Active personnel: {total_workers}\n"
        f"Open alerts: {open_alert_count}\n"
        f"Compliance: {compliance.get('Compliant', 0)} compliant, "
        f"{compliance.get('Warning', 0)} warning, "
        f"{compliance.get('Pending', 0)} pending"
    )

    if highest_risk in {"HIGH", "CRITICAL"}:
        highest_factors = _copilot_top_factors(highest_zone)

        if highest_factors:
            answer += (
                f"\n\n{highest_zone}'s strongest current model contributors: "
                f"{', '.join(highest_factors)}."
            )

    return answer, zone

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:0.6b"

def ask_ollama_stream(
    question: str,
    zone: str,
    obs: dict,
    risk: str,
    factors: list,
    history: list
):
    factor_text = ", ".join(
        str(f.get("feature", "")).replace("_", " ")
        for f in factors[:5]
    ) or "no dominant factors available"

    system_prompt = """
You are Safety Copilot for a simulated coal mine monitoring dashboard.

Answer using only the mine information supplied by the application.

Rules:

- Never invent sensor readings, worker counts, incidents, or risk values.
- Use the supplied dashboard data as the source of truth.
- Use previous conversation messages only when relevant.
- Give clear, useful answers in 4–6 short sentences.
- For safety questions, include the current risk, the reason, and the recommended action when the supplied data supports them.
- Do not claim to control machinery or emergency systems.
- This is a prototype using simulated mine data.
"""

    user_prompt = f"""
Zone: {zone}

Risk: {risk}

Observation:
{obs}

Top contributors:
{factor_text}

Question:
{question}
"""

    recent_history = history[-4:] if history else []

    messages = [
        {
            "role": "system",
            "content": system_prompt.strip()
        }
    ]

    messages.extend(recent_history)

    messages.append({
        "role": "user",
        "content": user_prompt.strip()
    })

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "think": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.2,
            "num_predict": 128,
            "num_ctx": 2048
        }
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        stream=True,
        timeout=45
    )

    response.raise_for_status()

    try:
        for line in response.iter_lines(decode_unicode=True):

            if not line:
                continue

            data = json.loads(line)

            message = data.get("message", {})
            content = message.get("content", "")

            if content:
                yield {
                    "type": "token",
                    "content": content
                }

            if data.get("done"):
                yield {
                    "type": "done"
                }

    finally:
        response.close()

@app.route("/api/copilot", methods=["POST"])
def api_copilot():

    payload = request.get_json(silent=True) or {}

    conversation_id = str(
        payload.get("conversation_id") or "default"
    ).strip()

    question = str(
        payload.get("question", "")
    ).strip()

    zone = payload.get("zone") or max(
        zone_status,
        key=lambda z: RISK_ORDER[zone_status[z]]
    )

    if not question:
        return jsonify({
            "error": "Please enter a question."
        }), 400

    # Get previous conversation before saving the new question.
    history = get_history(
        conversation_id,
        limit=12
    )

    obs = zone_observations.get(
        zone,
        {}
    )

    risk = zone_status.get(
        zone,
        "LOW"
    )

    factors = obs.get(
        "top_factors"
    ) or []

    def generate():

        full_answer = ""

        try:

            for event in ask_ollama_stream(

                question=question,
                zone=zone,
                obs=obs,
                risk=risk,
                factors=factors,
                history=history
            ):

                if event["type"] == "token":

                    content = event["content"]

                    full_answer += content

                    yield json.dumps({
                        "type": "token",
                        "content": content
                    }) + "\n"

                elif event["type"] == "done":

                    # Save only after the complete response is received.
                    save_message(
                        conversation_id,
                        "user",
                        question,
                        zone
                    )

                    save_message(
                        conversation_id,
                        "assistant",
                        full_answer,
                        zone
                    )

                    add_audit_entry(
                        "AI copilot query",
                        f"Zone: {zone} | Query: {question[:90]}"
                    )

                    yield json.dumps({
                        "type": "done",
                        "zone": zone,
                        "risk": risk,
                        "answer": full_answer,
                        "factors": factors,
                        "confidence": obs.get(
                            "ai_confidence",
                            0
                        )
                    }) + "\n"

        except requests.exceptions.ConnectionError:

            yield json.dumps({
                "type": "error",
                "error": "Ollama is not running. Open Ollama and try again."
            }) + "\n"

        except requests.exceptions.Timeout:

            yield json.dumps({
                "type": "error",
                "error": "The local AI took too long to respond. Try a shorter question."
            }) + "\n"

        except requests.exceptions.RequestException as exc:

            yield json.dumps({
                "type": "error",
                "error": f"Ollama request failed: {exc}"
            }) + "\n"

        except (KeyError, ValueError, TypeError) as exc:

            yield json.dumps({
                "type": "error",
                "error": f"Invalid Ollama response: {exc}"
            }) + "\n"

        except Exception as exc:

            yield json.dumps({
                "type": "error",
                "error": f"Unexpected error: {exc}"
            }) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson"
    )

def api_model_info():
    return jsonify(model_metadata())


@app.route("/api/alerts/<alert_id>/status", methods=["POST"])
def api_update_alert_status(alert_id):
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status not in {"Open", "Acknowledged", "Resolved"}:
        return jsonify({"error": "Invalid status"}), 400
    for alert in alerts:
        if alert["id"] == alert_id:
            alert["status"] = new_status
            add_audit_entry(f"Alert {new_status.lower()}", f"{alert_id} marked as {new_status}.")
            return jsonify(alert)
    return jsonify({"error": "Alert not found"}), 404

if __name__ == "__main__":
    init_db()
    ensure_model()
    app.run(debug=True)