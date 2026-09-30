# AI Resume Analyzer & Job Matcher

**Project 1 — Gen AI & Prompt Engineering (ExcelR)**
Python · Streamlit · Groq LLM · PyPDF · Prompt Engineering

Upload a resume, paste a job description, and the app returns an ATS-style
match score, matched/missing skills, strengths & weaknesses, concrete resume
improvements and 10 interview questions.

---

## 1. Features

| # | Feature | Notes |
|---|---------|-------|
| 1 | Resume upload | PDF, **DOCX** and **TXT** (PDF + DOCX + TXT are beyond the base spec) |
| 2 | Job description input | Paste text, with live character count |
| 3 | ATS match score | 0–100 with a coloured SVG gauge + progress bar |
| 4 | Matched / missing / partial skills | Shown as coloured pills |
| 5 | Strengths & weaknesses | Bullet lists from the LLM |
| 6 | Experience / education / project match | Three-column qualitative verdict |
| 7 | Resume improvement recommendations | 5–8 actionable items |
| 8 | Interview questions | Exactly 10, role-specific |
| 9 | **Deterministic keyword coverage** | A no-AI baseline scan to sanity-check the LLM |
| 10 | **Downloadable report** | Markdown, printable HTML (→ PDF) and raw JSON |
| 11 | **Demo mode** | Full UI with a rule-based engine, so you can demo without an API key |
| 12 | **Analysis history** | Last 10 runs kept in the session |
| 12b | **Compare & Rank page** | Score many resumes vs one JD, ranked shortlist, skill matrix, CSV export |
| 13 | Robust JSON parsing | Handles code fences, prose, trailing commas |
| 14 | Caching | Re-renders never burn a second API call |
| 15 | Unit + UI tests | 41 tests, no API key needed |

---

## 2. Project Structure

```
AI_Resume_Analyzer/
├── app.py                  # Page 1 - single resume vs job description
├── ui_common.py            # Shared sidebar + widgets used by both pages
├── core.py                 # All logic: extraction, parsing, scoring, ranking
├── prompts.py              # Every prompt in one place (versioned)
├── pages/
│   └── 1_Compare_and_Rank.py   # Page 2 - recruiter mode, multi-resume ranking
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # + pytest, pymupdf (for tests only)
├── .env.example            # Template - copy to .env
├── .gitignore
├── README.md               # This file
├── PROMPT_ENGINEERING.md   # Why each prompt is written the way it is
├── VIVA_NOTES.md           # Answers to the questions evaluators ask
├── sample_data/
│   ├── sample_resume.pdf   # Strong candidate - upload to test
│   ├── sample_resume.txt   # Same resume as plain text
│   ├── sample_resume_2.pdf # Weak candidate - for the Compare & Rank page
│   ├── sample_resume_2.txt
│   └── job_description.txt # The Trainee Software Engineer JD
└── tests/
    ├── test_core.py            # 44 logic tests
    ├── test_app.py             #  9 end-to-end UI tests (page 1)
    └── test_compare_page.py    #  6 end-to-end UI tests (page 2)
```

**Why `app.py` + `core.py` instead of one big file?**
Streamlit re-executes `app.py` from top to bottom on every click. Keeping the
logic in `core.py` means it can be unit-tested with pytest, needs no API key to
test, and keeps the UI file short enough to explain in a viva.

---

## 3. Installation (step by step)

### Windows

```bat
cd AI_Resume_Analyzer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### macOS / Linux

```bash
cd AI_Resume_Analyzer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Add your API key

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and replace the placeholder with your real key:

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
```

> Get a free key at **https://console.groq.com/keys** — sign in, click
> "Create API Key", copy it immediately (it is shown only once).
> **Never commit `.env` to GitHub.** It is already in `.gitignore`.

### Run

```bash
streamlit run app.py
```

Then open **http://localhost:8501**

---

## 3b. The two pages

Streamlit turns every `.py` file inside `pages/` into a second screen, reachable
from the sidebar. No routing code needed.

| Page | What it does |
|---|---|
| **AI Resume Analyzer** (`app.py`) | One resume vs one JD → full analysis report |
| **Compare & Rank** (`pages/1_Compare_and_Rank.py`) | Many resumes vs one JD → ranked shortlist, score bar chart, skill-by-skill matrix, CSV export |

On the Compare & Rank page you can choose the scoring engine:
* **⚡ Fast keyword rules** — free, instant, deterministic, zero hallucination.
* **🤖 AI analysis** — one Groq call per resume, richer qualitative feedback
  (watch the free-tier rate limit when you have many files).

---

## 4. How to test it in 60 seconds

1. Run `streamlit run app.py`.
2. In the sidebar click **📥 Load sample resume + job description**.
   (Or upload `sample_data/sample_resume.pdf` and paste
   `sample_data/job_description.txt`.)
3. Click **🔍 Analyze Resume**.
4. Switch to **Compare & Rank** in the sidebar, upload **both**
   `sample_data/sample_resume.pdf` and `sample_data/sample_resume_2.pdf`, paste
   the same JD and click **🏆 Score & Rank All Resumes**. You should see Arjun
   Nair at #1 (~67%) ahead of Priya Sharma (~17%).

No API key yet? Tick **Demo mode (no API key)** in the sidebar — the app runs
end-to-end using a rule-based engine so you can see and demo the whole UI.

### Expected output shape

```
ATS Match Score        82%
Matched Skills         Python · SQL · MySQL · OOP · Git · REST APIs
Missing Skills         Docker · AWS · Spring Boot
Partial Match Skills   Data Structures · FastAPI
Strengths              Good Python fundamentals · Database experience ...
```

---

## 5. Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Expected: `59 passed`.

* `tests/test_core.py` (44) — text extraction from PDF/DOCX/TXT, the JSON-repair
  logic, schema normalisation, prompt construction, keyword analysis and both
  report builders.
* `tests/test_app.py` (9) — drives the real `app.py` through Streamlit's own
  `AppTest` harness: it clicks the buttons, uploads the sample PDF and asserts
  that the full analysis renders with no exceptions, and that the empty-input
  guardrails warn instead of crashing.
* `tests/test_compare_page.py` (6) — same, for the Compare & Rank page: it
  uploads two resumes, asserts the stronger one is ranked #1, and checks that an
  unreadable file is reported instead of crashing the run.

**No API key or internet connection needed** — the UI tests run in demo mode.

---

## 6. Project Architecture

```
                     USER
                      |
                      v
              Streamlit Web UI  (app.py)
                      |
           +----------+----------+
           |                     |
           v                     v
     Resume PDF/DOCX      Job Description
           |                     |
           v                     |
     PyPDF / python-docx         |
           |                     |
           +----------+----------+
                      |
                      v
        Prompt Engineering (prompts.py)
                      |
                      v
                 Groq LLM
                      |
                      v
              Structured JSON
                      |
                      v
      parse_json_response() -> normalize_analysis()
                      |
           +----------+----------+
           |          |          |
           v          v          v
        ATS Score   Skills   Recommendations
                                 |
                                 v
                        Interview Questions
                                 |
                                 v
              Markdown / HTML / JSON report export
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `GROQ_API_KEY is missing` | Create `.env` from `.env.example` and restart Streamlit. |
| `401 / invalid api key` | Key expired or typo. Regenerate at console.groq.com/keys. |
| `429 / rate limit` | Free tier is limited per minute/day. Wait, or switch to `openai/gpt-oss-20b`. |
| `Model not found` | That model is not on your account. Use `openai/gpt-oss-120b`. |
| "Very little text was extracted" | The PDF is a scanned image. Use a text-based PDF or OCR it first. |
| `ModuleNotFoundError: streamlit` | Your venv is not activated, or run `pip install -r requirements.txt`. |
| Port 8501 busy | `streamlit run app.py --server.port 8502` |

---

## 8. Roadmap (already done vs. next)

**Already added on top of the base spec:** DOCX + TXT support, downloadable
Markdown/HTML/JSON report, deterministic keyword coverage, demo mode, analysis
history, structured JSON output mode, prompt versioning, **multi-resume
comparison and candidate ranking** (page 2), and 59 automated tests.

**Next iteration:** resume rewriting + skill-gap analysis, MySQL storage,
login/signup, admin dashboard, interview chatbot with RAG over company data,
deployment to Streamlit Community Cloud.

---

## 9. Deploy to Streamlit Community Cloud

1. Push the folder to a **public GitHub repo** (`.env` is git-ignored — verify
   with `git status` before pushing).
2. Go to https://share.streamlit.io → *Deploy an app*.
3. Repository → branch → main file = `app.py`.
4. Under **Advanced → Secrets**, add:
   ```toml
   GROQ_API_KEY = "gsk_xxxxxxxxxxxxx"
   ```
5. Deploy.

---

## 10. Academic honesty note

This is a coursework project. Use it to understand how the pieces fit, then
write your own README wording, change the prompts, and be ready to explain
every line in your viva. `VIVA_NOTES.md` contains the questions evaluators
actually ask.
