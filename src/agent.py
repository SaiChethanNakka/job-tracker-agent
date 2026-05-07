"""
agent.py
Main orchestrator — runs the daily job application tracking pipeline.
Ties together: Gmail → Classifier → Tracker → Reporter
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time

# Load .env before importing modules that need env vars
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from gmail_client import GmailClient
from classifier import EmailClassifier
from tracker import ApplicationTracker
from reporter import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent.parent / "agent.log"),
    ],
)
logger = logging.getLogger("agent")

REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def run_daily_scan(days_back: int = 1):
    """
    Full daily pipeline:
    1. Fetch job emails from Gmail (last N days)
    2. Classify each email via Claude
    3. Upsert into SQLite tracker
    4. Generate and save daily report
    """
    logger.info("=" * 60)
    logger.info(f"Starting daily scan — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 60)

    tracker = ApplicationTracker()
    reporter = ReportGenerator()

    # Step 1: Gmail
    logger.info("Step 1/4 — Fetching emails from Gmail...")
    try:
        gmail = GmailClient()
        emails = gmail.fetch_job_emails(days_back=days_back)
    except FileNotFoundError as e:
        logger.error(str(e))
        return
    except Exception as e:
        logger.error(f"Gmail fetch failed: {e}")
        return

    if not emails:
        logger.info("No new job-related emails found.")
    else:
        # Step 2: Classify
        logger.info(f"Step 2/4 — Classifying {len(emails)} emails via Claude...")
        classifier = EmailClassifier()
        classified_emails = classifier.classify_batch(emails)

        # Step 3: Persist to DB
        logger.info(f"Step 3/4 — Persisting {len(classified_emails)} classified emails to DB...")
        new_events = 0
        for email in classified_emails:
            app_id = tracker.upsert_from_classified_email(email)
            if app_id:
                new_events += 1
        logger.info(f"  Stored {new_events} new events.")

    # Step 4: Generate report
    logger.info("Step 4/4 — Generating analysis report...")
    funnel_stats = tracker.get_funnel_stats()
    rejections = tracker.get_rejection_data(limit=30)

    # Load active resume data for smarter analysis
    resume_data = tracker.get_active_resume()
    version_stats = None
    if resume_data:
        version_stats = tracker.get_resume_stats(resume_data["id"])
        logger.info(f"  Using resume version: {resume_data.get('version_label', '?')}")

    analysis = reporter.generate_analysis_report(
        rejections, funnel_stats,
        resume_data=resume_data,
        version_stats=version_stats,
    )
    report_md = reporter.to_markdown(analysis, funnel_stats)

    # Save to file
    report_filename = REPORTS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    with open(report_filename, "w") as f:
        f.write(report_md)

    # Save to DB
    tracker.save_report(report_md)
    tracker.close()

    logger.info(f"Report saved: {report_filename}")
    logger.info("Daily scan complete.")
    logger.info("=" * 60)


def run_scheduler():
    """Runs agent daily at 8:00 AM local time."""
    logger.info("Job Tracker Agent started — scheduled for 08:00 AM daily.")
    logger.info("Running initial scan now...")

    run_daily_scan(days_back=7)  # Catch-up scan on first launch (last 7 days)

    schedule.every().day.at("08:00").do(run_daily_scan, days_back=1)

    while True:
        schedule.run_pending()
        time.sleep(60)


def run_once(days_back: int = 7):
    """One-shot run — used for testing or manual triggers."""
    run_daily_scan(days_back=days_back)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Job Application Tracker Agent")
    parser.add_argument(
        "--mode",
        choices=["schedule", "once"],
        default="schedule",
        help="'schedule' = run daily at 8AM | 'once' = single run and exit"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="How many days back to scan (used with --mode once)"
    )
    args = parser.parse_args()

    if args.mode == "once":
        run_once(days_back=args.days)
    else:
        run_scheduler()
