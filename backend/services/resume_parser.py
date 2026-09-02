"""Resume parsing.

Converts a PDF / DOCX / TXT upload into structured JSON:

    {
      "contact":      {name, email, phone, linkedin, github, portfolio, location},
      "sections":     {summary, skills, experience, projects, education, ...},
      "education":    [...], "experience": [...], "projects": [...],
      "certifications": [...], "achievements": [...],
      "metadata":     {pages, words, file_type, extractor, warnings}
    }

Extraction backends, in order of preference:
    PDF  - PyMuPDF (fast, good layout) -> pdfplumber (better on odd layouts)
    DOCX - python-docx (paragraphs + tables)
    TXT  - decoded directly

Every backend is optional: a missing library produces a clear, actionable error
rather than a stack trace.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ml.nlp_pipeline import (
    ACTION_VERBS,
    find_metrics,
    find_years_of_experience,
    get_pipeline,
    normalise_whitespace,
)

# ---------------------------------------------------------------------------
# Section vocabulary
# ---------------------------------------------------------------------------

SECTION_PATTERNS: dict[str, list[str]] = {
    "summary": ["professional summary", "career summary", "summary", "objective",
                "career objective", "profile", "about me", "professional profile"],
    "skills": ["technical skills", "skills", "core competencies", "technologies",
               "technical expertise", "skill set", "areas of expertise", "tech stack"],
    "experience": ["work experience", "professional experience", "experience",
                   "employment history", "employment", "work history",
                   "internships", "internship experience", "industry experience"],
    "projects": ["projects", "academic projects", "personal projects", "key projects",
                 "selected projects", "project work", "project experience"],
    "education": ["education", "academic background", "academic qualifications",
                  "educational qualifications", "academics", "qualifications"],
    "certifications": ["certifications", "certificates", "licenses & certifications",
                       "professional certifications", "courses", "certifications & courses"],
    "achievements": ["achievements", "awards", "honors", "honours", "accomplishments",
                     "awards & achievements", "extracurricular", "activities"],
    "publications": ["publications", "research", "papers", "research experience"],
    "leadership": ["leadership", "positions of responsibility", "volunteering",
                   "volunteer experience"],
}

# Longest-first so "work experience" wins over "experience".
_HEADING_LOOKUP: list[tuple[str, str]] = sorted(
    ((pattern, section) for section, patterns in SECTION_PATTERNS.items() for pattern in patterns),
    key=lambda pair: -len(pair[0]),
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\(?\d{3,5}\)?[\s.-]?)?\d{3}[\s.-]?\d{3,4}(?!\d)"
)
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[\w.]*\.)?linkedin\.com/[\w\-/%.]+", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-.]+", re.I)
URL_RE = re.compile(r"https?://[\w\-./?%&=+#:]+", re.I)
DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*'?\d{2,4}|\d{1,2}/\d{4}|(?:19|20)\d{2})"
    r"\s*(?:-|–|—|to|until)\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*'?\d{2,4}|\d{1,2}/\d{4}|(?:19|20)\d{2}|Present|Current|Now|Ongoing)",
    re.I,
)
DEGREE_RE = re.compile(
    r"\b(B\.?\s?Tech|B\.?\s?E\.?|B\.?\s?Sc|B\.?\s?C\.?A|Bachelor(?:'s)?(?:\s+of\s+\w+)?|"
    r"M\.?\s?Tech|M\.?\s?E\.?|M\.?\s?Sc|M\.?\s?C\.?A|Master(?:'s)?(?:\s+of\s+\w+)?|"
    r"MBA|Ph\.?\s?D|Doctorate|Diploma|Associate(?:'s)?)\b",
    re.I,
)
GPA_RE = re.compile(r"(?:GPA|CGPA|Grade|Percentage)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)\s*(?:/\s*(\d{1,2}))?", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
BULLET_RE = re.compile(r"^\s*(?:[-*•‣●▪·>]|\d+[.)])\s+")

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}


class ResumeParsingError(Exception):
    """Raised when a file cannot be turned into usable text."""


# ---------------------------------------------------------------------------
# Structured containers
# ---------------------------------------------------------------------------


@dataclass
class ExperienceEntry:
    title: str = ""
    organisation: str = ""
    date_range: str = ""
    duration_months: int = 0
    bullets: list[str] = field(default_factory=list)
    raw: str = ""


@dataclass
class ProjectEntry:
    name: str = ""
    description: str = ""
    bullets: list[str] = field(default_factory=list)
    tech_hint: str = ""
    raw: str = ""


@dataclass
class EducationEntry:
    degree: str = ""
    field_of_study: str = ""
    institution: str = ""
    year: str = ""
    score: str = ""
    raw: str = ""


@dataclass
class ParsedResume:
    raw_text: str
    contact: dict[str, str]
    sections: dict[str, str]
    experience: list[ExperienceEntry]
    projects: list[ProjectEntry]
    education: list[EducationEntry]
    certifications: list[str]
    achievements: list[str]
    skill_section_terms: list[str]
    bullets: list[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contact": self.contact,
            "sections": self.sections,
            "experience": [asdict(e) for e in self.experience],
            "projects": [asdict(p) for p in self.projects],
            "education": [asdict(e) for e in self.education],
            "certifications": self.certifications,
            "achievements": self.achievements,
            "skill_section_terms": self.skill_section_terms,
            "bullets": self.bullets,
            "metadata": self.metadata,
        }

    @property
    def total_experience_months(self) -> int:
        return sum(e.duration_months for e in self.experience)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_text(data: bytes, filename: str) -> tuple[str, dict[str, Any]]:
    """Extract raw text from an uploaded file.

    Returns ``(text, metadata)``. Raises :class:`ResumeParsingError` when the
    file type is unsupported or contains no extractable text.
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _extract_pdf(data)
    if name.endswith(".docx"):
        return _extract_docx(data)
    if name.endswith(".doc"):
        raise ResumeParsingError(
            "Legacy .doc files are not supported. Save the file as PDF or DOCX and upload again."
        )
    if name.endswith(".txt"):
        text = data.decode("utf-8", errors="replace")
        return text, {"pages": 1, "extractor": "plain-text", "warnings": []}
    raise ResumeParsingError(
        f"Unsupported file type '{name.rsplit('.', 1)[-1] if '.' in name else name}'. "
        "Upload a PDF, DOCX or TXT resume."
    )


def _extract_pdf(data: bytes) -> tuple[str, dict[str, Any]]:
    warnings: list[str] = []
    text, pages, extractor = "", 0, ""

    try:
        try:
            import pymupdf as fitz  # PyMuPDF >= 1.24 module name
        except ImportError:
            import fitz  # older PyMuPDF releases

        with fitz.open(stream=data, filetype="pdf") as doc:
            pages = doc.page_count
            chunks = [page.get_text("text") for page in doc]
            if any(page.get_images() for page in doc):
                warnings.append(
                    "This PDF contains images. Text inside an image cannot be read by "
                    "applicant tracking systems - keep all content as selectable text."
                )
        text = "\n".join(chunks)
        extractor = "pymupdf"
    except ImportError:
        warnings.append("PyMuPDF not installed - fell back to pdfplumber.")
    except Exception as exc:
        warnings.append(f"PyMuPDF could not read this PDF ({exc}); trying pdfplumber.")

    if len(text.strip()) < 120:
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = pages or len(pdf.pages)
                plumbed = "\n".join(p.extract_text() or "" for p in pdf.pages)
                tables = sum(len(p.find_tables()) for p in pdf.pages)
            if len(plumbed.strip()) > len(text.strip()):
                text, extractor = plumbed, "pdfplumber"
            if tables:
                warnings.append(
                    f"Detected {tables} table layout(s). Many ATS parsers read table cells "
                    "out of order - prefer simple single-column formatting."
                )
        except ImportError:
            pass
        except Exception as exc:
            warnings.append(f"pdfplumber could not read this PDF ({exc}).")

    if not text.strip():
        raise ResumeParsingError(
            "No text could be extracted from this PDF. It is most likely a scanned image. "
            "Export a text-based PDF from your editor and upload it again."
        )

    if _looks_multi_column(text):
        warnings.append(
            "The layout looks multi-column. ATS parsers frequently scramble column order - "
            "a single-column layout is safer."
        )
    return text, {"pages": pages, "extractor": extractor or "pymupdf", "warnings": warnings}


def _extract_docx(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover
        raise ResumeParsingError(
            "DOCX support requires python-docx. Install it with: pip install python-docx"
        ) from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ResumeParsingError(f"This DOCX file could not be opened ({exc}).") from exc

    warnings: list[str] = []
    parts = [p.text for p in document.paragraphs]
    if document.tables:
        warnings.append(
            f"Detected {len(document.tables)} table(s). Tables often break ATS parsing - "
            "move that content into plain paragraphs where possible."
        )
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))

    text = "\n".join(parts)
    if not text.strip():
        raise ResumeParsingError("This DOCX file contains no readable text.")
    return text, {"pages": max(1, len(text) // 3500), "extractor": "python-docx", "warnings": warnings}


def _looks_multi_column(text: str) -> bool:
    """Heuristic: many short lines with a wide internal gap suggest columns."""
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 15:
        return False
    gapped = sum(1 for l in lines if re.search(r"\S {4,}\S", l))
    return gapped / len(lines) > 0.35


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ResumeParser:
    """Turns raw resume text into a structured record."""

    def __init__(self) -> None:
        self.nlp = get_pipeline()

    # -- entry point -------------------------------------------------------

    def parse(self, data: bytes, filename: str) -> ParsedResume:
        raw, meta = extract_text(data, filename)
        return self.parse_text(raw, filename=filename, base_metadata=meta)

    def parse_text(
        self,
        raw_text: str,
        filename: str = "resume.txt",
        base_metadata: dict[str, Any] | None = None,
    ) -> ParsedResume:
        meta = dict(base_metadata or {"pages": 1, "extractor": "raw-text", "warnings": []})
        text = normalise_whitespace(raw_text)
        lines = [l.rstrip() for l in text.split("\n")]

        sections = self._split_sections(lines)
        contact = self._extract_contact(text, lines)
        bullets = self._collect_bullets(lines)

        experience = self._parse_experience(sections.get("experience", ""))
        projects = self._parse_projects(sections.get("projects", ""))
        education = self._parse_education(sections.get("education", ""))
        certifications = self._parse_list_section(sections.get("certifications", ""))
        achievements = self._parse_list_section(sections.get("achievements", ""))
        skill_terms = self._parse_skill_section(sections.get("skills", ""))

        warnings = list(meta.get("warnings", []))
        for required in ("skills", "experience", "education"):
            if not sections.get(required):
                warnings.append(
                    f"No '{required}' section heading was detected. ATS parsers rely on "
                    f"standard headings - add a clear '{required.title()}' heading."
                )

        words = len(text.split())
        meta.update(
            {
                "file_name": filename,
                "file_type": filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt",
                "words": words,
                "characters": len(text),
                "sections_detected": sorted(k for k, v in sections.items() if v),
                "bullet_count": len(bullets),
                "bullets_with_metrics": sum(1 for b in bullets if find_metrics(b)),
                "bullets_with_action_verbs": sum(
                    1 for b in bullets if _first_token(b) in ACTION_VERBS
                ),
                "declared_years_experience": find_years_of_experience(text),
                "nlp_backend": self.nlp.backend,
                "warnings": warnings,
            }
        )

        return ParsedResume(
            raw_text=text,
            contact=contact,
            sections=sections,
            experience=experience,
            projects=projects,
            education=education,
            certifications=certifications,
            achievements=achievements,
            skill_section_terms=skill_terms,
            bullets=bullets,
            metadata=meta,
        )

    # -- sectioning --------------------------------------------------------

    def _split_sections(self, lines: list[str]) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current = "header"
        sections[current] = []
        for line in lines:
            heading = self._heading_for(line)
            if heading:
                current = heading
                sections.setdefault(current, [])
                # Some resumes put content on the heading line: "SKILLS: Python, SQL"
                remainder = re.sub(r"^[^A-Za-z]*[A-Za-z &/]+[:\-]\s*", "", line).strip()
                if remainder and len(remainder) > 3 and ":" in line:
                    sections[current].append(remainder)
                continue
            sections[current].append(line)
        return {k: "\n".join(v).strip() for k, v in sections.items()}

    @staticmethod
    def _heading_for(line: str) -> str | None:
        stripped = line.strip().strip("|").strip()
        if not stripped or len(stripped) > 60:
            return None
        if BULLET_RE.match(line):
            return None
        candidate = re.sub(r"[^a-zA-Z& ]", " ", stripped).strip().lower()
        candidate = re.sub(r"\s+", " ", candidate)
        if not candidate:
            return None
        for pattern, section in _HEADING_LOOKUP:
            if candidate == pattern:
                return section
            # "TECHNICAL SKILLS:" / "Projects -----" style headings
            if candidate.startswith(pattern) and len(candidate) - len(pattern) <= 12:
                if stripped.isupper() or stripped.endswith(":") or len(stripped.split()) <= 4:
                    return section
        return None

    # -- contact -----------------------------------------------------------

    def _extract_contact(self, text: str, lines: list[str]) -> dict[str, str]:
        head = "\n".join(lines[:14])
        email = EMAIL_RE.search(text)
        linkedin = LINKEDIN_RE.search(text)
        github = GITHUB_RE.search(text)

        phone = ""
        for candidate in PHONE_RE.finditer(head or text):
            digits = re.sub(r"\D", "", candidate.group(0))
            if 9 <= len(digits) <= 14 and not YEAR_RE.fullmatch(candidate.group(0).strip()):
                phone = candidate.group(0).strip()
                break

        portfolio = ""
        for url in URL_RE.finditer(text):
            value = url.group(0)
            if "linkedin.com" in value.lower() or "github.com" in value.lower():
                continue
            portfolio = value
            break

        return {
            "name": self._extract_name(lines, email.group(0) if email else ""),
            "email": email.group(0) if email else "",
            "phone": phone,
            "linkedin": _clean_url(linkedin.group(0)) if linkedin else "",
            "github": _clean_url(github.group(0)) if github else "",
            "portfolio": _clean_url(portfolio) if portfolio else "",
            "location": self._extract_location(head),
        }

    def _extract_name(self, lines: list[str], email: str) -> str:
        for line in lines[:8]:
            candidate = line.strip().strip("|").strip()
            if not candidate or len(candidate) > 48:
                continue
            if any(ch.isdigit() for ch in candidate) or "@" in candidate or "http" in candidate.lower():
                continue
            if self._heading_for(candidate):
                continue
            words = candidate.replace(",", " ").split()
            if not 1 < len(words) <= 5:
                continue
            alpha_words = [w for w in words if re.fullmatch(r"[A-Za-z.\-']{2,}", w)]
            if len(alpha_words) < 2:
                continue
            if candidate.isupper() or all(w[0].isupper() for w in alpha_words):
                return " ".join(w.title() if w.isupper() else w for w in words)

        # Fall back to spaCy PERSON entities, then to the email local part.
        doc = self.nlp.analyse("\n".join(lines[:12]))
        for ent in doc.entities:
            if ent.label == "PERSON" and 1 < len(ent.text.split()) <= 4:
                return ent.text.strip()
        if email:
            local = email.split("@")[0]
            parts = [p for p in re.split(r"[._\-0-9]+", local) if len(p) > 1]
            if parts:
                return " ".join(p.capitalize() for p in parts)
        return ""

    @staticmethod
    def _extract_location(head: str) -> str:
        match = re.search(
            r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s*([A-Z][a-z]+|[A-Z]{2})\b", head
        )
        return match.group(0) if match else ""

    # -- section parsers ---------------------------------------------------

    @staticmethod
    def _collect_bullets(lines: list[str]) -> list[str]:
        bullets = []
        for line in lines:
            if BULLET_RE.match(line):
                cleaned = BULLET_RE.sub("", line).strip()
                if len(cleaned.split()) >= 3:
                    bullets.append(cleaned)
        return bullets

    def _parse_experience(self, block: str) -> list[ExperienceEntry]:
        entries: list[ExperienceEntry] = []
        for chunk in _split_entries(block):
            lines = [l for l in chunk.split("\n") if l.strip()]
            if not lines:
                continue
            entry = ExperienceEntry(raw=chunk.strip())
            header_lines = [l for l in lines if not BULLET_RE.match(l)][:3]
            header = " | ".join(l.strip() for l in header_lines)

            date_match = DATE_RANGE_RE.search(chunk)
            if date_match:
                entry.date_range = date_match.group(0).strip()
                entry.duration_months = _months_between(date_match.group(1), date_match.group(2))

            title, org = _split_title_org(header, date_match.group(0) if date_match else "")
            entry.title, entry.organisation = title, org
            entry.bullets = [
                BULLET_RE.sub("", l).strip() for l in lines if BULLET_RE.match(l)
            ] or [l.strip() for l in lines[1:] if len(l.split()) > 4]
            if entry.title or entry.organisation or entry.bullets:
                entries.append(entry)
        return entries[:15]

    def _parse_projects(self, block: str) -> list[ProjectEntry]:
        entries: list[ProjectEntry] = []
        for chunk in _split_entries(block):
            lines = [l for l in chunk.split("\n") if l.strip()]
            if not lines:
                continue
            head = lines[0].strip()
            head = BULLET_RE.sub("", head).strip()
            name = re.split(r"\s[|\-–—]\s|:", head)[0].strip()
            tech_hint = ""
            tech_match = re.search(
                r"(?:tech(?:nologies)?|stack|tools|built with)\s*[:\-]\s*(.+)", chunk, re.I
            )
            if tech_match:
                tech_hint = tech_match.group(1).strip()
            bullets = [BULLET_RE.sub("", l).strip() for l in lines[1:] if BULLET_RE.match(l)]
            if not bullets:
                bullets = [l.strip() for l in lines[1:] if len(l.split()) > 4]
            entries.append(
                ProjectEntry(
                    name=name[:120],
                    description=" ".join(bullets)[:600] or head,
                    bullets=bullets,
                    tech_hint=tech_hint,
                    raw=chunk.strip(),
                )
            )
        return entries[:15]

    def _parse_education(self, block: str) -> list[EducationEntry]:
        entries: list[EducationEntry] = []
        for chunk in _split_entries(block, min_lines=1):
            text = chunk.strip()
            if not text:
                continue
            degree_match = DEGREE_RE.search(text)
            if not degree_match and not re.search(r"universit|college|institute|school", text, re.I):
                continue
            entry = EducationEntry(raw=text)
            if degree_match:
                entry.degree = degree_match.group(0).strip()
                # Stay on the degree's own line: a newline here would swallow
                # the institution name into the field of study.
                after = text[degree_match.end() :].split("\n")[0][:90]
                field_match = re.search(r"(?:in|of)[ \t]+([A-Za-z&, \t]{3,45})", after)
                if field_match:
                    entry.field_of_study = field_match.group(1).strip(" ,.|-")
            # Horizontal whitespace only, for the same reason.
            inst_match = re.search(
                r"([A-Z][\w.&'-]*(?:[ \t]+[A-Z][\w.&'-]*){0,5}[ \t]+"
                r"(?:University|College|Institute|School|Academy)"
                r"(?:[ \t]+of[ \t]+[A-Z][\w.&'-]*)?)",
                text,
            )
            if inst_match:
                entry.institution = inst_match.group(1).strip()
            years = YEAR_RE.findall(text)
            year_spans = re.findall(r"\b((?:19|20)\d{2})\b", text)
            if year_spans:
                entry.year = year_spans[-1]
            gpa = GPA_RE.search(text)
            if gpa:
                entry.score = gpa.group(0).strip()
            entries.append(entry)
        return entries[:8]

    @staticmethod
    def _parse_list_section(block: str) -> list[str]:
        items: list[str] = []
        for line in block.split("\n"):
            cleaned = BULLET_RE.sub("", line).strip(" .;")
            if len(cleaned.split()) >= 2 and len(cleaned) <= 220:
                items.append(cleaned)
        return items[:25]

    @staticmethod
    def _parse_skill_section(block: str) -> list[str]:
        """Split the skills block into individual declared terms."""
        terms: list[str] = []
        for line in block.split("\n"):
            cleaned = BULLET_RE.sub("", line).strip()
            if not cleaned:
                continue
            # Drop a leading category label: "Languages: Python, Java"
            cleaned = re.sub(r"^[A-Za-z &/]{3,28}:\s*", "", cleaned)
            for part in re.split(r"[,;|/•]|\s{3,}", cleaned):
                term = part.strip(" .-")
                if 1 < len(term) <= 40:
                    terms.append(term)
        seen: set[str] = set()
        unique = []
        for term in terms:
            key = term.lower()
            if key not in seen:
                seen.add(key)
                unique.append(term)
        return unique[:120]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_entries(block: str, min_lines: int = 1) -> list[str]:
    """Split a section into entries on blank lines or new non-bullet headers."""
    if not block.strip():
        return []
    chunks: list[list[str]] = [[]]
    for line in block.split("\n"):
        if not line.strip():
            if chunks[-1]:
                chunks.append([])
            continue
        starts_entry = (
            bool(chunks[-1])
            and not BULLET_RE.match(line)
            and any(BULLET_RE.match(prev) for prev in chunks[-1])
        )
        if starts_entry:
            chunks.append([])
        chunks[-1].append(line)
    return ["\n".join(c) for c in chunks if len(c) >= min_lines]


def _split_title_org(header: str, date_text: str) -> tuple[str, str]:
    cleaned = header.replace(date_text, "").strip(" |,-–—")
    parts = [p.strip(" |,-–—") for p in re.split(r"\s\|\s|\s[-–—]\s|,\s(?=[A-Z])", cleaned) if p.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0][:120], ""
    return parts[0][:120], parts[1][:120]


def _months_between(start: str, end: str) -> int:
    def to_ym(token: str) -> tuple[int, int] | None:
        token = token.strip().lower().replace("'", "")
        if token in {"present", "current", "now", "ongoing"}:
            from datetime import date

            today = date.today()
            return today.year, today.month
        month_match = re.match(r"([a-z]{3})[a-z]*\.?\s*(\d{2,4})", token)
        if month_match:
            month = MONTHS.get(month_match.group(1), 1)
            year = int(month_match.group(2))
            year += 2000 if year < 100 else 0
            return year, month
        slash = re.match(r"(\d{1,2})/(\d{4})", token)
        if slash:
            return int(slash.group(2)), int(slash.group(1))
        year_only = re.match(r"((?:19|20)\d{2})", token)
        if year_only:
            return int(year_only.group(1)), 6
        return None

    a, b = to_ym(start), to_ym(end)
    if not a or not b:
        return 0
    months = (b[0] - a[0]) * 12 + (b[1] - a[1])
    return max(0, min(months, 480))


def _clean_url(url: str) -> str:
    return url.strip().rstrip(").,;").removeprefix("https://").removeprefix("http://")


def _first_token(text: str) -> str:
    match = re.search(r"[A-Za-z]+", text or "")
    return match.group(0).lower() if match else ""


_PARSER: ResumeParser | None = None


def get_resume_parser() -> ResumeParser:
    global _PARSER
    if _PARSER is None:
        _PARSER = ResumeParser()
    return _PARSER
