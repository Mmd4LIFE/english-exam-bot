"""Extract English questions (1-30) from scanned konkoor booklets via OpenAI vision.

The question booklets are scanned images, so plain text extraction fails. We
render the first pages to images and ask a vision model to transcribe the
English multiple-choice section into structured JSON. Correct answers come from
the official answer key (see ``answer_keys.py``), not from the booklet image.
"""
from __future__ import annotations

import base64
import io
import json
import logging

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

_OCR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string"},
                    "title": {"type": ["string", "null"]},
                    "body": {"type": "string"},
                },
                "required": ["key", "title", "body"],
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "number": {"type": "integer"},
                    "skill_type": {
                        "type": "string",
                        "enum": ["grammar", "vocabulary", "cloze", "reading"],
                    },
                    "passage_key": {"type": ["string", "null"]},
                    "stem": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
                "required": ["number", "skill_type", "passage_key", "stem", "options"],
            },
        },
    },
    "required": ["passages", "questions"],
}

_PROMPT = (
    "These images are scanned pages of an Iranian graduate entrance exam "
    "(konkoor). Find the ENGLISH section — multiple-choice questions numbered "
    "1 to {n} (grammar/structure, vocabulary, cloze, and reading comprehension). "
    "Transcribe EACH question exactly as printed:\n"
    "- Keep the original English text of the stem and all four options.\n"
    "- For cloze and reading questions, also transcribe the shared passage into "
    "the `passages` array with a unique `key`, and reference it via "
    "`passage_key` on each related question.\n"
    "- For standalone grammar/vocabulary questions set `passage_key` to null.\n"
    "- Classify each question's skill_type.\n"
    "- Do NOT include the answer; only the printed question and options.\n"
    "- Ignore any non-English (Persian) sections entirely.\n"
    "Return only questions you can read with confidence."
)


def _images_b64(pdf_path: str, dpi: int, first_page: int, last_page: int) -> list[str]:
    from pdf2image import convert_from_path

    images = convert_from_path(
        pdf_path, dpi=dpi, first_page=first_page, last_page=last_page
    )
    encoded = []
    for img in images:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
        encoded.append(base64.b64encode(buf.getvalue()).decode())
    return encoded


class ExamOCR:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_ocr_model

    def extract(
        self,
        pdf_path: str,
        *,
        first_n: int = 30,
        dpi: int = 150,
        max_pages: int = 8,
    ) -> dict:
        images = _images_b64(pdf_path, dpi, 1, max_pages)
        content: list[dict] = [{"type": "text", "text": _PROMPT.format(n=first_n)}]
        for b64 in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
                }
            )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ocr_exam",
                    "strict": True,
                    "schema": _OCR_SCHEMA,
                },
            },
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        questions = [
            q for q in data.get("questions", [])
            if len(q.get("options", [])) == 4 and 1 <= q.get("number", 0) <= first_n
        ]
        logger.info("OCR %s → %d questions", pdf_path, len(questions))
        return {"passages": data.get("passages", []), "questions": questions}
