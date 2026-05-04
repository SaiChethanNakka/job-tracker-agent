"""
tracker.py
SQLite persistence layer for job application tracking.
Manages application state machine: APPLIED → stages → REJECTED/OFFER
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "applications.db")

# Stage ordering for state machine advancement (never go backwards)
STAGE_ORDER = {
    "APPLIED": 0,
    "PHONE_SCREEN": 1,
    "TECHNICAL": 2,
    "HIRING_MANAGER": 3,
    "BAR_RAISER": 4,
    "OFFER": 5,
    "REJECTED": 6,
    "UNKNOWN": -1,
}

CREATE_APPLICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    current_stage TEXT DEFAULT 'APPLIED',
    status TEXT DEFAULT 'ACTIVE',   -- ACTIVE | REJECTED | OFFER | GHOSTED
    applied_date TEXT,
    last_activity_date TEXT,
    rejection_signals TEXT,         -- JSON array stored as text
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    email_id TEXT UNIQUE,           -- Gmail message ID (dedup key)
    email_type TEXT NOT NULL,
    stage TEXT,
    subject TEXT,
    sender TEXT,
    email_date TEXT,
    summary TEXT,
    next_action TEXT,
    raw_rejection_signals TEXT,     -- JSON array
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);
"""

CREATE_REPORTS_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    report_type TEXT DEFAULT 'DAILY',
    content_md TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class ApplicationTracker:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript(CREATE_APPLICATIONS_SQL + CREATE_EVENTS_SQL + CREATE_REPORTS_SQL)
        self.conn.commit()

    def upsert_from_classified_email(self, classified: dict) -> Optional[int]:
        """
        Core method: given a classified email, find or create the application record
        and append the event. Advances stage if appropriate.
        Returns application_id or None if skipped.
        """
        import json

        company = classified.get("company")
        role = classified.get("role")
        email_type = classified.get("email_type")
        stage = classified.get("stage", "UNKNOWN")
        email_id = classified.get("id")

        if not company or company == "null":
            logger.warning(f"Skipping email — no company extracted: {classified.get('subject')}")
            return None

        # Dedup: skip if we've already processed this Gmail message ID
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM application_events WHERE email_id = ?", (email_id,))
        if cursor.fetchone():
            logger.debug(f"Email {email_id} already processed, skipping.")
            return None

        # Find or create application record
        app_id = self._find_application(company, role)
        if not app_id:
            app_id = self._create_application(company, role, classified)

        # Advance stage if this email represents progression
        self._maybe_advance_stage(app_id, email_type, stage)

        # Store the event
        rejection_signals = json.dumps(classified.get("rejection_signals", []))
        cursor.execute(
            """
            INSERT INTO application_events 
                (application_id, email_id, email_type, stage, subject, sender, 
                 email_date, summary, next_action, raw_rejection_signals)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                app_id,
                email_id,
                email_type,
                stage,
                classified.get("subject"),
                classified.get("sender"),
                classified.get("date"),
                classified.get("summary"),
                classified.get("next_action"),
                rejection_signals,
            ),
        )

        # Update last_activity
        cursor.execute(
            "UPDATE applications SET last_activity_date = ?, updated_at = ? WHERE id = ?",
            (classified.get("date"), datetime.now().isoformat(), app_id),
        )
        self.conn.commit()
        return app_id

    def _find_application(self, company: str, role: Optional[str]) -> Optional[int]:
        """Fuzzy match on company name (case-insensitive). Role is optional for matching."""
        cursor = self.conn.cursor()
        if role and role != "null":
            cursor.execute(
                "SELECT id FROM applications WHERE LOWER(company) = LOWER(?) AND LOWER(role) LIKE LOWER(?) LIMIT 1",
                (company, f"%{role[:20]}%"),
            )
        else:
            cursor.execute(
                "SELECT id FROM applications WHERE LOWER(company) = LOWER(?) LIMIT 1",
                (company,),
            )
        row = cursor.fetchone()
        return row["id"] if row else None

    def _create_application(self, company: str, role: Optional[str], classified: dict) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO applications (company, role, current_stage, status, applied_date, last_activity_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                company,
                role or "Unknown Role",
                "APPLIED",
                "ACTIVE",
                classified.get("date"),
                classified.get("date"),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def _maybe_advance_stage(self, app_id: int, email_type: str, new_stage: str):
        """Only advance stage — never go backward in the state machine."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT current_stage, status FROM applications WHERE id = ?", (app_id,))
        row = cursor.fetchone()
        if not row:
            return

        current_stage = row["current_stage"]
        current_order = STAGE_ORDER.get(current_stage, 0)
        new_order = STAGE_ORDER.get(new_stage, -1)

        new_status = row["status"]
        if email_type == "REJECTION":
            new_status = "REJECTED"
            new_stage = "REJECTED"
        elif email_type == "OFFER":
            new_status = "OFFER"
            new_stage = "OFFER"

        # Only advance if new stage is further along
        if new_order > current_order or email_type in ("REJECTION", "OFFER"):
            cursor.execute(
                "UPDATE applications SET current_stage = ?, status = ?, updated_at = ? WHERE id = ?",
                (new_stage, new_status, datetime.now().isoformat(), app_id),
            )
            self.conn.commit()

    def get_all_applications(self) -> List[dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT a.*, 
                   COUNT(e.id) as event_count
            FROM applications a
            LEFT JOIN application_events e ON e.application_id = a.id
            GROUP BY a.id
            ORDER BY a.last_activity_date DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_events_for_application(self, app_id: int) -> List[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM application_events WHERE application_id = ? ORDER BY created_at DESC",
            (app_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_rejection_data(self, limit: int = 30) -> List[dict]:
        """Returns rejection events with application context for report generation."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT a.company, a.role, a.current_stage, a.applied_date, a.last_activity_date,
                   e.raw_rejection_signals, e.summary, e.email_date
            FROM applications a
            JOIN application_events e ON e.application_id = a.id
            WHERE a.status = 'REJECTED' AND e.email_type = 'REJECTION'
            ORDER BY e.email_date DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_funnel_stats(self) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status = 'OFFER' THEN 1 ELSE 0 END) as offers,
                SUM(CASE WHEN current_stage = 'PHONE_SCREEN' THEN 1 ELSE 0 END) as phone_screens,
                SUM(CASE WHEN current_stage IN ('TECHNICAL', 'HIRING_MANAGER', 'BAR_RAISER') THEN 1 ELSE 0 END) as interviews,
                SUM(CASE WHEN current_stage = 'APPLIED' AND status = 'ACTIVE' THEN 1 ELSE 0 END) as awaiting_response
            FROM applications
        """)
        return dict(cursor.fetchone())

    def save_report(self, content_md: str, report_type: str = "DAILY") -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO reports (report_date, report_type, content_md) VALUES (?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d"), report_type, content_md),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recent_reports(self, limit: int = 10) -> List[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, report_date, report_type, created_at FROM reports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_report_by_id(self, report_id: int) -> Optional[dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def close(self):
        self.conn.close()
