"""OpenAI-backed generation of konkoor-style English exams.

The real konkoor (arshad) English section is entirely **reading
comprehension**: several passages, each followed by exactly 5 questions. The
generator mirrors that — it produces only passage groups (no standalone
grammar/vocabulary items), each with exactly four options and one correct
answer.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

QUESTIONS_PER_PASSAGE = 5


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
        "passages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "questions": {
                        "type": "array",
                        "minItems": QUESTIONS_PER_PASSAGE,
                        "maxItems": QUESTIONS_PER_PASSAGE,
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
                "required": ["title", "body", "questions"],
            },
        }
    },
    "required": ["passages"],
}


_SYSTEM_PROMPT = (
    "You are an expert item-writer for the English (reading comprehension) "
    "section of the Iranian national graduate entrance exam (konkoor "
    "karshenasi arshad). You write academically rigorous, unambiguous "
    "passage-based multiple-choice questions that mirror that exam's style and "
    "difficulty."
)


def _build_user_prompt(num_passages: int, examples: str | None) -> str:
    prompt = (
        f"Create a complete English reading-comprehension exam with EXACTLY "
        f"{num_passages} passages. EVERY passage must have EXACTLY "
        f"{QUESTIONS_PER_PASSAGE} questions (so {num_passages * QUESTIONS_PER_PASSAGE} "
        f"questions in total).\n\n"
        "Requirements:\n"
        "- Each passage is an original academic/expository text of 130-220 words "
        "on a varied topic (science, psychology, history, society, technology, "
        "the arts).\n"
        f"- Each passage is followed by EXACTLY {QUESTIONS_PER_PASSAGE} questions "
        "covering a mix of: main idea/purpose, specific detail, vocabulary-in-"
        "context, inference, and reference/tone.\n"
        "- Do NOT write standalone grammar or vocabulary questions — every "
        "question must be answerable from its passage.\n"
        "- Every question has EXACTLY four options; correct_index is 0-based "
        "(0..3).\n"
        "- Keep each explanation to one concise sentence.\n"
        "- Output must be valid against the provided JSON schema."
    )
    if examples:
        prompt += (
            "\n\nHere are real past konkoor questions for STYLE reference only — "
            "do not copy them, generate fresh passages in the same spirit:\n"
            + examples
        )
    return prompt


class ExamGenerator:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_gen_model

    async def generate(
        self, num_questions: int, style_examples: str | None = None
    ) -> list[GenGroup]:
        num_passages = max(1, math.ceil(num_questions / QUESTIONS_PER_PASSAGE))
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_prompt(num_passages, style_examples),
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
        for p in payload.get("passages", []):
            questions = [
                GenQuestion(
                    skill="reading",
                    stem=q["stem"],
                    options=q["options"],
                    correct_index=int(q["correct_index"]),
                    explanation=q.get("explanation", ""),
                )
                for q in p.get("questions", [])
                if len(q.get("options", [])) == 4
            ]
            if questions:
                groups.append(
                    GenGroup(
                        skill="reading",
                        passage_title=p.get("title"),
                        passage_body=p.get("body"),
                        questions=questions,
                    )
                )
        logger.info(
            "Generated %d passages / %d questions",
            len(groups),
            sum(len(g.questions) for g in groups),
        )
        return groups
