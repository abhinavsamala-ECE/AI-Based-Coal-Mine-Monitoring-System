# All values in this file are FICTIONAL / DEMO data for the SIH prototype.

MINE_ZONES = [
    "North Pit",
    "South Pit",
    "Conveyor Zone",
    "Processing Area",
    "Storage Area",
]

INITIAL_ZONE_STATUS = {
    "North Pit": "LOW",
    "South Pit": "LOW",
    "Conveyor Zone": "MEDIUM",
    "Processing Area": "HIGH",
    "Storage Area": "LOW",
}

# Latest demo values shown when a zone is clicked on the map.
INITIAL_ZONE_OBSERVATIONS = {
    "North Pit": {
        "methane": 0.5,
        "dust": 38,
        "temperature": 36,
        "vibration": 2.1,
        "ventilation_status": "good",
        "last_analysis": "Demo state",
    },
    "South Pit": {
        "methane": 0.7,
        "dust": 42,
        "temperature": 37,
        "vibration": 2.4,
        "ventilation_status": "good",
        "last_analysis": "Demo state",
    },
    "Conveyor Zone": {
        "methane": 0.6,
        "dust": 55,
        "temperature": 42,
        "vibration": 5.2,
        "ventilation_status": "good",
        "last_analysis": "Demo state",
    },
    "Processing Area": {
        "methane": 1.8,
        "dust": 120,
        "temperature": 58,
        "vibration": 3.8,
        "ventilation_status": "moderate",
        "last_analysis": "Demo state",
    },
    "Storage Area": {
        "methane": 0.4,
        "dust": 35,
        "temperature": 34,
        "vibration": 1.8,
        "ventilation_status": "good",
        "last_analysis": "Demo state",
    },
}

INITIAL_ALERTS = [
    {
        "id": "ALERT-0001",
        "timestamp": "09:12:05",
        "zone": "Conveyor Zone",
        "severity": "MEDIUM",
        "rule_ids": [],
        "ai_confidence": 74.0,
        "reason": "AI identified an elevated mechanical-risk pattern in the conveyor zone.",
        "action": "Schedule a machinery inspection for the conveyor motor.",
        "status": "Open",
    },
    {
        "id": "ALERT-0002",
        "timestamp": "08:47:41",
        "zone": "Processing Area",
        "severity": "HIGH",
        "rule_ids": [],
        "ai_confidence": 81.0,
        "reason": "AI identified elevated workforce-safety risk in the processing area.",
        "action": "Stop work in the area and verify personnel PPE compliance.",
        "status": "Acknowledged",
    },
]

INITIAL_COMPLIANCE_CHECKS = [
    {
        "check": "PPE inspection",
        "status": "Compliant",
        "last_checked": "Today",
        "action": "-",
    },
    {
        "check": "Ventilation check",
        "status": "Warning",
        "last_checked": "Today",
        "action": "Review",
    },
    {
        "check": "Equipment inspection",
        "status": "Pending",
        "last_checked": "Yesterday",
        "action": "Inspect",
    },
    {
        "check": "Safety checklist",
        "status": "Compliant",
        "last_checked": "Today",
        "action": "-",
    },
]

INITIAL_AUDIT_LOG = [
    {
        "timestamp": "08:47:41",
        "event": "Alert generated",
        "detail": "HIGH AI risk alert created for Processing Area (81% confidence).",
    },
    {
        "timestamp": "08:50:02",
        "event": "Alert acknowledged",
        "detail": "ALERT-0002 acknowledged by Safety Officer.",
    },
    {
        "timestamp": "09:12:05",
        "event": "Alert generated",
        "detail": "MEDIUM AI risk alert created for Conveyor Zone (74% confidence).",
    },
]
