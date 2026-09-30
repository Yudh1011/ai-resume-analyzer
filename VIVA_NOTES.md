# Viva / Presentation Notes

Questions evaluators actually ask about a project like this, with the answers
grounded in *this* codebase. Read it once, then close it and explain the project
out loud in three minutes.

---

## 30-second pitch

> "This is an AI Resume Analyzer. A user uploads a resume as PDF, DOCX or text,
> pastes a job description, and the app extracts the resume text with PyPDF,
> builds a structured prompt, sends it to a Groq-hosted Llama model, and gets
> back strict JSON. That JSON drives an ATS match score, matched and missing
> skills, strengths and weaknesses, resume improvements and ten interview
> questions, which the Streamlit UI renders and exports as a Markdown, HTML or
> JSON report."

---

## Likely questions

**Q: What is an ATS and why does it matter?**
An Applicant Tracking System is the software companies use to filter resumes
before a human reads them. It parses the document and keyword-matches it against
the job description. Resumes that do not parse cleanly, or that miss the exact
keywords, are rejected without being seen. This app simulates that matching step.

**Q: Why Groq instead of OpenAI?**
Groq runs models on dedicated inference hardware (LPUs), so responses come back
in well under a second, and it has a genuinely free tier — no credit card. For a
course project that means instant demos at zero cost.

**Q: Why `temperature=0.2`?**
Scoring has to be reproducible. Temperature controls sampling randomness; 0.2
keeps the output near-deterministic while still allowing some natural phrasing.
Creative tasks like the tips prompt use 0.3. The sidebar slider lets me
demonstrate the difference live.

**Q: How do you stop the model from hallucinating?**
Four layers: (1) explicit anti-invention rules in the prompt, (2) a
self-verification step, (3) Groq's `response_format=json_object`, and (4) a
deterministic keyword scan in `core.keyword_analysis()` that I can compare the
LLM's claim against. If the model says 95% but the keyword scan finds 4 of 12
required skills, I know the answer is wrong.

**Q: What if the model returns invalid JSON?**
`parse_json_response()` strips markdown code fences, locates the outermost
`{...}` block, and repairs trailing commas. If that still fails and JSON mode was
on, it retries once in plain mode. Finally `normalize_analysis()` clamps the
score to 0–100 and coerces every field to the right type, so the UI can never
crash on a bad response. All of this is unit-tested.

**Q: Why did you split `app.py` and `core.py`?**
Streamlit re-runs the whole script on every interaction. Keeping logic in
`core.py` means it is importable and testable without a browser or an API key —
that is why I have 33 passing pytest tests. `app.py` only draws widgets.

**Q: Why did you add a scoring rubric to the prompt?**
Without explicit bands the model invents a new scale each run and the number is
meaningless. With bands, 82 consistently means "strong match, a few gaps", and I
can defend the number.

**Q: What are the limitations?**
The ATS score is an LLM judgement, not a real ATS — real systems weight keywords
differently and parse layout. Scanned PDFs have no text layer, so extraction
fails without OCR. The model has no knowledge of the company beyond the pasted
JD. And there is no persistent storage — history lives only in the browser
session.

**Q: Tell me about the Compare & Rank page.**
It is recruiter mode. You upload several resumes against one job description and
it scores every candidate, then sorts them with `core.rank_candidates()`. The
sort key is ATS score first, then matched-skill count, then keyword coverage,
then name — so the order is deterministic. Ties get competition ranking, so two
equal candidates both get rank 1 and the next gets rank 3. It renders a ranking
table with progress bars, a score bar chart, a skill-by-skill comparison matrix
showing which candidate has which required skill, individual report tabs, and CSV
exports.

**Q: How does the candidate name get detected?**
`core.guess_candidate_name()` scans the first 12 lines for a short line that is
only letters and spaces, has no digits, no email address and is not a known
section heading. ALL-CAPS lines get title-cased. If nothing qualifies it falls
back to the file name — it is written so it can never raise on arbitrary input.

**Q: How would you make this production-grade?**
MySQL or Postgres for persistent resume history, login/signup with hashed
passwords, OCR for scanned PDFs, resume rewriting and skill-gap analysis, RAG
over company and role data, rate limiting and cost tracking, an admin dashboard,
and deployment to Streamlit Community Cloud or a Docker container behind a
reverse proxy.

**Q: Where is your API key stored?**
In a `.env` file loaded by `python-dotenv`, never hard-coded in `app.py`, and
`.env` is in `.gitignore` so it can never be committed. For deployment it goes
into Streamlit Cloud's encrypted Secrets store instead.

**Q: What is prompt engineering, in one sentence?**
Designing the instruction you give a model — role, context, constraints, output
format and examples — so that a general-purpose model reliably produces the
specific output your application needs.

---

## Numbers worth memorising

| Thing | Value |
|---|---|
| Unit + UI tests | 59, all passing, no API key required |
| Files of application code | 5 (`app.py`, `pages/1_Compare_and_Rank.py`, `ui_common.py`, `core.py`, `prompts.py`) |
| LLM prompts | 2 (analysis + tips) |
| Output schema fields | 12 |
| Resume formats supported | 3 (PDF, DOCX, TXT) |
| Report export formats | 3 (Markdown, HTML, JSON) |
| Known-skill vocabulary for the keyword scan | 47 canonical terms |
| Pages | 2 (single analysis + compare & rank) |
| Model used | `openai/gpt-oss-120b` on Groq (auto-detected live) |
| Temperature | 0.2 (analysis) / 0.3 (tips) |

---

## Live demo script (3 minutes)

1. `streamlit run app.py` — already running, show the landing page.
2. Click **📥 Load sample resume + job description** in the sidebar.
3. Click **🔍 Analyze Resume**. Point at the gauge, the matched/missing pills.
4. Open **🔎 Deterministic keyword coverage** — explain the no-AI baseline.
5. Scroll to interview questions.
6. Click **Download → HTML / Print to PDF**, open it, `Ctrl+P`.
7. Move the temperature slider from 0.0 to 0.9, re-analyse, compare scores.
8. Open **View raw JSON returned by the model** — show the structured contract.
9. Switch to **Compare & Rank**, upload both sample PDFs, click **Score & Rank**
   and show the shortlist, the skill matrix and the CSV download.

**Fallback plan:** if the API is down or rate-limited, tick **Demo mode** and
carry on — the whole UI still works.
