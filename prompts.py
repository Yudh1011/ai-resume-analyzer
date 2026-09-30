"""
prompts.py — Every prompt the app sends to the LLM lives in this one file.

Why a separate file?
    In a GenAI project the prompt IS the product. Keeping all prompts in one
    place means you can read them, version them, and improve them without
    touching application logic. Your evaluator can open this single file and
    judge your prompt engineering.

Templates use <<MARKER>> placeholders instead of Python f-strings so that the
JSON braces { } inside the prompt do not have to be escaped.
"""

from __future__ import annotations

PROMPT_VERSION = "1.1"

# ---------------------------------------------------------------------------
# The JSON contract.
# Keeping the exact key order in one place means the prompt, the parser and
# the report all agree on the schema.
# ---------------------------------------------------------------------------
OUTPUT_SCHEMA = """{
    "ats_score": 0,
    "candidate_summary": "",
    "matched_skills": [],
    "missing_skills": [],
    "partial_match_skills": [],
    "strengths": [],
    "weaknesses": [],
    "experience_match": "",
    "education_match": "",
    "project_match": "",
    "resume_improvements": [],
    "interview_questions": []
}"""

# ---------------------------------------------------------------------------
# Scoring rubric.
# Without a rubric an LLM invents a different scale every run. Giving explicit
# bands makes the ATS score repeatable and lets you defend the number in a viva.
# ---------------------------------------------------------------------------
SCORING_RUBRIC = """SCORING RUBRIC for "ats_score" (integer 0-100):
- 85-100 : Almost every must-have requirement is clearly evidenced in the resume.
- 70-84  : Strong match. Most must-haves present, a few gaps.
- 50-69  : Moderate match. Core skills present but evidence is thin or partial.
- 30-49  : Weak match. Only some requirements are addressed.
- 0-29   : Poor match. The resume does not target this role.
Score the evidence in the resume, not the potential of the candidate."""

ANALYSIS_SYSTEM_PROMPT = (
    "You are a professional ATS (Applicant Tracking System) resume analyzer and "
    "senior technical recruiter. You return valid JSON only - no markdown, no "
    "code fences, no commentary before or after the JSON object."
)

ANALYSIS_USER_PROMPT = """You are an expert technical recruiter and ATS resume analyzer.

Analyze the candidate resume against the provided job description.

Your response MUST be valid JSON.

Return exactly this structure, with exactly these keys and no others:

<<OUTPUT_SCHEMA>>

<<SCORING_RUBRIC>>

RULES:
1. ats_score must be an integer between 0 and 100.
2. matched_skills must contain ONLY skills clearly present in BOTH the resume and the job description.
3. missing_skills must contain important job requirements that are absent from the resume.
4. partial_match_skills must contain skills that are related but not strongly demonstrated.
5. A skill may appear in only ONE of matched_skills, missing_skills or partial_match_skills.
6. Do NOT invent candidate experience, employers, dates, degrees or projects.
7. Base the analysis ONLY on the resume and job description provided below.
8. interview_questions must contain exactly 10 questions that a real interviewer would ask this candidate about this role.
9. resume_improvements must contain 5 to 8 specific, actionable recommendations.
10. Every list item must be a short string. Keep the answer concise but useful.
11. Return JSON only. Do not wrap it in markdown code fences.

SELF-CHECK before you answer:
- Re-read the resume and confirm every item in matched_skills appears in it.
- Confirm the number of interview_questions is exactly 10.
- Confirm your output starts with "{" and ends with "}".

RESUME:
<<<RESUME_TEXT>>>

JOB DESCRIPTION:
<<<JOB_DESCRIPTION>>>
"""

# ---------------------------------------------------------------------------
# Second prompt: general resume coaching (not tied to one job description).
# ---------------------------------------------------------------------------
TIPS_SYSTEM_PROMPT = (
    "You are an expert resume coach and technical recruiter who has screened "
    "thousands of engineering resumes."
)

TIPS_USER_PROMPT = """Review this resume as a professional technical recruiter.

Provide 8 practical recommendations to improve it.

Focus on:
- ATS compatibility
- Technical skills
- Project descriptions
- Achievement statements
- Keywords
- Formatting
- Quantifiable results
- Professional summary

Return ONLY a numbered list from 1 to 8. No preamble, no closing remarks.

Resume:

<<RESUME_TEXT>>
"""


def _fill(template: str, mapping: dict[str, str]) -> str:
    """Replace <<MARKER>> placeholders. Safer than str.format when the template
    contains literal JSON braces."""
    out = template
    for key, value in mapping.items():
        out = out.replace(f"<<{key}>>", value)
    return out


def build_analysis_prompt(resume_text: str, job_description: str) -> str:
    """Build the full user prompt for the resume-vs-JD analysis."""
    return _fill(
        ANALYSIS_USER_PROMPT,
        {
            "OUTPUT_SCHEMA": OUTPUT_SCHEMA,
            "SCORING_RUBRIC": SCORING_RUBRIC,
            "RESUME_TEXT": resume_text.strip(),
            "JOB_DESCRIPTION": job_description.strip(),
        },
    )


def build_tips_prompt(resume_text: str) -> str:
    """Build the user prompt for general resume improvement tips."""
    return _fill(TIPS_USER_PROMPT, {"RESUME_TEXT": resume_text.strip()})
