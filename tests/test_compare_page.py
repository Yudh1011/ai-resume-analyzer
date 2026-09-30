"""
End-to-end UI tests for pages/1_Compare_and_Rank.py (recruiter mode).
Runs in demo mode, so no API key or internet is required.
"""

from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAGE = str(ROOT / "pages" / "1_Compare_and_Rank.py")
JD = (ROOT / "sample_data" / "job_description.txt").read_text(encoding="utf-8")
R1 = (ROOT / "sample_data" / "sample_resume.pdf").read_bytes()
R2 = (ROOT / "sample_data" / "sample_resume_2.pdf").read_bytes()

IGNORABLE = "No API key found"


def real_exceptions(at: AppTest) -> list:
    return [e for e in at.exception if IGNORABLE not in str(e.value)]


def boot() -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.run()
    assert not real_exceptions(at), real_exceptions(at)
    at.checkbox[0].set_value(True).run()          # demo mode on
    assert not real_exceptions(at), real_exceptions(at)
    return at


def rank_button(at: AppTest):
    return [b for b in at.button if "Rank" in b.label][0]


def test_compare_page_boots():
    at = boot()
    assert any("Compare" in m.value for m in at.markdown)
    assert at.radio[0].value.startswith("⚡")


def test_compare_warns_without_resumes():
    at = boot()
    at.text_area[0].set_value(JD).run()
    rank_button(at).click().run()
    assert not real_exceptions(at), real_exceptions(at)
    assert any("at least one resume" in w.value.lower() for w in at.warning)
    assert "comparison" not in at.session_state


def test_compare_warns_without_job_description():
    at = boot()
    up = at.get("file_uploader")[0]
    up.upload("a.pdf", R1, "application/pdf")
    up.upload("b.pdf", R2, "application/pdf")
    at.run()
    rank_button(at).click().run()
    assert not real_exceptions(at), real_exceptions(at)
    assert any("job description" in w.value.lower() for w in at.warning)


def test_compare_ranks_two_candidates():
    at = boot()
    up = at.get("file_uploader")[0]
    up.upload("arjun.pdf", R1, "application/pdf")
    up.upload("priya.pdf", R2, "application/pdf")
    at.text_area[0].set_value(JD).run()
    assert not real_exceptions(at), real_exceptions(at)

    rank_button(at).click().run()
    assert not real_exceptions(at), real_exceptions(at)

    ranked = at.session_state["comparison"]
    assert len(ranked) == 2

    # The stronger sample resume must beat the weaker one.
    assert ranked[0]["rank"] == 1
    assert ranked[0]["ats_score"] > ranked[1]["ats_score"]
    assert ranked[0]["name"] == "Arjun Nair"
    assert ranked[1]["name"] == "Priya Sharma"

    assert len(at.get("dataframe")) >= 2      # ranking table + skill matrix
    assert len(at.tabs) == 2                  # one detail tab per candidate
    assert len(at.get("download_button")) == 2
    assert any("RECOMMENDED CANDIDATE" in m.value for m in at.markdown)


def test_compare_survives_an_unreadable_file():
    at = boot()
    up = at.get("file_uploader")[0]
    up.upload("good.pdf", R1, "application/pdf")
    up.upload("broken.pdf", b"not a pdf at all", "application/pdf")
    at.text_area[0].set_value(JD).run()
    rank_button(at).click().run()

    assert not real_exceptions(at), real_exceptions(at)
    assert len(at.session_state["comparison"]) == 1
    assert any("could not be scored" in e.label for e in at.expander)


def test_compare_exports_csv():
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    import core

    at = boot()
    up = at.get("file_uploader")[0]
    up.upload("arjun.pdf", R1, "application/pdf")
    up.upload("priya.pdf", R2, "application/pdf")
    at.text_area[0].set_value(JD).run()
    rank_button(at).click().run()

    ranked = at.session_state["comparison"]
    ranking_csv = core.build_comparison_csv(ranked)
    matrix_csv = core.build_skill_matrix_csv(ranked)

    assert ranking_csv.splitlines()[0].startswith("Rank,Candidate")
    assert "Arjun Nair" in ranking_csv and "Priya Sharma" in ranking_csv
    assert matrix_csv.splitlines()[0].startswith("Required skill,")
    assert "Docker" in matrix_csv
