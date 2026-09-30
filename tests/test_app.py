"""
End-to-end UI tests for app.py using Streamlit's own AppTest harness.

These drive the real app.py the same way a browser would - setting widgets and
clicking buttons - and assert that no exception is ever raised. Demo mode is
used, so no API key and no internet connection are required.

Run from the project root:
    python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = str(ROOT / "app.py")
PDF = ROOT / "sample_data" / "sample_resume.pdf"
JD = (ROOT / "sample_data" / "job_description.txt").read_text(encoding="utf-8")

# Sidebar warnings about a missing .env key are expected in CI and are not errors.
IGNORABLE = "No API key found"


def real_exceptions(at: AppTest) -> list:
    return [e for e in at.exception if IGNORABLE not in str(e.value)]


def boot(demo_mode: bool = True) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not real_exceptions(at), real_exceptions(at)
    if demo_mode:
        at.checkbox[0].set_value(True).run()
        assert not real_exceptions(at), real_exceptions(at)
    return at


def analyze_button(at: AppTest):
    return [b for b in at.button if "Analyze" in b.label][0]


def click_sample_jd(at: AppTest) -> AppTest:
    return [b for b in at.button if "job description" in b.label.lower()][0].click().run()


def click_sample_resume(at: AppTest) -> AppTest:
    return [b for b in at.button if "sample resume" in b.label.lower()][0].click().run()


# --------------------------------------------------------------------------
def test_app_boots_without_exceptions():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not real_exceptions(at), real_exceptions(at)
    assert any("AI Resume Analyzer" in m.value for m in at.markdown)
    assert at.selectbox[0].value == "openai/gpt-oss-120b"
    assert len(at.button) == 3


def test_sample_jd_button_loads_job_description():
    at = boot()
    click_sample_jd(at)
    assert not real_exceptions(at), real_exceptions(at)
    assert "Trainee Software Engineer" in at.text_area[0].value


def test_sample_resume_button_loads_resume_text():
    at = boot()
    click_sample_resume(at)
    assert not real_exceptions(at), real_exceptions(at)
    assert at.session_state["use_sample_resume"] is True
    assert "ARJUN NAIR" in at.session_state["sample_resume"]


def test_full_analysis_via_sample_data():
    at = boot()
    click_sample_jd(at)
    click_sample_resume(at)
    analyze_button(at).click().run()

    assert not real_exceptions(at), real_exceptions(at)

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["ATS Match Score"].endswith("%")
    assert int(metrics["Matched Skills"]) > 0
    assert int(metrics["Missing Skills"]) > 0

    heads = [h.value for h in at.subheader]
    for expected in (
        "Candidate Summary",
        "Matched Skills",
        "Missing Skills",
        "Strengths",
        "Weaknesses",
        "Experience Match",
        "Resume Improvement Recommendations",
        "AI-Generated Interview Questions",
        "Download Report",
    ):
        assert any(expected in h for h in heads), f"missing section: {expected}"

    assert len(at.get("download_button")) == 3


def test_full_analysis_via_pdf_upload():
    """Drives the real PyPDF extraction path through the UI."""
    at = boot()
    at.get("file_uploader")[0].upload(
        "sample_resume.pdf", PDF.read_bytes(), "application/pdf"
    )
    at.text_area[0].set_value(JD).run()
    assert not real_exceptions(at), real_exceptions(at)

    analyze_button(at).click().run()
    assert not real_exceptions(at), real_exceptions(at)

    metrics = {m.label: m.value for m in at.metric}
    assert int(metrics["Matched Skills"]) >= 10
    assert 0 <= int(metrics["ATS Match Score"].rstrip("%")) <= 100
    assert len(at.subheader) == 14


def test_guardrail_warns_when_job_description_is_empty():
    at = boot()
    at.get("file_uploader")[0].upload(
        "sample_resume.pdf", PDF.read_bytes(), "application/pdf"
    )
    at.run()
    analyze_button(at).click().run()

    assert not real_exceptions(at), real_exceptions(at)
    assert any("job description" in w.value.lower() for w in at.warning)
    assert len(at.metric) == 0


def test_guardrail_warns_when_no_resume_is_uploaded():
    at = boot()
    at.text_area[0].set_value(JD).run()
    analyze_button(at).click().run()

    assert not real_exceptions(at), real_exceptions(at)
    assert any("upload a resume" in w.value.lower() for w in at.warning)
    assert len(at.metric) == 0


def test_demo_mode_checkbox_disables_model_controls():
    at = boot(demo_mode=False)
    at.checkbox[0].set_value(False).run()
    assert at.selectbox[0].proto.disabled is False
    at.checkbox[0].set_value(True).run()
    assert at.selectbox[0].proto.disabled is True


def test_history_records_the_run():
    at = boot()
    click_sample_jd(at)
    click_sample_resume(at)
    analyze_button(at).click().run()
    assert not real_exceptions(at), real_exceptions(at)
    assert "history" in at.session_state
    assert len(at.session_state["history"]) == 1
    assert "ATS" in at.session_state["history"][0]["label"]
