"""Ingestion CLI: OCR scanned past-exam booklets into the seed question bank.

Run with:  python -m app.ingestion.ingest  (or `make ingest`)

Pipeline
--------
1. Classify every PDF in the exams dir as an answer KEY (text grid) or a
   scanned BOOKLET (images).
2. Build a {year: {q_number: option}} map from the text answer keys
   (app/data/answer_keys.json, regenerated here).
3. For each scanned booklet, OCR questions 1..N with OpenAI vision, attach the
   correct option from the matching answer key, and collect passages.
4. Write app/data/seed/question_bank.json — the artifact that migration 0002
   seeds into the database on deploy.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
from pathlib import Path

from app.ingestion import answer_keys as ak

logger = logging.getLogger("ingest")

# Leading option enumerators captured by OCR, e.g. "1) ", "۲) ", "3. ", "(4) "
_OPT_PREFIX = re.compile(r"^\s*[\(]?[1-4۱-۴١-٤][\)\.\-]\s*")


def clean_option(text: str) -> str:
    return _OPT_PREFIX.sub("", text or "").strip()

DEFAULT_OUT = "app/data/seed/question_bank.json"
KEYS_OUT = "app/data/answer_keys.json"


def build_key_map(exams_dir: str, first_n: int) -> dict[int, dict[int, int]]:
    """{year: {q_number: correct_option(1-4)}} from text answer keys.

    Seeds from the committed app/data/answer_keys.json (which may include keys
    recovered from image-only answer sheets, e.g. 1394), then overlays keys
    parsed fresh from the text answer-key PDFs.
    """
    key_map: dict[int, dict[int, int]] = {}
    if Path(KEYS_OUT).exists():
        committed = json.loads(Path(KEYS_OUT).read_text(encoding="utf-8"))
        for y, k in committed.items():
            key_map[int(y)] = {int(q): int(o) for q, o in k.items()}
    for path in sorted(glob.glob(os.path.join(exams_dir, "*.pdf"))):
        text = ak.pdf_to_text(path)
        if not ak.is_answer_key(text):
            continue
        year = ak.year_from_name(path)
        if year is None:
            continue
        eng = ak.english_section_key(ak.parse_answer_key_text(text), first_n)
        if len(eng) >= first_n // 2:
            key_map[year] = eng
    return key_map


def discover_booklets(exams_dir: str) -> list[str]:
    """Question booklets to OCR.

    Every year PDF is a full scanned booklet (33-42 pages of question images),
    some of which also carry a text answer-key page — so we do NOT use the
    answer-key heuristic to exclude them. We only skip the standalone key files
    (their filename contains the Persian word «کلید» = "key").
    """
    booklets = []
    for path in sorted(glob.glob(os.path.join(exams_dir, "*.pdf"))):
        if "کلید" in Path(path).name:
            continue
        booklets.append(path)
    return booklets


def ingest(
    exams_dir: str,
    out_path: str,
    first_n: int,
    *,
    only_years: set[int] | None,
    allow_unkeyed: bool,
    merge: bool,
    max_pages: int = 10,
) -> dict:
    from app.ingestion.ocr import ExamOCR  # imported lazily (needs openai/pdf2image)

    key_map = build_key_map(exams_dir, first_n)
    Path(KEYS_OUT).parent.mkdir(parents=True, exist_ok=True)
    Path(KEYS_OUT).write_text(
        json.dumps(
            {str(y): {str(q): o for q, o in sorted(k.items())} for y, k in sorted(key_map.items())},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Answer keys available for years: %s", sorted(key_map))

    bank: dict[str, list] = {"passages": [], "questions": []}
    if merge and Path(out_path).exists():
        existing = json.loads(Path(out_path).read_text(encoding="utf-8"))
        bank["passages"] = existing.get("passages", [])
        bank["questions"] = existing.get("questions", [])

    ocr = ExamOCR()
    for pdf in discover_booklets(exams_dir):
        year = ak.year_from_name(pdf)
        if year is None or (only_years and year not in only_years):
            continue
        key = key_map.get(year, {})
        if not key and not allow_unkeyed:
            logger.warning("No answer key for %s (year %s) — skipping. Use --allow-unkeyed to keep.", pdf, year)
            continue

        logger.info("OCR booklet %s (year %s)…", pdf, year)
        try:
            result = ocr.extract(pdf, first_n=first_n, max_pages=max_pages)
        except Exception:  # noqa: BLE001
            logger.exception("OCR failed for %s", pdf)
            continue

        source = f"konkoor-{year}"
        # namespace passage keys per year to avoid collisions across exams
        for p in result["passages"]:
            bank["passages"].append(
                {
                    "key": f"{year}-{p['key']}",
                    "source": source,
                    "year": year,
                    "title": p.get("title"),
                    "body": p["body"],
                }
            )
        kept = 0
        seen_numbers: set[int] = set()
        for q in sorted(result["questions"], key=lambda x: x["number"]):
            num = q["number"]
            if num in seen_numbers:
                continue
            correct_opt = key.get(num)
            if correct_opt is None and not allow_unkeyed:
                continue
            options = [clean_option(o) for o in q["options"]]
            if any(not o for o in options):
                continue  # skip a question whose options didn't OCR cleanly
            seen_numbers.add(num)
            bank["questions"].append(
                {
                    "source": source,
                    "year": year,
                    "number": num,
                    "skill_type": q["skill_type"],
                    "stem": q["stem"].strip(),
                    "options": options,
                    "correct_index": (correct_opt - 1) if correct_opt else 0,
                    "explanation": None,
                    "passage_key": f"{year}-{q['passage_key']}" if q.get("passage_key") else None,
                }
            )
            kept += 1
        logger.info("  kept %d questions from year %s", kept, year)

    # Drop passages that ended up with no referencing question.
    used = {q["passage_key"] for q in bank["questions"] if q.get("passage_key")}
    bank["passages"] = [p for p in bank["passages"] if p["key"] in used]
    return bank


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR past konkoor exams into the seed bank.")
    parser.add_argument("--exams-dir", default="exams")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--first-n", type=int, default=30)
    parser.add_argument("--years", default="", help="comma-separated years to limit to")
    parser.add_argument("--allow-unkeyed", action="store_true",
                        help="keep questions even without a verified answer key")
    parser.add_argument("--merge", action="store_true",
                        help="merge into the existing bank instead of overwriting")
    parser.add_argument("--max-pages", type=int, default=10,
                        help="how many leading booklet pages to OCR (English section)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run OCR but do not write the bank file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    only = {int(y) for y in args.years.split(",") if y.strip()} or None

    bank = ingest(
        args.exams_dir, args.out, args.first_n,
        only_years=only, allow_unkeyed=args.allow_unkeyed, merge=args.merge,
        max_pages=args.max_pages,
    )
    print(f"Collected {len(bank['questions'])} questions / {len(bank['passages'])} passages.")
    if args.dry_run:
        print("Dry run — not writing.")
        return
    if not bank["questions"]:
        print("No questions collected; leaving existing seed file untouched.")
        return
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
