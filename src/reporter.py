"""
reporter.py
Generates AI-powered rejection analysis using Groq API.
Uses dynamic resume data when available, falls back to defaults.
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Optional

from groq import Groq

logger = logging.getLogger(__name__)

# Fallback defaults — used only when no resume has been uploaded
DEFAULT_RESUME_KEYWORDS = [
    "Java 17", "Spring Boot", "Spring WebClient", "Spring Cache",
    "Python", "FastAPI", "Kafka", "PostgreSQL", "REST APIs",
    "Microservices", "Docker", "AWS", "H2O MOJO", "CatBoost",
    "JUnit", "Gradle", "Maven", "Git", "CI/CD",
    "Machine Learning pipeline", "Credit decisioning", "Loan origination",
]

DEFAULT_KNOWN_GAPS = ["Redis", "Airflow", "Elasticsearch", "Kubernetes", "gRPC", "Spark"]

ANALYSIS_PROMPT_TEMPLATE = """You are an expert technical recruiter and resume coach 
specializing in fintech and backend engineering roles.
Analyze these job application rejections and provide actionable resume improvement advice.
Respond ONLY with a valid JSON object - no markdown fences, no preamble.

RESUME VERSION: {resume_version}
RESUME KEYWORDS: {my_keywords}
RESUME TONE: {resume_tone}
KNOWN GAPS: {known_gaps}
{version_performance}
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
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set.")
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    def generate_analysis_report(
        self,
        rejections: List[dict],
        funnel_stats: dict,
        resume_data: Optional[dict] = None,
        version_stats: Optional[dict] = None,
    ) -> dict:
        if not rejections:
            logger.info("No rejections to analyze yet.")
            return self._empty_report()

        # Use dynamic resume data if available, otherwise fall back to defaults
        if resume_data:
            keywords_list = json.loads(resume_data.get("keywords", "[]")) if isinstance(resume_data.get("keywords"), str) else resume_data.get("keywords", [])
            gaps_list = json.loads(resume_data.get("known_gaps", "[]")) if isinstance(resume_data.get("known_gaps"), str) else resume_data.get("known_gaps", [])
            resume_version = resume_data.get("version_label", "unknown")
            resume_tone = resume_data.get("tone", "not analyzed")
        else:
            keywords_list = DEFAULT_RESUME_KEYWORDS
            gaps_list = DEFAULT_KNOWN_GAPS
            resume_version = "no resume uploaded"
            resume_tone = "not analyzed"

        # Build version performance context string
        version_perf = ""
        if version_stats:
            version_perf = (
                f"RESUME VERSION PERFORMANCE: "
                f"{version_stats.get('total', 0)} applications, "
                f"{version_stats.get('rejection_rate', 0)}% rejection rate, "
                f"{version_stats.get('offer_rate', 0)}% offer rate, "
                f"{version_stats.get('advancement_rate', 0)}% advanced past initial screen"
            )

        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            resume_version=resume_version,
            my_keywords=", ".join(keywords_list),
            resume_tone=resume_tone,
            known_gaps=", ".join(gaps_list),
            version_performance=version_perf,
            count=len(rejections),
            rejections_json=json.dumps(rejections, indent=2),
            funnel_json=json.dumps(funnel_stats, indent=2),
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Report failed: {e}")
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
