"""
server.py
Flask API server — serves application data to the local web dashboard.
Run separately from agent.py: python server.py
Dashboard available at: http://localhost:5050
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from flask import Flask, jsonify, send_from_directory, abort
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).parent))
from tracker import ApplicationTracker
from reporter import ReportGenerator

logger = logging.getLogger(__name__)
app = Flask(__name__, static_folder=str(Path(__file__).parent.parent / "web"))
CORS(app)

REPORTS_DIR = Path(__file__).parent.parent / "reports"


def get_tracker():
    return ApplicationTracker()


# ──────────────────────────────────────────────────────────────
#  API Endpoints
# ──────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    tracker = get_tracker()
    stats = tracker.get_funnel_stats()
    tracker.close()
    return jsonify(stats)


@app.route("/api/applications")
def api_applications():
    tracker = get_tracker()
    apps = tracker.get_all_applications()
    tracker.close()
    return jsonify(apps)


@app.route("/api/applications/<int:app_id>/events")
def api_events(app_id):
    tracker = get_tracker()
    events = tracker.get_events_for_application(app_id)
    tracker.close()
    return jsonify(events)


@app.route("/api/reports")
def api_reports():
    tracker = get_tracker()
    reports = tracker.get_recent_reports(limit=10)
    tracker.close()
    return jsonify(reports)


@app.route("/api/reports/<int:report_id>")
def api_report_detail(report_id):
    tracker = get_tracker()
    report = tracker.get_report_by_id(report_id)
    tracker.close()
    if not report:
        abort(404)
    return jsonify(report)


@app.route("/api/reports/generate", methods=["POST"])
def api_generate_report():
    """Manually trigger a report generation on demand."""
    tracker = get_tracker()
    reporter = ReportGenerator()
    funnel_stats = tracker.get_funnel_stats()
    rejections = tracker.get_rejection_data(limit=30)
    analysis = reporter.generate_analysis_report(rejections, funnel_stats)
    report_md = reporter.to_markdown(analysis, funnel_stats)
    report_id = tracker.save_report(report_md, report_type="MANUAL")

    # Also save to file
    REPORTS_DIR.mkdir(exist_ok=True)
    report_filename = REPORTS_DIR / f"{datetime.now().strftime('%Y-%m-%d-%H%M')}-manual.md"
    with open(report_filename, "w") as f:
        f.write(report_md)

    report = tracker.get_report_by_id(report_id)
    tracker.close()
    return jsonify({"success": True, "report": report})


@app.route("/api/timeline")
def api_timeline():
    """Returns all applications as a flat list for timeline visualization."""
    tracker = get_tracker()
    apps = tracker.get_all_applications()
    tracker.close()

    timeline = []
    for a in apps:
        timeline.append({
            "id": a["id"],
            "company": a["company"],
            "role": a["role"],
            "stage": a["current_stage"],
            "status": a["status"],
            "applied_date": a["applied_date"],
            "last_activity": a["last_activity_date"],
            "event_count": a["event_count"],
        })
    return jsonify(timeline)


# ──────────────────────────────────────────────────────────────
#  Dashboard Static Files
# ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    print("\n🚀 Job Tracker Dashboard running at: http://localhost:5050\n")
    app.run(host="0.0.0.0", port=5050, debug=False)
