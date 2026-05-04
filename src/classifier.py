"""
classifier.py
Uses Google Gemini API (free tier) to classify job emails and extract structured metadata.
Uses the new google-genai SDK.
"""

import json
import logging
import os
import time
from typing import Optional, List

from google import genai

logger = logging.getLogger(__name__)

EMAIL_TYPES = [
    "APPLICATION_CONFIRM",
    "RECRUITER_OUTREACH",
    "INTERVIEW_INVITE",
    "REJECTION",
    "OFFER",
    "STATUS_UPDATE",
    "IRRELEVANT",
]

CLASSIFY_PROMPT_TEMPLATE = """You are a job application email classifier.
Analyze this email and return a JSON object with these exact fields.
Respond with valid JSON only - no markdown fences, no explanation.

{{
  "email_type": "<one of: APPLICATION_CONFIRM | RECRUITER_OUTREACH | INTERVIEW_INVITE | REJECTION | OFFER | STATUS_UPDATE | IRRELEVANT>",
  "company": "<company name, or null if unclear>",
  "role": "<job title/role, or null if unclear>",
  "stage": "<APPLIED | PHONE_SCREEN | TECHNICAL | HIRING_MANAGER | OFFER | REJECTED | UNKNOWN>",
  "confidence": <0.0 to 1.0>,
  "rejection_signals": ["<rejection language found, empty if none>"],
  "next_action": "<what candidate should do next, or null>",
  "summary": "<one sentence describing this email>"
}}

Email:
Subject: {subject}
From: {sender}
Date: {date}
Snippet: {snippet}
Body: {body_text}
"""


class EmailClassifier:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set.\n"
                "Get a free key at: https://aistudio.google.com"
            )
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash"

    def classify(self, email: dict) -> Optional[dict]:
        prompt = CLASSIFY_PROMPT_TEMPLATE.format(
            subject=email.get("subject", ""),
            sender=email.get("sender", ""),
            date=email.get("date", ""),
            snippet=email.get("snippet", ""),
            body_text=email.get("body_text", "")[:2000],
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            raw = response.text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            classification = json.loads(raw)

            if classification.get("email_type") not in EMAIL_TYPES:
                classification["email_type"] = "IRRELEVANT"

            return {**email, **classification}

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                logger.warning("Rate limit hit — waiting 60 seconds before retrying...")
                time.sleep(60)
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                    )
                    raw = response.text.strip()
                    raw = raw.replace("```json", "").replace("```", "").strip()
                    classification = json.loads(raw)
                    if classification.get("email_type") not in EMAIL_TYPES:
                        classification["email_type"] = "IRRELEVANT"
                    return {**email, **classification}
                except Exception as e2:
                    logger.error(f"Retry also failed for '{email.get('subject')}': {e2}")
                    return None
            logger.error(f"Classification failed for '{email.get('subject')}': {e}")
            return None

    def classify_batch(self, emails: List[dict]) -> List[dict]:
        results = []
        for i, email in enumerate(emails):
            # Add a small delay between calls to stay under rate limits
            if i > 0:
                time.sleep(4)
            classified = self.classify(email)
            if classified and classified.get("email_type") != "IRRELEVANT":
                results.append(classified)
                logger.info(
                    f"  [{classified['email_type']}] {classified.get('company', '?')} — {classified.get('role', '?')}"
                )
        logger.info(f"Classified {len(results)} relevant emails out of {len(emails)} total.")
        return results
