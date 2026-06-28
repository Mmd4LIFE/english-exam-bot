"""Shared helpers for handlers: DB sessions, timers, message editing."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.bot import keyboards as kb
from app.bot.render import render_question, render_result_summary
from app.db import repositories as repo
from app.db.base import SessionFactory
from app.db.models import ExamSession
from app.utils import remaining_seconds

logger = logging.getLogger(__name__)


@asynccontextmanager
async def db_session():
    session = SessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def ensure_user(update: Update) -> None:
    user = update.effective_user
    if user is None:
        return
    async with db_session() as session:
        await repo.upsert_user(
            session,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            language_code=user.language_code,
        )


def timer_job_name(session_id: int) -> str:
    return f"exam-timer:{session_id}"


def schedule_timer(context: ContextTypes.DEFAULT_TYPE, exam: ExamSession) -> None:
    """Schedule the auto-close job at the exam deadline."""
    if context.job_queue is None:
        logger.warning("JobQueue unavailable; timer not scheduled")
        return
    name = timer_job_name(exam.id)
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    delay = max(1, remaining_seconds(exam.deadline_at))
    context.job_queue.run_once(
        on_timer_expired,
        when=delay,
        name=name,
        data={
            "session_id": exam.id,
            "chat_id": exam.tg_chat_id,
            "message_id": exam.tg_message_id,
        },
    )


def cancel_timer(context: ContextTypes.DEFAULT_TYPE, session_id: int) -> None:
    if context.job_queue is None:
        return
    for job in context.job_queue.get_jobs_by_name(timer_job_name(session_id)):
        job.schedule_removal()


async def on_timer_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback: close the exam when time runs out."""
    data = context.job.data  # type: ignore[union-attr]
    session_id = data["session_id"]
    async with db_session() as session:
        exam = await repo.load_session(session, session_id)
        if exam is None or exam.status != "in_progress":
            return
        await repo.finalize_session(session, exam, expired=True)
        text = render_result_summary(exam, expired=True)
        markup = kb.review_open_keyboard(exam.id)
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except BadRequest as exc:
            logger.info("Could not edit expired exam message: %s", exc)


async def safe_answer(query, text: str | None = None, show_alert: bool = False) -> None:
    """Acknowledge a callback query, tolerating an expired/old query id.

    Telegram invalidates a callback query after ~15s. If a slow handler (e.g.
    exam generation) delayed processing, the ack can fail with "query is too
    old" — which is harmless and must not crash the handler.
    """
    try:
        await query.answer(text=text, show_alert=show_alert)
    except BadRequest as exc:
        msg = str(exc).lower()
        if "too old" not in msg and "invalid" not in msg and "not found" not in msg:
            raise


async def safe_edit(query, text: str, reply_markup=None) -> None:
    """Edit a callback message, ignoring harmless 'not modified'/old-query errors."""
    try:
        await query.edit_message_text(
            text=text, parse_mode="HTML", reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        msg = str(exc).lower()
        if "not modified" in msg or "too old" in msg or "invalid" in msg:
            return
        raise


async def show_current_question(query, exam: ExamSession) -> None:
    await safe_edit(query, render_question(exam), kb.question_keyboard(exam, exam.current_position))
