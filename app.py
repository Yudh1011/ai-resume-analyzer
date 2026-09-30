"""
app.py — Streamlit user interface for the AI Resume Analyzer.

Run it with:
    streamlit run app.py

This file is deliberately thin: it only draws widgets and calls functions from
core.py. All the real logic (text extraction, prompts, JSON parsing, scoring)
lives in core.py so it can be unit-tested.
"""

from __future__ import annotations

import json

import streamlit as st

import core

# ===========================================================================
# CONFIGURATION
# ===========================================================================

from ui_common import (
    apply_page_config,
    describe_api_error,
    render_sidebar_settings,
    render_skill_list,
    score_gauge,
)

apply_page_config("AI Resume Analyzer")

# ===========================================================================
# SIDEBAR (shared with the Compare & Rank page)
# ===========================================================================

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
    '<div class="main-title">AI Resume Analyzer &amp; Job Matcher</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="subtitle">Analyze a resume against a job description using Generative AI.</div>',
    unsafe_allow_html=True,
)

if demo_mode:
    st.info(
        "**Demo mode is ON** — results come from a deterministic keyword rule "
        "engine, not from the LLM. Add your Groq API key to get the full AI analysis.",
        icon="🧪",
    )

# ===========================================================================
# INPUTS
# ===========================================================================

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Resume")
    uploaded_file = st.file_uploader(
        "Upload a resume",
        type=["pdf", "docx", "txt"],
        help="Text-based PDF, Word (.docx) or plain .txt",
    )

    if st.button("Use bundled sample resume", width="stretch"):
        import os as _os
        _path = _os.path.join(_os.path.dirname(__file__), "sample_data", "sample_resume.txt")
        try:
            with open(_path, encoding="utf-8") as fh:
                st.session_state["sample_resume"] = fh.read()
            st.session_state["use_sample_resume"] = True
            st.rerun()
        except FileNotFoundError:
            st.error("sample_data/sample_resume.txt not found.")

    if st.session_state.get("use_sample_resume") and not uploaded_file:
        st.caption("Using the bundled sample resume.")
        with st.expander("Preview sample resume text"):
            st.text(st.session_state.get("sample_resume", ""))

with col2:
    st.subheader("2. Job Description")
    job_description = st.text_area(
        "Paste the job description here",
        value=st.session_state.get("sample_jd", ""),
        height=250,
        placeholder="Paste the complete job description...",
    )
    st.caption(f"{len(job_description.strip())} characters")

# ===========================================================================
# ANALYZE BUTTON
# ===========================================================================

st.divider()

analyze_button = st.button("🔍 Analyze Resume", type="primary", width="stretch")


@st.cache_data(show_spinner=False)
def cached_analysis(api_key: str, model: str, temperature: float, json_mode: bool,
                    resume_text: str, job_description: str) -> dict:
    """Cached so re-rendering the page never burns another API call."""
    return core.analyze_resume(
        api_key=api_key,
        model=model,
        resume_text=resume_text,
        job_description=job_description,
        temperature=temperature,
        json_mode=json_mode,
    )


# ===========================================================================
# PROCESS
# ===========================================================================

if analyze_button:
    resume_text = ""
    resume_name = "resume"

    if uploaded_file is not None:
        resume_name = uploaded_file.name
        try:
            resume_text = core.extract_text(uploaded_file.name, uploaded_file.getvalue())
        except Exception as exc:  # noqa: BLE001
            st.error(describe_api_error(exc))
            st.stop()
    elif st.session_state.get("use_sample_resume"):
        resume_text = st.session_state.get("sample_resume", "")
        resume_name = "sample_resume.txt"

    if not resume_text.strip():
        st.warning("Please upload a resume (or load the sample data from the sidebar).")
        st.stop()

    if not job_description.strip():
        st.warning("Please enter a job description.")
        st.stop()

    resume_text = core.clean_text(resume_text)

    if len(resume_text) < core.MIN_RESUME_CHARS:
        st.error(
            "Very little text was extracted from this file "
            f"({len(resume_text)} characters). If it is a scanned PDF, run it "
            "through an OCR tool first or upload a text-based PDF."
        )
        st.stop()

    with st.spinner("Reading and analyzing resume..."):
        keywords = core.keyword_analysis(resume_text, job_description)

        if demo_mode or not api_key:
            result = core.baseline_analysis(resume_text, job_description)
            source = "Rule-based engine (demo mode - no AI used)"
        else:
            try:
                result = cached_analysis(
                    api_key, model, float(temperature), bool(json_mode),
                    resume_text, job_description,
                )
                source = f"Groq LLM · {model}"
            except Exception as exc:  # noqa: BLE001
                st.error(describe_api_error(exc))
                st.stop()

    st.session_state["analysis"] = result
    st.session_state["keywords"] = keywords
    st.session_state["resume_text"] = resume_text
    st.session_state["resume_name"] = resume_name
    st.session_state["source"] = source
    st.session_state["job_title"] = job_description.strip().splitlines()[0][:80]

    history = st.session_state.setdefault("history", [])
    history.insert(0, {
        "label": f"{resume_name} · ATS {result.get('ats_score', 0)}%",
        "analysis": result,
        "keywords": keywords,
        "source": source,
        "resume_name": resume_name,
        "job_title": st.session_state["job_title"],
    })
    st.session_state["history"] = history[:10]

# ===========================================================================
# RESULTS
# ===========================================================================

if "analysis" in st.session_state:
    result = st.session_state["analysis"]
    keywords = st.session_state.get("keywords", {})
    resume_name = st.session_state.get("resume_name", "resume")
    job_title = st.session_state.get("job_title", "Job Description")

    st.divider()
    st.header("📊 Resume Analysis Report")
    st.caption(f"Source: {st.session_state.get('source', 'AI')}")

    # ------------------------------------------------ ATS SCORE
    score = int(result.get("ats_score", 0))
    st.markdown(score_gauge(score), unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ATS Match Score", f"{score}%")
    m2.metric("Matched Skills", len(result.get("matched_skills", [])))
    m3.metric("Missing Skills", len(result.get("missing_skills", [])))
    m4.metric("Keyword Coverage", f"{keywords.get('coverage', 0)}%")

    st.progress(score / 100)

    # ------------------------------------------------ SUMMARY
    st.subheader("Candidate Summary")
    st.write(result.get("candidate_summary") or "No summary available.")

    # ------------------------------------------------ SKILLS
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("✅ Matched Skills")
        render_skill_list(result.get("matched_skills", []), "ok",
                          "No strong matches identified.")
    with col2:
        st.subheader("❌ Missing Skills")
        render_skill_list(result.get("missing_skills", []), "bad",
                          "No major missing skills identified.")

    st.subheader("⚠️ Partial Match Skills")
    render_skill_list(result.get("partial_match_skills", []), "mid",
                      "No partial matches identified.")

    # ------------------------------------------------ KEYWORD COVERAGE
    with st.expander("🔎 Deterministic keyword coverage (no AI used)"):
        if keywords:
            kc1, kc2 = st.columns(2)
            with kc1:
                st.markdown("**Skills required by the JD and found in the resume**")
                render_skill_list(keywords.get("covered", []), "ok", "None.")
            with kc2:
                st.markdown("**Skills required by the JD but missing**")
                render_skill_list(keywords.get("missing", []), "bad", "None.")
            if keywords.get("bonus"):
                st.markdown("**Extra skills in the resume (not required by this JD)**")
                render_skill_list(keywords["bonus"], "mid", "")
            st.caption(
                "This is a plain keyword scan - it never hallucinates, and it is a "
                "useful baseline for checking whether the LLM's score is sensible."
            )

    # ------------------------------------------------ STRENGTHS / WEAKNESSES
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("💪 Strengths")
        for item in result.get("strengths", []):
            st.write(f"✓ {item}")
    with col2:
        st.subheader("🚧 Weaknesses")
        for item in result.get("weaknesses", []):
            st.write(f"• {item}")

    # ------------------------------------------------ EXPERIENCE / EDUCATION / PROJECT
    e1, e2, e3 = st.columns(3)
    with e1:
        st.subheader("Experience Match")
        st.write(result.get("experience_match") or "Not available.")
    with e2:
        st.subheader("Education Match")
        st.write(result.get("education_match") or "Not available.")
    with e3:
        st.subheader("Project Match")
        st.write(result.get("project_match") or "Not available.")

    # ------------------------------------------------ IMPROVEMENTS
    st.subheader("📝 Resume Improvement Recommendations")
    for index, item in enumerate(result.get("resume_improvements", []), start=1):
        st.write(f"{index}. {item}")

    # ------------------------------------------------ INTERVIEW QUESTIONS
    st.subheader("🎤 AI-Generated Interview Questions")
    for index, question in enumerate(result.get("interview_questions", []), start=1):
        st.write(f"{index}. {question}")

    # ------------------------------------------------ GENERAL TIPS
    with st.expander("💡 Generate General Resume Improvement Tips"):
        if st.button("Generate Tips"):
            with st.spinner("Generating recommendations..."):
                try:
                    if demo_mode or not api_key:
                        tips = "\n".join(
                            f"{i}. {t}"
                            for i, t in enumerate(result.get("resume_improvements", []), 1)
                        )
                        st.info("Demo mode: showing rule-based recommendations instead of AI tips.")
                    else:
                        tips = core.generate_resume_tips(
                            api_key=api_key,
                            model=model,
                            resume_text=st.session_state["resume_text"],
                        )
                    st.write(tips)
                except Exception as exc:  # noqa: BLE001
                    st.error(describe_api_error(exc))

    # ------------------------------------------------ DOWNLOADS
    st.subheader("⬇️ Download Report")
    md_report = core.build_markdown_report(result, keywords, resume_name, job_title)
    html_report = core.build_html_report(result, keywords, resume_name, job_title)

    d1, d2, d3 = st.columns(3)
    d1.download_button(
        "Markdown (.md)",
        data=md_report,
        file_name="resume_analysis.md",
        mime="text/markdown",
        width="stretch",
    )
    d2.download_button(
        "HTML / Print to PDF",
        data=html_report,
        file_name="resume_analysis.html",
        mime="text/html",
        width="stretch",
    )
    d3.download_button(
        "Raw JSON",
        data=json.dumps(result, indent=2, ensure_ascii=False),
        file_name="resume_analysis.json",
        mime="application/json",
        width="stretch",
    )

    with st.expander("View extracted resume text"):
        st.text(st.session_state.get("resume_text", ""))

    with st.expander("View raw JSON returned by the model"):
        st.json(result)

    # ------------------------------------------------ HISTORY
    history = st.session_state.get("history", [])
    if len(history) > 1:
        with st.expander(f"🕘 Analysis history ({len(history)})"):
            chosen = st.selectbox(
                "Previous runs",
                range(len(history)),
                format_func=lambda i: history[i]["label"],
            )
            if st.button("Load this analysis"):
                entry = history[chosen]
                st.session_state["analysis"] = entry["analysis"]
                st.session_state["keywords"] = entry["keywords"]
                st.session_state["source"] = entry["source"]
                st.session_state["resume_name"] = entry["resume_name"]
                st.session_state["job_title"] = entry["job_title"]
                st.rerun()

# ===========================================================================
# FOOTER
# ===========================================================================

st.divider()
st.caption("AI Resume Analyzer | Python + Streamlit + Groq")
