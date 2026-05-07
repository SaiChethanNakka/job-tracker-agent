"""
resume_parser.py
Extracts text from PDF resumes and uses Groq API to analyze keywords, tone, and gaps.
"""

import json
import logging
import os
from typing import Optional

import fitz  # PyMuPDF
from groq import Groq

logger = logging.getLogger(__name__)

RESUME_ANALYSIS_PROMPT = """You are a senior technical resume analyst.
Analyze this resume text and extract structured metadata.
Respond with valid JSON only - no markdown fences, no explanation.

RESUME TEXT:
{resume_text}

Return this exact JSON:
{{
  "keywords": ["list of every technical skill, tool, framework, language, platform mentioned"],
  "tone": "one-sentence description of the resume's overall tone and writing style",
  "experience_level": "one of: junior | mid | mid-senior | senior | staff | principal",
  "key_sections": {{
    "summary": "brief summary of what the resume's summary/objective says",
    "experience": "brief summary of work experience highlights",
    "skills": "brief summary of skills section",
    "education": "brief summary of education"
  }},
  "known_gaps": ["common skills/tools expected for this experience level that are NOT mentioned in the resume"]
}}
"""


class ResumeParser:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set.")
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract all text from a PDF file."""
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip()
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            raise

    def extract_text_from_bytes(self, pdf_bytes: bytes) -> str:
        """Extract all text from PDF bytes (for file upload)."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip()
        except Exception as e:
            logger.error(f"PDF extraction from bytes failed: {e}")
            raise

    def analyze_resume(self, resume_text: str) -> dict:
        """Send resume text to Groq for keyword/tone/gap analysis."""
        # Cap text to avoid exceeding token limits
        truncated = resume_text[:6000]

        prompt = RESUME_ANALYSIS_PROMPT.format(resume_text=truncated)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Resume analysis failed: {e}")
            return {
                "keywords": [],
                "tone": "Could not analyze",
                "experience_level": "unknown",
                "key_sections": {},
                "known_gaps": [],
            }

    def parse_and_analyze(self, pdf_path: Optional[str] = None, pdf_bytes: Optional[bytes] = None) -> dict:
        """
        Full pipeline: extract text from PDF, then analyze with AI.
        Provide either pdf_path or pdf_bytes.
        Returns dict with: raw_text, keywords, tone, experience_level, key_sections, known_gaps
        """
        if pdf_bytes:
            raw_text = self.extract_text_from_bytes(pdf_bytes)
        elif pdf_path:
            raw_text = self.extract_text_from_pdf(pdf_path)
        else:
            raise ValueError("Provide either pdf_path or pdf_bytes.")

        analysis = self.analyze_resume(raw_text)

        return {
            "raw_text": raw_text,
            "keywords": analysis.get("keywords", []),
            "tone": analysis.get("tone", ""),
            "experience_level": analysis.get("experience_level", "unknown"),
            "key_sections": analysis.get("key_sections", {}),
            "known_gaps": analysis.get("known_gaps", []),
        }
