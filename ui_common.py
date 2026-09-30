"""
ui_common.py — Shared Streamlit widgets used by every page.

Streamlit multipage apps run each file in `pages/` independently, so the sidebar
settings (API key, demo mode, model, temperature) live here and are reused by
both `app.py` and `pages/1_Compare_and_Rank.py`.
"""

from __future__ import annotations

import math
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Groq retires models every few months (llama-3.3-70b-versatile was shut down
# for free accounts on 2026-08-16). This list is only a fallback; when a key is
# present the app asks Groq for the live list instead (see get_model_options).
FALLBACK_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]


def get_model_options(api_key: str) -> list[str]:
    """Return the models the user's Groq account can actually call right now.

    Queries the Groq Models API for the live list so the dropdown never offers a
    retired model. Falls back to FALLBACK_MODELS when there is no key or the
    request fails (offline). Result is cached in session_state per key.
    """
    cached = st.session_state.get("model_options")
    if cached and st.session_state.get("model_options_key") == api_key:
        return cached

    options = None
    if api_key:
        try:
            from groq import Groq

            live = [m.id for m in Groq(api_key=api_key).models.list()]
            live = [m for m in live if not m.startswith(("whisper-", "canopylabs/"))]
            if live:
                options = live
        except Exception:  # noqa: BLE001 - any failure just means use fallback
            options = None

    options = options or list(FALLBACK_MODELS)
    st.session_state["model_options"] = options
    st.session_state["model_options_key"] = api_key
    return options

APP_CSS = """
<style>
.main-title { font-size: 42px; font-weight: 700; margin-bottom: 5px; }
.subtitle   { font-size: 18px; color: #666; margin-bottom: 25px; }
.gauge-wrap {
    display: flex; align-items: center; gap: 18px; padding: 18px 22px;
    border: 1px solid #e5e7eb; border-radius: 12px; background: #fafafa;
    margin-bottom: 18px;
}
.gauge-label { font-size: 15px; color: #374151; }
.gauge-big   { font-size: 26px; font-weight: 700; color: #111827; }
.skill-pill {
    display: inline-block; padding: 4px 10px; margin: 3px 4px 3px 0;
    border-radius: 999px; font-size: 13px; border: 1px solid #e5e7eb; background: #fff;
}
.pill-ok  { background: #ecfdf5; border-color: #a7f3d0; color: #065f46; }
.pill-bad { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.pill-mid { background: #fffbeb; border-color: #fde68a; color: #92400e; }
.rank-hero {
    padding: 20px 24px; border-radius: 12px; margin-bottom: 18px;
    background: linear-gradient(90deg,#ecfdf5,#f0fdf4);
    border: 1px solid #a7f3d0;
}
</style>
"""


def apply_page_config(title: str) -> None:
    st.set_page_config(page_title=title, page_icon="📄", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)


def get_api_key() -> str:
    """API key precedence: sidebar input > session_state > .env file."""
    return (
        st.session_state.get("api_key_override")
        or os.getenv("GROQ_API_KEY")
        or ""
    ).strip()


def render_sidebar_settings() -> dict:
    """Draw the shared settings sidebar and return the current configuration."""
    import prompts

    with st.sidebar:
        st.header("⚙️ Settings")

        if os.getenv("GROQ_API_KEY"):
            st.success("API key loaded from `.env`")
        else:
            st.warning("No API key found in `.env`")

        key_input = st.text_input(
            "Groq API key (optional override)",
            type="password",
            placeholder="gsk_...",
            help="Paste a key here to use it for this session without editing .env.",
        )
        if key_input:
            st.session_state["api_key_override"] = key_input.strip()

        api_key = get_api_key()

        st.divider()

        demo_mode = st.checkbox(
            "Demo mode (no API key)",
            value=not api_key,
            help=(
                "Uses a deterministic rule-based analyzer instead of the LLM. "
                "Great for showing the UI before you have a Groq key."
            ),
        )

        model = st.selectbox(
            "Groq model",
            get_model_options(api_key),
            index=0,
            disabled=demo_mode,
            help="Live list of models your Groq account can call. If one is "
                 "retired, pick another - openai/gpt-oss-120b works on free tiers.",
        )

        temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.0,
            value=0.2,
            step=0.1,
            disabled=demo_mode,
            help="Low = consistent and factual (best for scoring). High = more creative.",
        )

        json_mode = st.toggle(
            "Structured JSON output",
            value=True,
            disabled=demo_mode,
            help="Asks Groq for guaranteed-valid JSON. Turn off if your model rejects it.",
        )

        st.divider()

        if st.button("📥 Load sample job description", width="stretch"):
            sample_dir = os.path.join(os.path.dirname(__file__), "sample_data")
            try:
                with open(os.path.join(sample_dir, "job_description.txt"), encoding="utf-8") as fh:
                    st.session_state["sample_jd"] = fh.read()
                st.toast("Sample job description loaded")
                st.rerun()
            except FileNotFoundError:
                st.error("sample_data files not found.")

        st.divider()
        st.caption(
            f"**Stack:** Python · Streamlit · Groq LLM · PyPDF · Prompt Engineering "
            f"(prompts v{prompts.PROMPT_VERSION})"
        )

    return {
        "api_key": api_key,
        "demo_mode": bool(demo_mode),
        "model": model,
        "temperature": float(temperature),
        "json_mode": bool(json_mode),
    }


def score_gauge(score: int) -> str:
    """A self-contained SVG donut gauge (no external libraries needed)."""
    score = max(0, min(100, int(score)))
    radius = 54
    circumference = 2 * math.pi * radius
    filled = circumference * score / 100
    if score >= 75:
        color, verdict = "#16a34a", "Strong match"
    elif score >= 50:
        color, verdict = "#d97706", "Moderate match"
    else:
        color, verdict = "#dc2626", "Needs work"

    return f"""
    <div class="gauge-wrap">
      <svg width="130" height="130" viewBox="0 0 130 130">
        <circle cx="65" cy="65" r="{radius}" fill="none" stroke="#e5e7eb" stroke-width="12"/>
        <circle cx="65" cy="65" r="{radius}" fill="none" stroke="{color}" stroke-width="12"
                stroke-linecap="round" stroke-dasharray="{filled:.2f} {circumference:.2f}"
                transform="rotate(-90 65 65)"/>
        <text x="65" y="62" text-anchor="middle" font-size="30" font-weight="700"
              fill="{color}">{score}</text>
        <text x="65" y="82" text-anchor="middle" font-size="12" fill="#6b7280">out of 100</text>
      </svg>
      <div>
        <div class="gauge-label">ATS Match Score</div>
        <div class="gauge-big">{verdict}</div>
        <div class="gauge-label">{score}% compatibility with this job description.</div>
      </div>
    </div>
    """


def pills(items: list[str], kind: str) -> str:
    if not items:
        return "_None identified._"
    return "".join(
        f'<span class="skill-pill pill-{kind}">{item}</span>' for item in items
    )


def render_skill_list(items: list[str], kind: str, empty_text: str) -> None:
    if items:
        st.markdown(pills(items, kind), unsafe_allow_html=True)
    else:
        st.caption(empty_text)


def describe_api_error(exc: Exception) -> str:
    """Turn a raw Groq exception into advice a beginner can act on."""
    text = str(exc).lower()
    if "invalid api key" in text or "authentication" in text or "401" in text:
        return (
            "Groq rejected the API key. Open https://console.groq.com/keys, "
            "copy a key that starts with `gsk_`, and paste it into the sidebar "
            "(or into your .env file), then rerun the app."
        )
    if "rate limit" in text or "429" in text:
        return (
            "Groq rate limit reached. The free tier allows a limited number of "
            "requests per minute and per day - wait a minute and try again."
        )
    if "model" in text and ("not found" in text or "does not exist" in text):
        return (
            "That model is not available on your Groq account. Pick a different "
            "model in the sidebar - `llama-3.3-70b-versatile` works for most "
            "free accounts."
        )
    if "context" in text or "too long" in text or "tokens" in text:
        return "The resume + job description is too long for the model. Shorten the job description."
    return f"Error: {exc}"
