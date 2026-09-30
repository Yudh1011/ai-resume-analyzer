"""
core.py — All the non-UI logic of the AI Resume Analyzer.

Why a separate file?
    Streamlit re-executes app.py from top to bottom on every click. Keeping the
    "brain" (text extraction, prompt building, JSON parsing, scoring) in a plain
    Python module means:
        1. It can be unit-tested with pytest - no browser, no API key needed.
        2. app.py stays short and readable.
    Nothing in this file imports streamlit.
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

# ===========================================================================
# CONSTANTS
# ===========================================================================

MIN_RESUME_CHARS = 100      # below this the PDF is probably a scanned image
MAX_LLM_CHARS = 24_000      # safety cap so we never blow the context window

# The JSON contract shared by prompt -> parser -> report.
# Order matters: it is also the display order in the UI.
SCHEMA: dict[str, Any] = {
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
    "interview_questions": [],
}

LIST_FIELDS = (
    "matched_skills",
    "missing_skills",
    "partial_match_skills",
    "strengths",
    "weaknesses",
    "resume_improvements",
    "interview_questions",
)

TEXT_FIELDS = (
    "candidate_summary",
    "experience_match",
    "education_match",
    "project_match",
)


# ===========================================================================
# 1. TEXT EXTRACTION
# ===========================================================================

def clean_text(text: str) -> str:
    """Collapse runs of whitespace into single spaces and trim the ends.

    PDF extraction produces lots of stray newlines and double spaces which
    waste tokens and can confuse the model.
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_text_from_pdf(data: bytes) -> str:
    """Extract the text layer of a PDF using pypdf."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - report any parse failure to the user
        raise ValueError(f"Unable to read PDF: {exc}") from exc

    pages = []
    for page in reader.pages:
        try:
            page_text = page.extract_text()
        except Exception:  # noqa: BLE001 - one broken page must not kill the run
            page_text = ""
        if page_text:
            pages.append(page_text)

    return "\n".join(pages)


def extract_text_from_docx(data: bytes) -> str:
    """Extract paragraph and table text from a .docx file."""
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ValueError(
            "python-docx is not installed. Run: pip install python-docx"
        ) from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to read DOCX: {exc}") from exc

    parts = [p.text for p in document.paragraphs if p.text]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_text(filename: str, data: bytes) -> str:
    """Pick the right extractor based on the file extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        return extract_text_from_pdf(data)
    if ext == "docx":
        return extract_text_from_docx(data)
    if ext in ("txt", "md", "text"):
        return data.decode("utf-8", errors="ignore")

    raise ValueError(
        f"Unsupported file type '.{ext}'. Please upload a PDF, DOCX or TXT file."
    )


def truncate_for_llm(text: str, max_chars: int = MAX_LLM_CHARS) -> str:
    """Hard cap on document length so a huge resume cannot exceed the model's
    context window. Truncates at the end and marks where it happened."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " ...[text truncated]"


# ===========================================================================
# 2. LLM RESPONSE PARSING
# ===========================================================================

def parse_json_response(content: str) -> dict[str, Any]:
    """Safely pull a JSON object out of an LLM reply.

    LLMs routinely disobey "return JSON only". This handles the three common
    failure modes:
        * markdown code fences  ```json ... ```
        * prose before/after the JSON object
        * trailing commas / single quotes (repaired on a best-effort basis)
    Raises ValueError when no usable object can be found.
    """
    if not content or not content.strip():
        raise ValueError("The AI returned an empty response. Please try again.")

    text = content.strip()

    # Strip markdown fences anywhere in the string (not just at the start).
    text = re.sub(r"```(?:json|JSON)?", "", text)
    text = text.replace("```", "").strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("The AI returned JSON that was not an object.")
    except json.JSONDecodeError:
        pass

    # Fall back to locating the outermost { ... } pair.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Last resort: remove trailing commas, which models love to emit.
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    raise ValueError(
        "The AI returned an invalid response and it could not be parsed. "
        "Please try again."
    )


def _as_list(value: Any) -> list[str]:
    """Coerce whatever the model returned into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        # A model sometimes returns "a, b, c" instead of ["a","b","c"].
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, (list, tuple, set)):
        return [str(value).strip()]

    items: list[str] = []
    for item in value:
        if isinstance(item, dict):
            # e.g. {"skill": "Python", "note": "..."} -> keep the first value
            item = next(iter(item.values()), "")
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def normalize_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    """Force the model's output onto the schema.

    Guarantees every key exists, ats_score is an int in 0..100 and every list
    field is a list of non-empty strings. This is what stops the UI from
    crashing when the model misbehaves.
    """
    if not isinstance(raw, dict):
        raw = {}

    result: dict[str, Any] = {}

    score = raw.get("ats_score", raw.get("score", 0))
    try:
        score = int(round(float(score)))
    except (TypeError, ValueError):
        score = 0
    result["ats_score"] = max(0, min(100, score))

    for field in TEXT_FIELDS:
        value = raw.get(field, "")
        if isinstance(value, (list, tuple)):
            value = " ".join(str(v) for v in value)
        result[field] = str(value).strip() if value is not None else ""

    for field in LIST_FIELDS:
        result[field] = _as_list(raw.get(field))

    # Copy through any unexpected extra keys so nothing is silently lost.
    for key, value in raw.items():
        if key not in result:
            result[key] = value

    return result


# ===========================================================================
# 3. LLM CALLS
# ===========================================================================

def call_groq(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    json_mode: bool = True,
) -> str:
    """Send one chat completion request to Groq and return the text reply."""
    from groq import Groq

    client = Groq(api_key=api_key)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }

    if json_mode:
        # Groq structured output. Requires the word "json" to appear in the
        # messages - our prompts always mention JSON.
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return content or ""


def analyze_resume(
    api_key: str,
    model: str,
    resume_text: str,
    job_description: str,
    temperature: float = 0.2,
    json_mode: bool = True,
) -> dict[str, Any]:
    """Full pipeline: build prompt -> call Groq -> parse -> normalize."""
    import prompts

    user_prompt = prompts.build_analysis_prompt(
        truncate_for_llm(resume_text),
        truncate_for_llm(job_description),
    )

    content = call_groq(
        api_key=api_key,
        model=model,
        system_prompt=prompts.ANALYSIS_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=temperature,
        json_mode=json_mode,
    )

    # If json_mode was refused by the model, retry once in plain mode.
    try:
        parsed = parse_json_response(content)
    except ValueError:
        if json_mode:
            content = call_groq(
                api_key=api_key,
                model=model,
                system_prompt=prompts.ANALYSIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=temperature,
                json_mode=False,
            )
            parsed = parse_json_response(content)
        else:
            raise

    return normalize_analysis(parsed)


def generate_resume_tips(
    api_key: str,
    model: str,
    resume_text: str,
    temperature: float = 0.3,
) -> str:
    """Second, independent prompt: generic resume coaching tips."""
    import prompts

    return call_groq(
        api_key=api_key,
        model=model,
        system_prompt=prompts.TIPS_SYSTEM_PROMPT,
        user_prompt=prompts.build_tips_prompt(truncate_for_llm(resume_text)),
        temperature=temperature,
        json_mode=False,
    )


# ===========================================================================
# 4. DETERMINISTIC KEYWORD ANALYSIS (no LLM, no cost)
# ===========================================================================

# canonical term -> surface forms we look for in the text
SKILL_ALIASES: dict[str, list[str]] = {
    "Python": ["python"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js "],
    "TypeScript": ["typescript"],
    "C": ["c language", " c ", "c programming"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "c sharp"],
    "SQL": ["sql"],
    "MySQL": ["mysql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MongoDB": ["mongodb", "mongo db"],
    "SQLite": ["sqlite"],
    "Object Oriented Programming": [
        "object oriented programming",
        "object-oriented programming",
        " oop",
    ],
    "Data Structures": ["data structures", "data structure", " dsa"],
    "Algorithms": ["algorithms", "algorithm"],
    "Git": ["git", "github", "gitlab"],
    "REST APIs": ["rest api", "rest apis", "restful api", "restful apis"],
    "FastAPI": ["fastapi", "fast api"],
    "Flask": ["flask"],
    "Django": ["django"],
    "Spring Boot": ["spring boot", "springboot"],
    "Spring": ["spring"],
    "Docker": ["docker", "containerization", "containers"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "CI/CD": ["ci/cd", "continuous integration", "continuous deployment"],
    "Linux": ["linux", "ubuntu"],
    "Unit Testing": ["unit testing", "unit test", "pytest", "junit"],
    "Debugging": ["debug", "debugging", "troubleshoot"],
    "Agile": ["agile", "scrum", "kanban"],
    "HTML": ["html"],
    "CSS": ["css"],
    "React": ["react"],
    "Node.js": ["node.js", "nodejs"],
    "Machine Learning": ["machine learning", " ml "],
    "Deep Learning": ["deep learning"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Excel": ["excel"],
    "Power BI": ["power bi"],
    "Tableau": ["tableau"],
    "Communication Skills": ["communication skill", "communication"],
    "Problem Solving": ["problem solving", "problem-solving"],
    "Code Reviews": ["code review"],
    "Database Design": ["database design", "normalization", "normalisation"],
}

_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.]*")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "is", "it", "its", "of", "on", "or", "our", "the", "to", "we", "will",
    "with", "you", "your", "this", "that", "these", "those", "who", "which",
    "what", "when", "where", "why", "how", "all", "any", "but", "not", "only",
    "own", "same", "so", "than", "too", "very", "can", "cannot", "could", "did",
    "does", "do", "done", "had", "has", "her", "here", "him", "his", "i", "if",
    "me", "my", "no", "nor", "s", "she", "should", "some", "such", "t", "their",
    "them", "then", "there", "they", "up", "us", "was", "were", "while", "would",
    "also", "about", "above", "after", "again", "against", "am", "because",
    "before", "being", "below", "between", "both", "during", "each", "few",
    "more", "most", "other", "out", "over", "under", "until", "into", "through",
    "must", "plus", "preferred", "requirements", "requirement", "responsibilities",
    "responsibility", "role", "job", "work", "working", "team", "teams", "good",
    "strong", "knowledge", "experience", "years", "year", "ability", "able",
    "looking", "candidate", "company", "include", "including", "includes",
    "etc", "e.g", "i.e", "using", "use", "used", "new", "one", "two", "three",
    "may", "well", "way", "much", "many", "get", "got", "make", "made", "keep",
    "help", "helps", "need", "needs", "required", "require", "want", "wants",
    "ensure", "across", "per", "via", "like", "just", "very", "within",
}


def _normalize(text: str) -> str:
    """Lowercase and pad with spaces so ' oop' style aliases match cleanly."""
    return f" {text.lower()} "


def extract_skill_terms(text: str) -> list[str]:
    """Find every known skill term that appears in a piece of text."""
    haystack = _normalize(text)
    found = []
    for canonical, forms in SKILL_ALIASES.items():
        if any(form in haystack for form in forms):
            found.append(canonical)
    return found


def keyword_analysis(resume_text: str, job_description: str) -> dict[str, Any]:
    """Deterministic skill-overlap analysis.

    This costs nothing, never hallucinates, and gives you a baseline to compare
    the LLM's opinion against - a good thing to mention in your viva.
    """
    jd_terms = extract_skill_terms(job_description)
    resume_terms = extract_skill_terms(resume_text)
    resume_set = set(resume_terms)

    covered = [t for t in jd_terms if t in resume_set]
    missing = [t for t in jd_terms if t not in resume_set]
    bonus = [t for t in resume_terms if t not in set(jd_terms)]

    coverage = round(100 * len(covered) / len(jd_terms)) if jd_terms else 0

    return {
        "jd_skills": jd_terms,
        "covered": covered,
        "missing": missing,
        "bonus": bonus,
        "coverage": coverage,
    }


def baseline_analysis(resume_text: str, job_description: str) -> dict[str, Any]:
    """Build an analysis using pure keyword rules - no API key required.

    Used for (a) Demo mode so the UI can be shown before you have a key, and
    (b) a deterministic baseline to sanity-check the LLM's score.
    """
    kw = keyword_analysis(resume_text, job_description)

    covered, missing, bonus = kw["covered"], kw["missing"], kw["bonus"]
    total = len(kw["jd_skills"])
    coverage = kw["coverage"]

    resume_words = len(resume_text.split())

    summary = (
        f"Rule-based analysis (no AI used). The resume covers {len(covered)} of "
        f"{total} recognised skills mentioned in the job description "
        f"({coverage}% keyword coverage) across roughly {resume_words} words."
    )

    improvements = []
    if missing:
        improvements.append(
            "Add evidence for these missing keywords if you genuinely have them: "
            + ", ".join(missing[:8])
            + "."
        )
    if resume_words < 350:
        improvements.append(
            "The resume is short. Expand project bullets with the problem, the "
            "tools used and the measurable outcome."
        )
    if not any(ch.isdigit() for ch in resume_text):
        improvements.append(
            "No numbers found. Add quantified results such as 'reduced load time "
            "by 40%'."
        )
    improvements.append(
        "Mirror the exact wording of the job description - ATS parsers match "
        "keywords literally."
    )
    improvements.append(
        "Keep a single-column layout with standard section headings so the ATS "
        "can parse it."
    )

    questions = [
        f"Walk me through a project where you used {covered[0]}."
        if covered
        else "Walk me through your most substantial project.",
        "Explain the core concepts of Object Oriented Programming with an example.",
        "What is the difference between a list and a tuple in Python?",
        "How would you design and expose a simple REST API?",
        "Explain normalization in a relational database.",
        "What is time complexity and how do you analyse it?",
        "How do you use Git in a team workflow?",
        "Describe a bug you found and how you debugged it.",
        "How do you handle a requirement you do not understand?",
        "Where do you want your technical skills to be in two years?",
    ]

    raw = {
        "ats_score": max(10, min(95, coverage)),
        "candidate_summary": summary,
        "matched_skills": covered,
        "missing_skills": missing,
        "partial_match_skills": bonus[:5],
        "strengths": [f"Demonstrates {t}" for t in covered[:6]]
        or ["No matching skills detected yet"],
        "weaknesses": [f"No mention of {t}" for t in missing[:6]]
        or ["No obvious skill gaps detected"],
        "experience_match": (
            "Keyword rules cannot judge years of experience. Enable AI mode for "
            "a qualitative assessment."
        ),
        "education_match": (
            "Keyword rules cannot judge education fit. Enable AI mode for a "
            "qualitative assessment."
        ),
        "project_match": (
            "Keyword rules cannot judge project depth. Enable AI mode for a "
            "qualitative assessment."
        ),
        "resume_improvements": improvements,
        "interview_questions": questions[:10],
    }
    return normalize_analysis(raw)


# ===========================================================================
# 6. MULTI-RESUME COMPARISON AND CANDIDATE RANKING
# ===========================================================================

_NAME_BLACKLIST = {
    "resume", "cv", "curriculum vitae", "profile", "summary", "contact",
    "contact details", "contact information", "objective", "personal details",
    "education", "experience", "skills", "professional summary",
}

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]*$")


def guess_candidate_name(resume_text: str, fallback: str = "Candidate") -> str:
    """Best-effort extraction of the candidate's name from the top of a resume.

    Heuristic: the first short line that is only letters/spaces, has no digits,
    no email and is not a section heading. ALL-CAPS lines are title-cased.
    Falls back to `fallback` (usually the file name) when nothing looks like a
    name - this must never raise, because it runs on arbitrary user input.
    """
    if not resume_text:
        return fallback

    for raw_line in resume_text.splitlines()[:12]:
        line = raw_line.strip(" |\t-*\u2022")
        if not line:
            continue
        if len(line) > 45:
            break  # a line this long is not a name
        words = line.split()
        if not 1 <= len(words) <= 4:
            if len(words) > 4:
                break
            continue
        if any(ch.isdigit() for ch in line):
            continue
        if "@" in line or "http" in line.lower() or "www." in line.lower():
            continue
        if line.strip().lower() in _NAME_BLACKLIST:
            continue
        if not _NAME_RE.match(line):
            continue
        return line.title() if line.isupper() else line

    return fallback


def rank_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort candidates best-first and assign competition-style ranks.

    Primary sort: ATS score. Tie-breakers: number of matched skills, then
    keyword coverage, then name (so the order is deterministic across runs).
    Equal scores receive the same rank (1, 2, 2, 4).
    """
    ordered = sorted(
        entries,
        key=lambda e: (
            -int(e.get("ats_score", 0)),
            -int(e.get("matched_count", 0)),
            -int(e.get("coverage", 0)),
            str(e.get("name", "")),
        ),
    )

    ranked: list[dict[str, Any]] = []
    previous_key: tuple[int, int, int] | None = None
    previous_rank = 0

    for position, entry in enumerate(ordered, start=1):
        key = (
            int(entry.get("ats_score", 0)),
            int(entry.get("matched_count", 0)),
            int(entry.get("coverage", 0)),
        )
        rank = previous_rank if key == previous_key else position
        row = dict(entry)
        row["rank"] = rank
        ranked.append(row)
        previous_key, previous_rank = key, rank

    return ranked


def build_comparison_csv(ranked: list[dict[str, Any]]) -> str:
    """Render the ranking table as CSV for download / Excel."""
    import csv

    columns = [
        ("rank", "Rank"),
        ("name", "Candidate"),
        ("file_name", "File"),
        ("ats_score", "ATS Score"),
        ("matched_count", "Matched Skills"),
        ("missing_count", "Missing Skills"),
        ("coverage", "Keyword Coverage %"),
        ("matched_skills", "Matched Skills List"),
        ("missing_skills", "Missing Skills List"),
        ("source", "Scored By"),
    ]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([title for _, title in columns])

    for row in ranked:
        writer.writerow([
            "; ".join(str(v) for v in row[key]) if isinstance(row.get(key), list)
            else row.get(key, "")
            for key, _ in columns
        ])

    return buffer.getvalue()


def build_skill_matrix_csv(ranked: list[dict[str, Any]]) -> str:
    """Skill-by-candidate matrix as CSV: rows are required skills, columns are
    candidates, cells are YES/NO."""
    import csv

    all_skills = sorted({
        skill
        for row in ranked
        for skill in row.get("keywords", {}).get("jd_skills", [])
    })

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Required skill"] + [row["name"] for row in ranked])

    for skill in all_skills:
        cells = [
            "YES" if skill in row.get("keywords", {}).get("covered", []) else "NO"
            for row in ranked
        ]
        writer.writerow([skill] + cells)

    return buffer.getvalue()


# ===========================================================================
# 5. REPORT EXPORT
# ===========================================================================

def _score_color(score: int) -> str:
    if score >= 75:
        return "#16a34a"
    if score >= 50:
        return "#d97706"
    return "#dc2626"


def build_markdown_report(
    analysis: dict[str, Any],
    keywords: dict[str, Any] | None = None,
    resume_name: str = "resume.pdf",
    job_title: str = "Job Description",
) -> str:
    """Render the analysis as a Markdown document (downloadable)."""
    lines: list[str] = []
    lines.append(f"# AI Resume Analysis Report")
    lines.append("")
    lines.append(f"**Resume:** {resume_name}  ")
    lines.append(f"**Role:** {job_title}  ")
    lines.append(f"**ATS Match Score:** {analysis.get('ats_score', 0)}/100")
    lines.append("")

    lines.append("## Candidate Summary")
    lines.append(analysis.get("candidate_summary") or "Not available.")
    lines.append("")

    def section(title: str, items: list[str], bullet: str = "-") -> None:
        lines.append(f"## {title}")
        if items:
            for item in items:
                lines.append(f"{bullet} {item}")
        else:
            lines.append("None identified.")
        lines.append("")

    section("Matched Skills", analysis.get("matched_skills", []))
    section("Missing Skills", analysis.get("missing_skills", []))
    section("Partial Match Skills", analysis.get("partial_match_skills", []))
    section("Strengths", analysis.get("strengths", []))
    section("Weaknesses", analysis.get("weaknesses", []))

    for title, key in (
        ("Experience Match", "experience_match"),
        ("Education Match", "education_match"),
        ("Project Match", "project_match"),
    ):
        lines.append(f"## {title}")
        lines.append(analysis.get(key) or "Not available.")
        lines.append("")

    section(
        "Resume Improvement Recommendations",
        analysis.get("resume_improvements", []),
        bullet="1.",
    )
    section(
        "AI-Generated Interview Questions",
        analysis.get("interview_questions", []),
        bullet="1.",
    )

    if keywords:
        lines.append("## Keyword Coverage (deterministic)")
        lines.append(f"Coverage: {keywords.get('coverage', 0)}%")
        lines.append("")
        if keywords.get("covered"):
            lines.append("**Found in resume:** " + ", ".join(keywords["covered"]))
            lines.append("")
        if keywords.get("missing"):
            lines.append("**Missing from resume:** " + ", ".join(keywords["missing"]))
            lines.append("")

    lines.append("---")
    lines.append("_Generated by AI Resume Analyzer | Python + Streamlit + Groq_")
    return "\n".join(lines)


def build_html_report(
    analysis: dict[str, Any],
    keywords: dict[str, Any] | None = None,
    resume_name: str = "resume.pdf",
    job_title: str = "Job Description",
) -> str:
    """Render a self-contained HTML report.

    All CSS is inline, so the file works offline and can be printed to PDF
    from the browser (Ctrl/Cmd + P -> Save as PDF).
    """
    import html as _html

    score = int(analysis.get("ats_score", 0))
    color = _score_color(score)

    def esc(value: Any) -> str:
        return _html.escape(str(value))

    def block(title: str, items: list[str], marker: str = "&bull;") -> str:
        if not items:
            body = "<p class='empty'>None identified.</p>"
        else:
            body = "<ul>" + "".join(
                f"<li><span class='m'>{marker}</span> {esc(i)}</li>" for i in items
            ) + "</ul>"
        return f"<section><h2>{esc(title)}</h2>{body}</section>"

    def paragraph(title: str, key: str) -> str:
        return (
            f"<section><h2>{esc(title)}</h2>"
            f"<p>{esc(analysis.get(key) or 'Not available.')}</p></section>"
        )

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>AI Resume Analysis Report</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;margin:40px;color:#1f2937;max-width:900px}",
        "h1{font-size:28px;margin-bottom:4px}h2{font-size:17px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;margin-top:28px}",
        ".meta{color:#6b7280;font-size:13px;margin-bottom:20px}",
        ".score{display:inline-block;padding:18px 34px;border-radius:12px;color:#fff;font-size:34px;font-weight:700}",
        ".bar{height:10px;background:#e5e7eb;border-radius:6px;overflow:hidden;margin-top:14px;max-width:420px}",
        f".bar>div{{height:100%;width:{score}%;background:{color}}}",
        "ul{margin:8px 0 0;padding-left:4px;list-style:none}li{margin:5px 0}.m{color:#9ca3af;margin-right:6px}",
        ".empty{color:#9ca3af;font-style:italic}",
        "@media print{body{margin:0}}",
        "</style></head><body>",
        "<h1>AI Resume Analysis Report</h1>",
        f"<div class='meta'><b>Resume:</b> {esc(resume_name)} &nbsp;|&nbsp; "
        f"<b>Role:</b> {esc(job_title)}</div>",
        f"<div class='score' style='background:{color}'>{score}%</div>",
        f"<div class='bar'><div></div></div>",
        "<section><h2>Candidate Summary</h2><p>"
        + esc(analysis.get("candidate_summary") or "Not available.")
        + "</p></section>",
        block("Matched Skills", analysis.get("matched_skills", []), "&#10003;"),
        block("Missing Skills", analysis.get("missing_skills", [])),
        block("Partial Match Skills", analysis.get("partial_match_skills", []), "~"),
        block("Strengths", analysis.get("strengths", []), "&#10003;"),
        block("Weaknesses", analysis.get("weaknesses", [])),
        paragraph("Experience Match", "experience_match"),
        paragraph("Education Match", "education_match"),
        paragraph("Project Match", "project_match"),
        block("Resume Improvement Recommendations", analysis.get("resume_improvements", []), "&#8226;"),
        block("AI-Generated Interview Questions", analysis.get("interview_questions", []), "&#8226;"),
    ]

    if keywords:
        parts.append(
            f"<section><h2>Keyword Coverage (deterministic)</h2>"
            f"<p>Coverage: <b>{esc(keywords.get('coverage', 0))}%</b></p>"
        )
        if keywords.get("covered"):
            parts.append(f"<p><b>Found:</b> {esc(', '.join(keywords['covered']))}</p>")
        if keywords.get("missing"):
            parts.append(f"<p><b>Missing:</b> {esc(', '.join(keywords['missing']))}</p>")
        parts.append("</section>")

    parts.append(
        "<p class='meta' style='margin-top:32px'>Generated by AI Resume Analyzer "
        "| Python + Streamlit + Groq</p></body></html>"
    )
    return "".join(parts)
