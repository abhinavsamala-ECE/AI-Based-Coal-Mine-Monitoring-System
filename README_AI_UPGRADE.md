# Coal Mine Monitor — AI Operations Upgrade

This build replaces the prototype risk classification path with a trained scikit-learn Random Forest model and adds a connected AI operations layer.

## Included

- Live simulated mine telemetry across 17 model features
- Mine-wide + zone-level ML risk predictions
- Risk probability, confidence and learned feature explanations
- Worker digital-twin indicators
- Simulated computer-vision camera events
- What-if scenario simulator
- Emergency evacuation route simulator
- Simulated ambulance / fire-response tracker
- Incident replay timeline
- AI Safety Copilot driven by the current model state
- Persistent CSV sensor history, camera events and incident history
- Synthetic labelled training dataset
- Automatic model retraining after additional labelled synthetic observations accumulate
- Genuine Three.js 3D mine scene retained, with live zone risk colours

## Data layout

`data/risk_training.csv` — initial synthetic labelled training set.

`data/sensor_history.csv` — live simulated observations appended while the dashboard runs.

`data/camera_events.csv` — simulated computer-vision events.

`data/incident_history.csv` — simulated incident summaries.

`models/risk_model.joblib` — trained model used for inference.

`models/model_metadata.json` — model/version/feature information.

## Run

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Important prototype note

The model and sensor streams are synthetic demonstration data. The predictions are not certified safety limits and must not be treated as an autonomous mine-control system. Real deployment would require representative mine data, domain expert validation, calibration, monitoring, human verification and safety engineering.
