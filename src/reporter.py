"""
reporter.py
Generates AI-powered rejection analysis using Google Gemini (new google-genai SDK).
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Optional

from google import genai

logger = logging.getLogger(__name__)

MY_RESUME_KEYWORDS = [
    "Java 17", "Spring Boot", "Spring WebClient", "Spring Cache",
    "Python", "FastAPI", "Kafka", "PostgreSQL", "REST APIs",
    "Microservices", "Docker", "AWS", "H2O MOJO", "CatBoost",
    "JUnit", "Gradle", "Maven", "Git", "CI/CD",
    "Machine Learning pipeline", "Credit decisioning", "Loan origination",
]

KNOWN_GAPS = ["Redis", "Airflow", "Elasticsearch", "Kubernetes", "gRPC", "Spark"]

ANALYSIS_PROMPT_TEMPLATE = """You are an expert technical recruiter and resume coach 
specializing in fintech and backend engineering roles.
Analyze these job application rejections and provide actionable resume improvement advice.
Respond ONLY with a valid JSON object - no markdown fences, no preamble.

MY RESUME KEYWORDS: {my_keywords}
KNOWN GAPS: {known_gaps}
RECENT REJECTIONS ({count} total): {rejections_json}
FUNNEL STATS: {funnel_json}

Return this exact JSON:
{{
  "overall_health_score": <0-100>,
  "top_rejection_patterns": [{{"pattern": "", "frequency": "", "likely_cause": "", "severity": "HIGH"}}],
  "stage_analysis": {{"ats_drop_rate": "", "phone_screen_drop_rate": "", "interview_drop_rate": ""}},
  "keyword_gaps_found": [{{"keyword": "", "found_in": "", "resume_fix": ""}}],
  "resume_improvements": [{{"priority": "HIGH", "section": "", "current_problem": "", "suggested_fix": ""}}],
  "positive_signals": [""],
  "weekly_action_items": [""]
}}
"""


class ReportGenerator:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash"

    def generate_analysis_report(self, rejections: List[dict], funnel_stats: dict) -> dict:
        if not rejections:
            logger.info("No rejections to analyze yet.")
            return self._empty_report()

        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            my_keywords=", ".join(MY_RESUME_KEYWORDS),
            known_gaps=", ".join(KNOWN_GAPS),
            count=len(rejections),
            rejections_json=json.dumps(rejections, indent=2),
            funnel_json=json.dumps(funnel_stats, indent=2),
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            raw = response.text.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return self._empty_report()

    def to_markdown(self, analysis: dict, funnel_stats: dict, report_date: Optional[str] = None) -> str:
        date = report_date or datetime.now().strftime("%B %d, %Y")
        score = analysis.get("overall_health_score", 0)
        score_bar = self._score_bar(score)

        lines = [
            f"# Job Search Report - {date}",
            f"",
            f"## Pipeline Health: {score}/100  {score_bar}",
            f"",
            f"## Funnel Overview",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Applications | {funnel_stats.get('total', 0)} |",
            f"| Active | {funnel_stats.get('awaiting_response', 0)} |",
            f"| Phone Screens | {funnel_stats.get('phone_screens', 0)} |",
            f"| Interviews | {funnel_stats.get('interviews', 0)} |",
            f"| Rejections | {funnel_stats.get('rejected', 0)} |",
            f"| Offers | {funnel_stats.get('offers', 0)} |",
            f"",
        ]

        stage = analysis.get("stage_analysis", {})
        if stage:
            lines += [
                "## Stage Drop-off",
                f"- ATS/Pre-screen: {stage.get('ats_drop_rate', 'N/A')}",
                f"- Phone Screen: {stage.get('phone_screen_drop_rate', 'N/A')}",
                f"- Interviews: {stage.get('interview_drop_rate', 'N/A')}",
                "",
            ]

        for p in analysis.get("top_rejection_patterns", []):
            lines += [f"### [{p.get('severity')}] {p.get('pattern')}", f"- {p.get('likely_cause')}", ""]

        for g in analysis.get("keyword_gaps_found", []):
            lines += [f"### Gap: {g.get('keyword')}", f"- Fix: {g.get('resume_fix')}", ""]

        for i in analysis.get("resume_improvements", []):
            lines += [f"### [{i.get('priority')}] {i.get('section')}", f"- {i.get('suggested_fix')}", ""]

        lines += ["## Positives"] + [f"- {p}" for p in analysis.get("positive_signals", [])] + [""]
        lines += ["## Action Items"] + [f"{n+1}. {a}" for n, a in enumerate(analysis.get("weekly_action_items", []))] + [""]
        lines.append(f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

        return "\n".join(lines)

    def _score_bar(self, score: int) -> str:
        filled = score // 10
        return "#" * filled + "-" * (10 - filled)

    def _empty_report(self) -> dict:
        return {
            "overall_health_score": 0,
            "top_rejection_patterns": [],
            "stage_analysis": {},
            "keyword_gaps_found": [],
            "resume_improvements": [],
            "positive_signals": ["Not enough data yet."],
            "weekly_action_items": ["Keep applying and let the agent collect more data."],
        }
