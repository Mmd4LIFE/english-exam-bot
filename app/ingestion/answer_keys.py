"""Parse konkoor answer-key PDFs (text-based) into {question_number: option}.

The official answer-key booklets are text PDFs whose grid lists, left to right,
pairs of (question number, correct option). Persian/RTL control characters are
interleaved with Western digits, so we strip control characters first and then
greedily pair plausible (number, option 1-4) tokens. The grid dominates, so a
last-write-wins dict reliably recovers the key for questions 1-30.
"""
from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path

# Bidi / formatting control characters that wrap the digits in these PDFs.
_CONTROL_RE = re.compile(r"[‌‍‎‏‪-‮⁦-⁩­]")
_TOKEN_RE = re.compile(r"\d+")

MAX_Q = 320  # exams go up to ~305 questions


def pdf_to_text(path: str | Path) -> str:
    """Extract layout text via poppler's pdftotext (returns '' if unavailable)."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            check=True,
        )
        return out.stdout.decode("utf-8", errors="ignore")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_RE.sub("", text)
    # Map Persian/Arabic-Indic digits to ASCII just in case.
    trans = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
    trans.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
    return text.translate(trans)


def parse_answer_key_text(text: str) -> dict[int, int]:
    """Return {question_number: correct_option(1-4)} parsed from key-grid text."""
    tokens = [int(t) for t in _TOKEN_RE.findall(_clean(text))]
    key: dict[int, int] = {}
    i = 0
    n = len(tokens)
    while i < n - 1:
        q, opt = tokens[i], tokens[i + 1]
        if 1 <= q <= MAX_Q and 1 <= opt <= 4:
            key[q] = opt  # last write wins → grid overrides stray numbers
            i += 2
        else:
            i += 1
    return key


def is_answer_key(text: str) -> bool:
    """Heuristic: a real key yields many (number, 1-4) pairs."""
    return len(parse_answer_key_text(text)) >= 30


def year_from_name(path: str | Path) -> int | None:
    m = re.search(r"(1[34]\d\d|9\d)", Path(path).stem)
    if not m:
        return None
    val = int(m.group(1))
    return val + 1300 if val < 100 else val  # 99 -> 1399


def english_section_key(key: dict[int, int], first_n: int = 30) -> dict[int, int]:
    """Keep only the English section (questions 1..first_n)."""
    return {q: key[q] for q in range(1, first_n + 1) if q in key}
