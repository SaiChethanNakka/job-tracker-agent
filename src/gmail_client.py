"""
gmail_client.py
Handles Gmail OAuth2 authentication and email fetching.
Read-only scope — never modifies or labels emails.
"""

import os
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Read-only scope — this agent never writes to Gmail
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "..", "credentials.json")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "token.json")

# Gmail search queries to capture job-related emails
JOB_SEARCH_QUERIES = [
    "subject:(application received) OR subject:(thank you for applying) OR subject:(thanks for applying)",
    "subject:(we received your application) OR subject:(application submitted) OR subject:(application confirmed)",
    "subject:(application status) OR subject:(your application) OR subject:(regarding your application)",
    "subject:(interview) AND (subject:(invitation) OR subject:(schedule) OR subject:(next steps))",
    "subject:(unfortunately) OR subject:(we regret) OR subject:(not moving forward) OR subject:(other candidates)",
    "subject:(offer) AND (subject:(congratulations) OR subject:(excited to offer))",
    "from:(noreply@greenhouse.io) OR from:(noreply@lever.co) OR from:(workday) OR from:(taleo) OR from:(icims)",
    "from:(jobs-noreply@linkedin.com) OR from:(noreply@indeed.com) OR from:(jobs@glassdoor.com)",
]


class GmailClient:
    def __init__(self):
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """OAuth2 flow — opens browser on first run, auto-refreshes after."""
        creds = None

        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Gmail token...")
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_PATH):
                    raise FileNotFoundError(
                        f"credentials.json not found at {CREDENTIALS_PATH}.\n"
                        "Download it from: GCP Console → APIs & Services → Credentials → OAuth 2.0 Client"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
                logger.info("Gmail authentication successful.")

            with open(TOKEN_PATH, "w") as token_file:
                token_file.write(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail service initialized.")

    def fetch_job_emails(self, days_back: int = 1) -> List[dict]:
        """
        Fetches job-related emails from the last N days.
        Returns list of dicts with: id, subject, sender, date, body_text, snippet
        """
        cutoff = datetime.now() - timedelta(days=days_back)
        after_epoch = int(cutoff.timestamp())

        all_messages = []
        seen_ids = set()

        for query in JOB_SEARCH_QUERIES:
            full_query = f"({query}) after:{after_epoch}"
            try:
                results = self.service.users().messages().list(
                    userId="me",
                    q=full_query,
                    maxResults=50
                ).execute()

                messages = results.get("messages", [])
                for msg_ref in messages:
                    msg_id = msg_ref["id"]
                    if msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        email_data = self._fetch_message_detail(msg_id)
                        if email_data:
                            all_messages.append(email_data)

            except HttpError as e:
                logger.error(f"Gmail API error for query '{query}': {e}")
                continue

        logger.info(f"Fetched {len(all_messages)} unique job-related emails (last {days_back} day(s)).")
        return all_messages

    def _fetch_message_detail(self, message_id: str) -> Optional[dict]:
        """Fetches full message detail and extracts readable fields."""
        try:
            msg = self.service.users().messages().get(
                userId="me",
                id=message_id,
                format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "unknown")
            date_str = headers.get("Date", "")
            snippet = msg.get("snippet", "")

            body_text = self._extract_body(msg["payload"])

            return {
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "snippet": snippet,
                "body_text": body_text[:4000],  # Cap to avoid huge prompts
            }

        except HttpError as e:
            logger.error(f"Failed to fetch message {message_id}: {e}")
            return None

    def _extract_body(self, payload: dict) -> str:
        """Recursively extracts plain text body from MIME payload."""
        body_text = ""

        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        elif payload.get("mimeType", "").startswith("multipart"):
            for part in payload.get("parts", []):
                body_text += self._extract_body(part)

        return body_text
