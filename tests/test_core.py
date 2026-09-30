"""
Tests for core.py — the non-UI logic of the AI Resume Analyzer.

Run from the project root:
    python -m pytest tests/ -v

No API key and no internet connection are required.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import prompts  # noqa: E402

SAMPLE_DIR = ROOT / "sample_data"
SAMPLE_RESUME_PDF = SAMPLE_DIR / "sample_resume.pdf"
SAMPLE_RESUME_TXT = SAMPLE_DIR / "sample_resume.txt"
SAMPLE_JD = SAMPLE_DIR / "job_description.txt"


def sample_resume_text() -> str:
    return SAMPLE_RESUME_TXT.read_text(encoding="utf-8")


def sample_jd_text() -> str:
    return SAMPLE_JD.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# clean_text
# --------------------------------------------------------------------------
def test_clean_text_collapses_whitespace():
    assert core.clean_text("  hello \n\n  world   ") == "hello world"


def test_clean_text_handles_empty():
    assert core.clean_text("") == ""
    assert core.clean_text(None) == ""  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# truncate_for_llm
# --------------------------------------------------------------------------
def test_truncate_for_llm_caps_length():
    out = core.truncate_for_llm("x" * 5000, max_chars=100)
    assert len(out) < 200
    assert out.endswith("[text truncated]")


def test_truncate_for_llm_leaves_short_text_alone():
    assert core.truncate_for_llm("short") == "short"


# --------------------------------------------------------------------------
# parse_json_response
# --------------------------------------------------------------------------
def test_parse_plain_json():
    assert core.parse_json_response('{"ats_score": 80}') == {"ats_score": 80}


def test_parse_json_wrapped_in_markdown_fence():
    content = '```json\n{"ats_score": 72, "matched_skills": ["Python"]}\n```'
    parsed = core.parse_json_response(content)
    assert parsed["ats_score"] == 72
    assert parsed["matched_skills"] == ["Python"]


def test_parse_json_with_surrounding_prose():
    content = (
        "Sure! Here is the analysis you asked for:\n\n"
        '{"ats_score": 65, "strengths": ["clear writing"]}\n\n'
        "Let me know if you want changes."
    )
    parsed = core.parse_json_response(content)
    assert parsed["ats_score"] == 65


def test_parse_json_repairs_trailing_comma():
    content = '{"ats_score": 90, "matched_skills": ["Python", "SQL",],}'
    parsed = core.parse_json_response(content)
    assert parsed["ats_score"] == 90


def test_parse_json_raises_on_garbage():
    with pytest.raises(ValueError):
        core.parse_json_response("I cannot help with that.")


def test_parse_json_raises_on_empty():
    with pytest.raises(ValueError):
        core.parse_json_response("   ")


# --------------------------------------------------------------------------
# normalize_analysis
# --------------------------------------------------------------------------
def test_normalize_fills_every_schema_key():
    result = core.normalize_analysis({})
    for key in core.SCHEMA:
        assert key in result


def test_normalize_clamps_score():
    assert core.normalize_analysis({"ats_score": 480})["ats_score"] == 100
    assert core.normalize_analysis({"ats_score": -5})["ats_score"] == 0
    assert core.normalize_analysis({"ats_score": "78.6"})["ats_score"] == 79


def test_normalize_coerces_comma_string_to_list():
    result = core.normalize_analysis({"matched_skills": "Python, SQL , Git"})
    assert result["matched_skills"] == ["Python", "SQL", "Git"]


def test_normalize_coerces_dict_list_items():
    result = core.normalize_analysis(
        {"matched_skills": [{"skill": "Python"}, {"skill": "SQL"}]}
    )
    assert result["matched_skills"] == ["Python", "SQL"]


def test_normalize_coerces_string_field_from_list():
    result = core.normalize_analysis({"experience_match": ["2 years", "of Python"]})
    assert result["experience_match"] == "2 years of Python"


def test_normalize_preserves_extra_keys():
    result = core.normalize_analysis({"extra_note": "hello"})
    assert result["extra_note"] == "hello"


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------
def test_extract_text_txt():
    data = SAMPLE_RESUME_TXT.read_bytes()
    text = core.extract_text("sample_resume.txt", data)
    assert "ARJUN NAIR" in text
    assert "Python" in text


def test_extract_text_pdf_from_sample_file():
    """Exercises the real pypdf code path against the shipped sample PDF."""
    assert SAMPLE_RESUME_PDF.exists(), "sample_resume.pdf is missing from sample_data/"
    text = core.extract_text("sample_resume.pdf", SAMPLE_RESUME_PDF.read_bytes())
    assert len(text) > core.MIN_RESUME_CHARS
    assert "Python" in text


def test_extract_text_docx_roundtrip():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("ARJUN NAIR")
    document.add_paragraph("Skills: Python, SQL, Git")
    buf = io.BytesIO()
    document.save(buf)
    text = core.extract_text("resume.docx", buf.getvalue())
    assert "ARJUN NAIR" in text
    assert "Python" in text


def test_extract_text_rejects_unknown_extension():
    with pytest.raises(ValueError):
        core.extract_text("resume.exe", b"MZ...")


def test_extract_text_rejects_corrupt_pdf():
    with pytest.raises(ValueError):
        core.extract_text("resume.pdf", b"this is definitely not a pdf")


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
def test_analysis_prompt_embeds_inputs_and_markers_resolved():
    prompt = prompts.build_analysis_prompt("RESUME BODY HERE", "JD BODY HERE")
    assert "RESUME BODY HERE" in prompt
    assert "JD BODY HERE" in prompt
    assert "<<RESUME_TEXT>>" not in prompt
    assert "<<JOB_DESCRIPTION>>" not in prompt
    assert "<<OUTPUT_SCHEMA>>" not in prompt
    assert "<<SCORING_RUBRIC>>" not in prompt


def test_analysis_prompt_declares_every_schema_key():
    prompt = prompts.build_analysis_prompt("r", "j")
    for key in core.SCHEMA:
        assert f'"{key}"' in prompt, f"prompt is missing schema key {key}"


def test_tips_prompt_embeds_resume():
    prompt = prompts.build_tips_prompt("MY RESUME TEXT")
    assert "MY RESUME TEXT" in prompt
    assert "<<RESUME_TEXT>>" not in prompt


# --------------------------------------------------------------------------
# Keyword analysis
# --------------------------------------------------------------------------
def test_keyword_analysis_finds_overlap_and_gaps():
    kw = core.keyword_analysis(sample_resume_text(), sample_jd_text())
    assert "Python" in kw["covered"]
    assert "SQL" in kw["covered"]
    assert "MySQL" in kw["covered"]
    assert "Docker" in kw["missing"]
    assert "AWS" in kw["missing"]
    assert 0 < kw["coverage"] <= 100


def test_keyword_analysis_detects_phrases_and_aliases():
    assert "Object Oriented Programming" in core.extract_skill_terms(
        "Strong grasp of OOP and object oriented programming."
    )
    assert "REST APIs" in core.extract_skill_terms("Built RESTful APIs with Flask.")
    assert "Git" in core.extract_skill_terms("Used GitHub for version control.")


def test_keyword_analysis_coverage_zero_when_no_overlap():
    kw = core.keyword_analysis("Nothing relevant here at all.", sample_jd_text())
    assert kw["coverage"] == 0
    assert kw["covered"] == []


def test_keyword_analysis_empty_jd_is_safe():
    kw = core.keyword_analysis("python sql", "")
    assert kw["coverage"] == 0
    assert kw["jd_skills"] == []


# --------------------------------------------------------------------------
# Baseline (no-API) analysis
# --------------------------------------------------------------------------
def test_baseline_analysis_is_schema_valid():
    result = core.baseline_analysis(sample_resume_text(), sample_jd_text())
    for key in core.SCHEMA:
        assert key in result
    assert 0 <= result["ats_score"] <= 100
    assert len(result["interview_questions"]) == 10


def test_baseline_analysis_flags_missing_skills():
    result = core.baseline_analysis(sample_resume_text(), sample_jd_text())
    assert "Docker" in result["missing_skills"]


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
def test_markdown_report_contains_score_and_sections():
    analysis = core.normalize_analysis(
        {"ats_score": 82, "matched_skills": ["Python", "SQL"], "missing_skills": ["Docker"]}
    )
    md = core.build_markdown_report(analysis, resume_name="arjun.pdf", job_title="Trainee SWE")
    assert "82/100" in md
    assert "arjun.pdf" in md
    assert "Trainee SWE" in md
    assert "## Matched Skills" in md
    assert "Python" in md


def test_html_report_is_self_contained():
    analysis = core.normalize_analysis({"ats_score": 44, "matched_skills": ["Git"]})
    html = core.build_html_report(analysis, resume_name="r.pdf")
    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html
    assert "http://" not in html and "https://" not in html
    assert "44%" in html


def test_html_report_escapes_html_injection():
    analysis = core.normalize_analysis(
        {"candidate_summary": "<script>alert('xss')</script>"}
    )
    html = core.build_html_report(analysis)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


# --------------------------------------------------------------------------
# Multi-resume: name detection, ranking, CSV export
# --------------------------------------------------------------------------
def test_guess_candidate_name_from_sample():
    assert core.guess_candidate_name(sample_resume_text()) == "Arjun Nair"


def test_guess_candidate_name_uppercase_is_title_cased():
    assert core.guess_candidate_name("PRIYA SHARMA\nSkills: Python") == "Priya Sharma"


def test_guess_candidate_name_falls_back():
    assert core.guess_candidate_name("Skills: Python\nExperience: 2 years", "x.pdf") == "x.pdf"
    assert core.guess_candidate_name("", "empty.pdf") == "empty.pdf"


def test_guess_candidate_name_skips_email_and_heading_lines():
    text = "RESUME\narjun@example.com\n+91 98470 00000\nArjun Nair\nPython developer"
    assert core.guess_candidate_name(text) == "Arjun Nair"


def test_rank_candidates_orders_best_first():
    ranked = core.rank_candidates([
        {"name": "B", "ats_score": 60, "matched_count": 3, "coverage": 50},
        {"name": "A", "ats_score": 80, "matched_count": 5, "coverage": 70},
    ])
    assert [r["name"] for r in ranked] == ["A", "B"]
    assert [r["rank"] for r in ranked] == [1, 2]


def test_rank_candidates_uses_competition_ranking_on_ties():
    ranked = core.rank_candidates([
        {"name": "A", "ats_score": 80, "matched_count": 5, "coverage": 70},
        {"name": "B", "ats_score": 80, "matched_count": 5, "coverage": 70},
        {"name": "C", "ats_score": 60, "matched_count": 3, "coverage": 50},
    ])
    assert [r["rank"] for r in ranked] == [1, 1, 3]


def test_rank_candidates_tiebreaks_on_matched_then_coverage():
    ranked = core.rank_candidates([
        {"name": "LowCov", "ats_score": 70, "matched_count": 4, "coverage": 40},
        {"name": "HighCov", "ats_score": 70, "matched_count": 4, "coverage": 90},
    ])
    assert ranked[0]["name"] == "HighCov"


def test_rank_candidates_handles_empty_list():
    assert core.rank_candidates([]) == []


def test_build_comparison_csv_headers_and_rows():
    ranked = core.rank_candidates([{
        "name": "Arjun Nair", "file_name": "a.pdf", "ats_score": 80,
        "matched_count": 5, "missing_count": 1, "coverage": 70,
        "matched_skills": ["Python", "SQL"], "missing_skills": ["Docker"],
        "source": "keyword rules",
    }])
    csv_text = core.build_comparison_csv(ranked)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert lines[0].startswith("Rank,Candidate,File,ATS Score")
    assert "Arjun Nair" in lines[1]
    assert "Python; SQL" in lines[1]
    assert len(lines) == 2


def test_build_skill_matrix_csv():
    ranked = [
        {"name": "A", "keywords": {"jd_skills": ["Python", "Docker"], "covered": ["Python"]}},
        {"name": "B", "keywords": {"jd_skills": ["Python", "Docker"], "covered": ["Python", "Docker"]}},
    ]
    csv_text = core.build_skill_matrix_csv(ranked)
    lines = csv_text.splitlines()
    assert lines[0] == "Required skill,A,B"
    assert "Docker,NO,YES" in lines
    assert "Python,YES,YES" in lines


def test_build_skill_matrix_csv_empty_is_safe():
    assert core.build_skill_matrix_csv([]).splitlines()[0] == "Required skill"
