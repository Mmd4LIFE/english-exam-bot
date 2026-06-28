"""Async data-access helpers (repositories) used by the bot and services."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    ExamSession,
    Question,
    SessionQuestion,
    SessionStatus,
    User,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------- Users -----------------------------------------
async def upsert_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        session.add(user)
    else:
        user.username = username
        user.first_name = first_name
        user.language_code = language_code
        user.last_active_at = utcnow()
    await session.flush()
    return user


# ----------------------------- Question bank ---------------------------------
async def available_bank_years(session: AsyncSession) -> list[int]:
    rows = await session.execute(
        select(Question.year)
        .where(Question.origin == "bank", Question.year.is_not(None))
        .distinct()
        .order_by(Question.year.desc())
    )
    return [r[0] for r in rows.all()]


async def fetch_bank_questions(
    session: AsyncSession, year: int | None, limit: int
) -> list[Question]:
    """Fetch up to ``limit`` bank questions (optionally for one year), ordered."""
    stmt = (
        select(Question)
        .options(selectinload(Question.passage))
        .where(Question.origin == "bank")
    )
    if year is not None:
        stmt = stmt.where(Question.year == year).order_by(Question.number.asc())
    else:
        stmt = stmt.order_by(func.random())
    stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


# ----------------------------- Exam sessions ---------------------------------
async def get_active_session(
    session: AsyncSession, user_id: int
) -> ExamSession | None:
    stmt = (
        select(ExamSession)
        .where(
            ExamSession.user_id == user_id,
            ExamSession.status == SessionStatus.IN_PROGRESS,
        )
        .order_by(ExamSession.started_at.desc())
        .options(selectinload(ExamSession.items).selectinload(SessionQuestion.question))
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def load_session(
    session: AsyncSession, session_id: int
) -> ExamSession | None:
    stmt = (
        select(ExamSession)
        .where(ExamSession.id == session_id)
        .options(
            selectinload(ExamSession.items)
            .selectinload(SessionQuestion.question)
            .selectinload(Question.passage)
        )
    )
    return (await session.execute(stmt)).scalars().first()


async def create_session(
    session: AsyncSession,
    *,
    user_id: int,
    source_kind: str,
    source_label: str | None,
    duration_seconds: int,
    questions: list[Question],
) -> ExamSession:
    now = utcnow()
    exam = ExamSession(
        user_id=user_id,
        source_kind=source_kind,
        source_label=source_label,
        num_questions=len(questions),
        duration_seconds=duration_seconds,
        started_at=now,
        deadline_at=now + timedelta(seconds=duration_seconds),
        status=SessionStatus.IN_PROGRESS,
        current_position=0,
    )
    session.add(exam)
    await session.flush()  # assign exam.id

    for pos, q in enumerate(questions):
        session.add(
            SessionQuestion(session_id=exam.id, question_id=q.id, position=pos)
        )
    await session.flush()
    return exam


async def record_answer(
    session: AsyncSession,
    exam: ExamSession,
    position: int,
    selected_index: int,
) -> None:
    item = next((i for i in exam.items if i.position == position), None)
    if item is None:
        return
    item.selected_index = selected_index
    item.is_correct = selected_index == item.question.correct_index
    item.answered_at = utcnow()
    await session.flush()


async def finalize_session(
    session: AsyncSession, exam: ExamSession, *, expired: bool = False
) -> None:
    correct = sum(1 for i in exam.items if i.is_correct)
    exam.correct_count = correct
    exam.score = round(100.0 * correct / exam.num_questions, 1) if exam.num_questions else 0.0
    exam.status = SessionStatus.EXPIRED if expired else SessionStatus.FINISHED
    exam.finished_at = utcnow()
    await session.flush()


# ----------------------------- Stats -----------------------------------------
async def latest_finished_session(
    session: AsyncSession, user_id: int
) -> ExamSession | None:
    stmt = (
        select(ExamSession)
        .where(
            ExamSession.user_id == user_id,
            ExamSession.status.in_(
                [SessionStatus.FINISHED, SessionStatus.EXPIRED]
            ),
        )
        .order_by(ExamSession.finished_at.desc())
        .limit(1)
    )
    exam = (await session.execute(stmt)).scalars().first()
    return await load_session(session, exam.id) if exam else None


async def user_finished_sessions(
    session: AsyncSession, user_id: int, limit: int = 30
) -> list[ExamSession]:
    stmt = (
        select(ExamSession)
        .where(
            ExamSession.user_id == user_id,
            ExamSession.status.in_(
                [SessionStatus.FINISHED, SessionStatus.EXPIRED]
            ),
        )
        .order_by(ExamSession.finished_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def user_skill_breakdown(
    session: AsyncSession, user_id: int
) -> dict[str, tuple[int, int]]:
    """Return {skill_type: (correct, total)} across the user's finished exams."""
    stmt = (
        select(
            Question.skill_type,
            func.count(SessionQuestion.id),
            func.sum(case((SessionQuestion.is_correct.is_(True), 1), else_=0)),
        )
        .join(SessionQuestion, SessionQuestion.question_id == Question.id)
        .join(ExamSession, ExamSession.id == SessionQuestion.session_id)
        .where(
            ExamSession.user_id == user_id,
            ExamSession.status.in_(
                [SessionStatus.FINISHED, SessionStatus.EXPIRED]
            ),
            SessionQuestion.selected_index.is_not(None),
        )
        .group_by(Question.skill_type)
    )
    result: dict[str, tuple[int, int]] = {}
    for skill, total, correct in (await session.execute(stmt)).all():
        result[skill] = (int(correct or 0), int(total or 0))
    return result
