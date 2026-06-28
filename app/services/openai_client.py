"""OpenAI-backed generation of konkoor-style English exams.

Produces a structured set of question *groups*. A group is either a set of
standalone questions (grammar / vocabulary) or a passage (cloze / reading) with
its questions. Every question has exactly four options and one correct index.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class GenQuestion:
    skill: str
    stem: str
    options: list[str]
    correct_index: int
    explanation: str


@dataclass
class GenGroup:
    skill: str
    passage_title: str | None
    passage_body: str | None
    questions: list[GenQuestion]


_EXAM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "skill": {
                        "type": "string",
                        "enum": ["grammar", "vocabulary", "cloze", "reading"],
                    },
                    "passage_title": {"type": ["string", "null"]},
                    "passage_body": {"type": ["string", "null"]},
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "stem": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 4,
                                    "maxItems": 4,
                                },
                                "correct_index": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 3,
                                },
                                "explanation": {"type": "string"},
                            },
                            "required": [
                                "stem",
                                "options",
                                "correct_index",
                                "explanation",
                            ],
                        },
                    },
                },
                "required": [
                    "skill",
                    "passage_title",
                    "passage_body",
                    "questions",
                ],
            },
        }
    },
    "required": ["groups"],
}


_SYSTEM_PROMPT = (
    "You are an expert item-writer for the English section of the Iranian "
    "national graduate entrance exam (konkoor karshenasi arshad). You write "
    "academically rigorous, unambiguous multiple-choice English questions that "
    "mirror that exam's style and difficulty."
)


def _build_user_prompt(num_questions: int, examples: str | None) -> str:
    blueprint = (
        "Create a complete English exam with EXACTLY {n} questions total, "
        "distributed to match the konkoor structure:\n"
        "- ~6 standalone GRAMMAR questions (sentence-completion).\n"
        "- ~6 standalone VOCABULARY questions (sentence-completion).\n"
        "- one CLOZE passage (a short paragraph with numbered blanks) whose "
        "questions test grammar/vocabulary in context.\n"
        "- one or two READING passages (120-200 words each) followed by "
        "comprehension questions.\n"
        "Adjust the per-section counts so the TOTAL is exactly {n}.\n\n"
        "Hard rules:\n"
        "- Every question has EXACTLY four options.\n"
        "- correct_index is 0-based (0..3) and points to the correct option.\n"
        "- For standalone questions, passage_title and passage_body are null.\n"
        "- For cloze/reading groups, fill passage_title and passage_body and "
        "put the related questions in that group; in cloze stems refer to the "
        "blanks (e.g. 'Blank (1) ...').\n"
        "- Keep each explanation to one concise sentence.\n"
        "- Output must be valid against the provided JSON schema."
    ).format(n=num_questions)
    if examples:
        blueprint += (
            "\n\nHere are real past questions for STYLE reference only — do not "
            "copy them, generate fresh items in the same spirit:\n" + examples
        )
    return blueprint


class ExamGenerator:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_gen_model

    async def generate(
        self, num_questions: int, style_examples: str | None = None
    ) -> list[GenGroup]:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(num_questions, style_examples),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "english_exam",
                    "strict": True,
                    "schema": _EXAM_SCHEMA,
                },
            },
            temperature=0.7,
        )
        payload = json.loads(resp.choices[0].message.content or "{}")
        groups: list[GenGroup] = []
        for g in payload.get("groups", []):
            questions = [
                GenQuestion(
                    skill=g["skill"],
                    stem=q["stem"],
                    options=q["options"],
                    correct_index=int(q["correct_index"]),
                    explanation=q.get("explanation", ""),
                )
                for q in g.get("questions", [])
                if len(q.get("options", [])) == 4
            ]
            if questions:
                groups.append(
                    GenGroup(
                        skill=g["skill"],
                        passage_title=g.get("passage_title"),
                        passage_body=g.get("passage_body"),
                        questions=questions,
                    )
                )
        logger.info(
            "Generated %d groups / %d questions",
            len(groups),
            sum(len(g.questions) for g in groups),
        )
        return groups
