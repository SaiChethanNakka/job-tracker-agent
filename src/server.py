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

from flask import Flask, jsonify, send_from_directory, abort, request
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).parent))
from tracker import ApplicationTracker
from reporter import ReportGenerator
from resume_parser import ResumeParser

logger = logging.getLogger(__name__)
app = Flask(__name__, static_folder=str(Path(__file__).parent.parent / "web"))
CORS(app)

REPORTS_DIR = Path(__file__).parent.parent / "reports"
RESUMES_DIR = Path(__file__).parent.parent / "resumes"
RESUMES_DIR.mkdir(exist_ok=True)


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
    """Manually trigger a report generation on demand — uses active resume data."""
    tracker = get_tracker()
    reporter = ReportGenerator()
    funnel_stats = tracker.get_funnel_stats()
    rejections = tracker.get_rejection_data(limit=30)

    # Load active resume data for the report
    resume_data = tracker.get_active_resume()
    version_stats = None
    if resume_data:
        version_stats = tracker.get_resume_stats(resume_data["id"])

    analysis = reporter.generate_analysis_report(
        rejections, funnel_stats,
        resume_data=resume_data,
        version_stats=version_stats,
    )
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
            "resume_version": a.get("resume_version"),
        })
    return jsonify(timeline)


# ──────────────────────────────────────────────────────────────
#  Resume Endpoints
# ──────────────────────────────────────────────────────────────

@app.route("/api/resume/upload", methods=["POST"])
def api_resume_upload():
    """Upload a PDF resume, extract text, analyze with AI, and save as a new version."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    version_label = request.form.get("version_label", "").strip()

    try:
        pdf_bytes = file.read()

        # Save the PDF file to disk
        safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        save_path = RESUMES_DIR / safe_name
        with open(save_path, "wb") as f:
            f.write(pdf_bytes)

        # Parse and analyze
        parser = ResumeParser()
        result = parser.parse_and_analyze(pdf_bytes=pdf_bytes)
        result["filename"] = file.filename
        if version_label:
            result["version_label"] = version_label

        # Save to database
        tracker = get_tracker()
        version_id = tracker.save_resume_version(result)
        version = tracker.get_resume_version(version_id)
        tracker.close()

        return jsonify({"success": True, "version": version})

    except Exception as e:
        logger.error(f"Resume upload failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/resume/versions")
def api_resume_versions():
    """List all resume versions with stats."""
    tracker = get_tracker()
    versions = tracker.get_all_resume_versions()
    tracker.close()
    return jsonify(versions)


@app.route("/api/resume/active")
def api_resume_active():
    """Get the currently active resume version."""
    tracker = get_tracker()
    resume = tracker.get_active_resume()
    stats = None
    if resume:
        stats = tracker.get_resume_stats(resume["id"])
    tracker.close()
    if not resume:
        return jsonify({"active": False})
    return jsonify({"active": True, "resume": resume, "stats": stats})


@app.route("/api/resume/versions/<int:version_id>")
def api_resume_version_detail(version_id):
    """Get a specific resume version with its performance stats."""
    tracker = get_tracker()
    version = tracker.get_resume_version(version_id)
    if not version:
        tracker.close()
        abort(404)
    stats = tracker.get_resume_stats(version_id)
    tracker.close()
    return jsonify({"version": version, "stats": stats})


@app.route("/api/resume/versions/<int:version_id>/activate", methods=["POST"])
def api_resume_activate(version_id):
    """Set a specific resume version as the active one."""
    tracker = get_tracker()
    success = tracker.activate_resume_version(version_id)
    tracker.close()
    if not success:
        abort(404)
    return jsonify({"success": True})


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

