"""Build exam sessions from the question bank or via OpenAI generation."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories as repo
from app.db.models import (
    ExamSession,
    Origin,
    Passage,
    Question,
    SourceKind,
)
from app.services.openai_client import ExamGenerator, GenGroup

logger = logging.getLogger(__name__)


async def _style_examples(session: AsyncSession, limit: int = 6) -> str | None:
    """A few real bank questions, rendered as text, to steer generation style."""
    rows = (
        await session.execute(
            select(Question)
            .where(Question.origin == Origin.BANK)
            .order_by(Question.id)
            .limit(limit)
        )
    ).scalars().all()
    if not rows:
        return None
    lines = []
    for q in rows:
        opts = " / ".join(q.options)
        lines.append(f"- {q.stem} | options: {opts}")
    return "\n".join(lines)


async def _persist_generated(
    session: AsyncSession, groups: list[GenGroup]
) -> list[Question]:
    """Store generated groups as Passage/Question rows; return them in order."""
    ordered: list[Question] = []
    for g in groups:
        passage_id = None
        if g.passage_body:
            passage = Passage(
                source="ai", year=None, title=g.passage_title, body=g.passage_body
            )
            session.add(passage)
            await session.flush()
            passage_id = passage.id
        for gq in g.questions:
            q = Question(
                passage_id=passage_id,
                origin=Origin.AI,
                source="ai",
                year=None,
                number=None,
                skill_type=gq.skill,
                stem=gq.stem,
                options=gq.options,
                correct_index=gq.correct_index,
                explanation=gq.explanation,
            )
            session.add(q)
            ordered.append(q)
    await session.flush()
    return ordered


async def build_ai_session(
    session: AsyncSession, *, user_id: int, num_questions: int, duration_seconds: int
) -> ExamSession:
    generator = ExamGenerator()
    examples = await _style_examples(session)
    groups = await generator.generate(num_questions, style_examples=examples)
    questions = await _persist_generated(session, groups)
    if not questions:
        raise RuntimeError("Generation returned no questions")
    # Trim/keep to the requested count while keeping passage groups intact-ish.
    questions = questions[:num_questions]
    exam = await repo.create_session(
        session,
        user_id=user_id,
        source_kind=SourceKind.AI,
        source_label="AI generated",
        duration_seconds=duration_seconds,
        questions=questions,
    )
    return exam


async def build_bank_session(
    session: AsyncSession,
    *,
    user_id: int,
    year: int | None,
    num_questions: int,
    duration_seconds: int,
) -> ExamSession:
    questions = await repo.fetch_bank_questions(session, year, num_questions)
    if not questions:
        raise RuntimeError("No bank questions available")
    label = f"konkoor {year}" if year else "konkoor mixed"
    exam = await repo.create_session(
        session,
        user_id=user_id,
        source_kind=SourceKind.BANK,
        source_label=label,
        duration_seconds=duration_seconds,
        questions=questions,
    )
    return exam
