"""Ad-hoc smoke test of the analytics layer (not part of the shipped test suite)."""
import json
import sys

from analytics.base import resolve_window
from analytics.forecast import get_forecast
from analytics.pipeline import get_pipeline_status
from analytics.quality import get_data_quality
from analytics.retention import get_retention

w = resolve_window(preset_days=90)
print("WINDOW", w.as_dict())

f = get_forecast(w)
print("FORECAST history", len(f["history"]), "forecast", len(f["forecast"]), "mape", f["model"]["mape"])
print("SUMMARY", json.dumps(f["summary"]))
print("ANOMALIES", len(f.get("anomalies", [])))
print("SAMPLE", json.dumps(f["forecast"][:2], indent=1))

r = get_retention(w)
print("RETENTION cohorts", len(r["cohorts"]), "curve", r["retention_curve"][:3], "repeat", r["repeat_rate"], "churn", r["churn_rate"])

p = get_pipeline_status()
print("PIPELINE status", p["status"], "metrics", json.dumps(p["metrics"]))
print("TOPICS", json.dumps(p["topics"]))
print("LAYERS", json.dumps(p["layers"]))
print("DAGS", len(p["orchestration"]))

q = get_data_quality()
print("QUALITY", q["score"], json.dumps(q["summary"]))
if q.get("note"):
    print("NOTE", q["note"])
