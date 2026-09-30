"""
pages/1_Compare_and_Rank.py — Recruiter mode.

Upload several resumes against ONE job description, score them all, and get a
ranked shortlist with a skill-by-skill comparison matrix.

Streamlit discovers any .py file inside the `pages/` folder automatically and
adds it to the sidebar navigation - no routing code needed.
"""

from __future__ import annotations

import streamlit as st

import core
from ui_common import (
    apply_page_config,
    describe_api_error,
    pills,
    render_sidebar_settings,
    render_skill_list,
)

apply_page_config("Compare & Rank Resumes")

settings = render_sidebar_settings()
api_key = settings["api_key"]
demo_mode = settings["demo_mode"]
model = settings["model"]
temperature = settings["temperature"]
json_mode = settings["json_mode"]

# ===========================================================================
# TITLE
# ===========================================================================

st.markdown(
    '<div class="main-title">Compare &amp; Rank Resumes</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="subtitle">Score many resumes against one job description and '
    "get a ranked shortlist.</div>",
    unsafe_allow_html=True,
)

if demo_mode:
    st.info(
        "**Demo mode is ON** — scores come from the deterministic keyword engine "
        "(free, instant, no hallucination). Add a Groq key and switch to AI mode "
        "for qualitative analysis of every candidate.",
        icon="🧪",
    )

# ===========================================================================
# INPUTS
# ===========================================================================

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Resumes")
    uploaded_files = st.file_uploader(
        "Select two or more resumes",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        help="Hold Ctrl (Cmd on Mac) to select several files at once.",
    )
    st.caption(f"{len(uploaded_files or [])} file(s) selected")

with col2:
    st.subheader("2. Job Description")
    job_description = st.text_area(
        "Paste the job description here",
        value=st.session_state.get("sample_jd", ""),
        height=250,
        placeholder="Paste the complete job description...",
        key="compare_jd",
    )
    st.caption(f"{len(job_description.strip())} characters")

use_ai = st.radio(
    "Scoring engine",
    ["⚡ Fast keyword rules (free, instant)", "🤖 AI analysis (Groq, one call per resume)"],
    horizontal=True,
    help=(
        "Keyword rules are free and never hallucinate. AI mode gives richer "
        "qualitative feedback but makes one API call per resume - the free Groq "
        "tier is rate limited."
    ),
)
ai_mode = use_ai.startswith("🤖")

if ai_mode and (demo_mode or not api_key):
    st.warning(
        "AI mode needs an API key and demo mode turned off. Falling back to "
        "keyword rules for this run."
    )
    ai_mode = False

st.divider()
analyze_button = st.button("🏆 Score & Rank All Resumes", type="primary", width="stretch")


# ===========================================================================
# PROCESS
# ===========================================================================

if analyze_button:
    if not uploaded_files:
        st.warning("Please upload at least one resume.")
        st.stop()
    if not job_description.strip():
        st.warning("Please enter a job description.")
        st.stop()

    entries: list[dict] = []
    failures: list[str] = []
    progress = st.progress(0.0, text="Starting...")

    for index, uploaded in enumerate(uploaded_files, start=1):
        progress.progress(
            index / len(uploaded_files),
            text=f"Scoring {uploaded.name} ({index}/{len(uploaded_files)})...",
        )

        try:
            raw_text = core.extract_text(uploaded.name, uploaded.getvalue())
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{uploaded.name}: {exc}")
            continue

        if len(core.clean_text(raw_text)) < core.MIN_RESUME_CHARS:
            failures.append(
                f"{uploaded.name}: not enough extractable text (scanned PDF?)"
            )
            continue

        name = core.guess_candidate_name(raw_text, fallback=uploaded.name)
        resume_text = core.clean_text(raw_text)
        keywords = core.keyword_analysis(resume_text, job_description)

        if ai_mode:
            try:
                analysis = core.analyze_resume(
                    api_key=api_key,
                    model=model,
                    resume_text=resume_text,
                    job_description=job_description,
                    temperature=temperature,
                    json_mode=json_mode,
                )
                source = f"AI · {model}"
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{uploaded.name}: {describe_api_error(exc)}")
                analysis = core.baseline_analysis(resume_text, job_description)
                source = "keyword rules (AI call failed)"
        else:
            analysis = core.baseline_analysis(resume_text, job_description)
            source = "keyword rules"

        entries.append({
            "name": name,
            "file_name": uploaded.name,
            "ats_score": int(analysis.get("ats_score", 0)),
            "matched_count": len(analysis.get("matched_skills", [])),
            "missing_count": len(analysis.get("missing_skills", [])),
            "coverage": int(keywords.get("coverage", 0)),
            "matched_skills": analysis.get("matched_skills", []),
            "missing_skills": analysis.get("missing_skills", []),
            "analysis": analysis,
            "keywords": keywords,
            "resume_text": resume_text,
            "source": source,
        })

    progress.empty()

    if failures:
        with st.expander(f"⚠️ {len(failures)} file(s) could not be scored"):
            for message in failures:
                st.write(f"• {message}")

    if not entries:
        st.error("No resume could be read. Check the warnings above.")
        st.stop()

    st.session_state["comparison"] = core.rank_candidates(entries)
    st.session_state["comparison_jd_title"] = job_description.strip().splitlines()[0][:80]

# ===========================================================================
# RESULTS
# ===========================================================================

if "comparison" in st.session_state:
    ranked = st.session_state["comparison"]

    st.divider()
    st.header("🏆 Candidate Ranking")
    st.caption(
        f"{len(ranked)} candidate(s) scored against: "
        f"**{st.session_state.get('comparison_jd_title', 'this role')}**"
    )

    # ------------------------------------------------ TOP CANDIDATE
    top = ranked[0]
    st.markdown(
        f"""
        <div class="rank-hero">
          <div style="font-size:13px;color:#065f46;letter-spacing:1px">RECOMMENDED CANDIDATE</div>
          <div style="font-size:28px;font-weight:700;color:#064e3b">{top['name']}</div>
          <div style="font-size:15px;color:#065f46">
            ATS {top['ats_score']}% &nbsp;·&nbsp; {top['matched_count']} matched skills
            &nbsp;·&nbsp; {top['coverage']}% keyword coverage
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------ RANKING TABLE
    st.subheader("Ranking table")
    st.dataframe(
        [
            {
                "Rank": r["rank"],
                "Candidate": r["name"],
                "File": r["file_name"],
                "ATS Score": r["ats_score"],
                "Matched": r["matched_count"],
                "Missing": r["missing_count"],
                "Keyword Coverage %": r["coverage"],
                "Scored By": r["source"],
            }
            for r in ranked
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "ATS Score": st.column_config.ProgressColumn(
                "ATS Score", min_value=0, max_value=100, format="%d%%"
            ),
            "Keyword Coverage %": st.column_config.ProgressColumn(
                "Keyword Coverage %", min_value=0, max_value=100, format="%d%%"
            ),
        },
    )

    # ------------------------------------------------ CHART
    chart_col1, chart_col2 = st.columns([3, 2])
    with chart_col1:
        st.subheader("Score comparison")
        st.bar_chart(
            {r["name"]: r["ats_score"] for r in ranked},
            horizontal=True,
            color="#2563eb",
        )
    with chart_col2:
        scores = [r["ats_score"] for r in ranked]
        st.metric("Candidates scored", len(ranked))
        st.metric("Highest score", f"{max(scores)}%")
        st.metric("Average score", f"{round(sum(scores) / len(scores))}%")
        st.metric("Score spread", f"{max(scores) - min(scores)} pts")

    # ------------------------------------------------ SKILL MATRIX
    with st.expander("🧩 Skill-by-skill comparison matrix", expanded=True):
        all_skills = sorted(
            {skill for r in ranked for skill in r["keywords"].get("jd_skills", [])}
        )
        if all_skills:
            matrix = []
            for skill in all_skills:
                row = {"Required skill": skill}
                for r in ranked:
                    row[r["name"]] = (
                        "✅" if skill in r["keywords"].get("covered", []) else "❌"
                    )
                matrix.append(row)
            st.dataframe(matrix, width="stretch", hide_index=True)
            st.caption("✅ = found in that candidate's resume · ❌ = not found")
        else:
            st.caption("No recognised skills found in the job description.")

    # ------------------------------------------------ PER-CANDIDATE DETAIL
    st.subheader("Individual reports")
    tabs = st.tabs([f"{r['rank']}. {r['name']}" for r in ranked])

    for tab, r in zip(tabs, ranked):
        with tab:
            analysis = r["analysis"]
            st.caption(
                f"**File:** {r['file_name']} · **Scored by:** {r['source']} · "
                f"**ATS:** {r['ats_score']}%"
            )
            st.write(analysis.get("candidate_summary") or "No summary available.")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**✅ Matched skills**")
                render_skill_list(r["matched_skills"], "ok", "None.")
            with c2:
                st.markdown("**❌ Missing skills**")
                render_skill_list(r["missing_skills"], "bad", "None.")

            with st.expander("Improvements & interview questions"):
                st.markdown("**Resume improvements**")
                for i, item in enumerate(analysis.get("resume_improvements", []), 1):
                    st.write(f"{i}. {item}")
                st.markdown("**Interview questions**")
                for i, q in enumerate(analysis.get("interview_questions", []), 1):
                    st.write(f"{i}. {q}")

            with st.expander("View extracted resume text"):
                st.text(r["resume_text"][:4000])

    # ------------------------------------------------ DOWNLOADS
    st.subheader("⬇️ Export")
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download ranking (CSV)",
        data=core.build_comparison_csv(ranked),
        file_name="candidate_ranking.csv",
        mime="text/csv",
        width="stretch",
    )
    d2.download_button(
        "Download skill matrix (CSV)",
        data=core.build_skill_matrix_csv(ranked),
        file_name="skill_matrix.csv",
        mime="text/csv",
        width="stretch",
    )

st.divider()
st.caption("AI Resume Analyzer | Compare & Rank | Python + Streamlit + Groq")
