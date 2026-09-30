# Prompt Engineering Notes

This is the part of the project your evaluator will judge most closely. Every
prompt lives in **`prompts.py`**. Below is the reasoning behind each technique,
so you can explain it confidently.

Prompt version: **1.1**

---

## 1. The two-prompt design

| Prompt | Purpose | Temperature | Output |
|---|---|---|---|
| `ANALYSIS_USER_PROMPT` | Resume vs. JD → structured score | 0.2 | strict JSON |
| `TIPS_USER_PROMPT` | Generic resume coaching | 0.3 | numbered list |

**Why split them?** One prompt doing two jobs produces a mushy answer. Separating
an *evaluation* task (needs to be consistent and factual → low temperature,
structured output) from a *creative advice* task (can be a bit more varied →
slightly higher temperature, free text) lets each prompt be tuned for its own
goal. This is the single most important prompt-engineering decision in the app.

---

## 2. Techniques used, and why

### 2.1 Role priming (system message)
```
You are a professional ATS (Applicant Tracking System) resume analyzer and
senior technical recruiter.
```
Assigning a domain expert role measurably improves the quality and vocabulary of
the output. It is placed in the **system** message, not the user message, so it
persists and carries more weight.

### 2.2 Explicit output contract (the JSON schema)
The exact JSON object is printed inside the prompt with every key and its type:
```json
{ "ats_score": 0, "matched_skills": [], ... }
```
Telling the model *what shape* to answer in is far more reliable than describing
the shape in prose. The same schema constant is reused by the parser, so the
prompt and the code cannot drift apart.

### 2.3 A scoring rubric — the biggest quality win
```
85-100 : Almost every must-have requirement is clearly evidenced
70-84  : Strong match. Most must-haves present, a few gaps
50-69  : Moderate match...
```
Without a rubric, the model invents a different scale on every run and the
"ATS score" is meaningless. With bands, the number is **repeatable** and you can
defend it: *"82 means strong match with a few gaps, per my rubric."*

The rubric also says *"score the evidence in the resume, not the potential of the
candidate"* — otherwise models are generous and everything scores 90.

### 2.4 Anti-hallucination rules
```
6. Do NOT invent candidate experience, employers, dates, degrees or projects.
7. Base the analysis ONLY on the resume and job description provided below.
```
Grounding constraints. LLMs love to invent plausible-sounding employers; an
explicit prohibition sharply reduces this.

### 2.5 Mutual-exclusivity constraint
```
5. A skill may appear in only ONE of matched_skills, missing_skills or
   partial_match_skills.
```
Without this, the model happily lists "Python" as both matched *and* missing.
Constraints that eliminate logical contradictions make downstream code trustworthy.

### 2.6 Exact counts
```
8. interview_questions must contain exactly 10 questions...
9. resume_improvements must contain 5 to 8 specific, actionable recommendations.
```
Vague ("provide some questions") produces 3 items or 25. Numbers make the UI
layout predictable.

### 2.7 Self-verification step
```
SELF-CHECK before you answer:
- Re-read the resume and confirm every item in matched_skills appears in it.
- Confirm the number of interview_questions is exactly 10.
- Confirm your output starts with "{" and ends with "}".
```
Asking the model to verify its own answer before emitting it is a lightweight
form of chain-of-thought that catches its own mistakes at near-zero cost.

### 2.8 Format enforcement, twice
The instruction *"Return JSON only. Do not wrap it in markdown code fences"*
appears in **both** the system prompt and the user prompt. Belt and braces —
plus Groq's `response_format={"type":"json_object"}` as a third layer.

### 2.9 Low temperature for evaluation
`temperature=0.2`. Scoring must be reproducible: the same resume against the same
JD should give roughly the same score. High temperature is for creative writing.
The slider in the sidebar lets you demonstrate the difference live.

### 2.10 Clear input delimiting
```
RESUME:
<the resume>

JOB DESCRIPTION:
<the JD>
```
Labelled sections prevent the model from confusing where the resume ends and the
JD begins — a real failure mode when both mention the same skills.

---

## 3. Defence in depth: what happens when the model disobeys

Prompts are requests, not guarantees. `core.py` has three fallback layers:

1. **`response_format={"type":"json_object"}`** — Groq's structured output mode.
2. **`parse_json_response()`** — strips ```` ```json ```` fences, finds the
   outermost `{...}` block, and repairs trailing commas.
3. **`normalize_analysis()`** — forces the result onto the schema: clamps
   `ats_score` to 0–100, converts `"Python, SQL"` strings into real lists,
   flattens `[{"skill":"Python"}]` into `["Python"]`, and fills any missing key.

If JSON mode is rejected by a model, the app automatically retries once in plain
mode. **Result: the UI never crashes because of a bad model response.**

---

## 4. Guardrails

| Guardrail | Where | Why |
|---|---|---|
| `MIN_RESUME_CHARS = 100` | `app.py` | Rejects scanned/image PDFs with a clear message |
| `MAX_LLM_CHARS = 24_000` | `truncate_for_llm()` | Prevents context-window overflow on huge resumes |
| `st.cache_data` | `app.py` | Re-renders never burn a second API call |
| Deterministic keyword scan | `keyword_analysis()` | A no-AI baseline to check whether the LLM's score is plausible |

That last one is worth highlighting in your presentation: **you do not have to
trust the LLM blindly.** The keyword engine computes coverage with zero cost and
zero hallucination risk, so if the LLM says 95% but the keyword scan finds 4 of
12 skills, you know something is off.

---

## 5. Prompt improvement ideas to mention in your viva

* **Few-shot example** — include one worked resume/JD/score triple to anchor the scale.
* **Chain-of-thought then JSON** — let the model reason in a hidden `reasoning`
  field, then emit the score. Improves accuracy; costs tokens.
* **Two-pass scoring** — first extract skills from the resume, then match them
  against the JD. Reduces hallucinated matches.
* **Self-consistency** — call the model 3 times at temperature 0.5 and take the
  median score.
* **Per-skill evidence** — ask the model to quote the exact resume line that
  proves each matched skill. Makes the output auditable.

---

## 6. Try this experiment yourself

1. Set temperature to **0.0** and analyse the sample resume. Note the score.
2. Set temperature to **0.9** and analyse again. Compare.
3. Remove the scoring rubric from `prompts.py` and analyse a third time.

Write the three scores in your report. Showing that you *measured* the effect of
a prompt change is exactly what a prompt-engineering course is looking for.
