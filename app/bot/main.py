"""Bot entrypoint: wiring, startup recovery, and polling loop."""
from __future__ import annotations

import logging

from sqlalchemy import select
from telegram import BotCommand
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
)

from app.bot import keyboards as kb
from app.bot.handlers import exam, review, start, stats
from app.bot.handlers.common import on_timer_expired, timer_job_name
from app.bot.render import render_result_summary
from app.config import get_settings
from app.db import repositories as repo
from app.db.base import SessionFactory
from app.db.models import ExamSession, SessionStatus
from app.utils import remaining_seconds

logger = logging.getLogger(__name__)


async def _recover_sessions(application: Application) -> None:
    """On startup, expire overdue exams and reschedule live timers.

    This makes the bot safe to restart / ``docker compose up`` at any time:
    in-progress exams are never silently lost.
    """
    async with SessionFactory() as session:
        rows = (
            await session.execute(
                select(ExamSession).where(
                    ExamSession.status == SessionStatus.IN_PROGRESS
                )
            )
        ).scalars().all()

        for row in rows:
            exam_obj = await repo.load_session(session, row.id)
            if exam_obj is None:
                continue
            remaining = remaining_seconds(exam_obj.deadline_at)
            if remaining <= 0:
                await repo.finalize_session(session, exam_obj, expired=True)
                if exam_obj.tg_chat_id and exam_obj.tg_message_id:
                    try:
                        await application.bot.edit_message_text(
                            text=render_result_summary(exam_obj, expired=True),
                            chat_id=exam_obj.tg_chat_id,
                            message_id=exam_obj.tg_message_id,
                            parse_mode="HTML",
                            reply_markup=kb.review_open_keyboard(exam_obj.id),
                        )
                    except BadRequest:
                        pass
            else:
                application.job_queue.run_once(
                    on_timer_expired,
                    when=remaining,
                    name=timer_job_name(exam_obj.id),
                    data={
                        "session_id": exam_obj.id,
                        "chat_id": exam_obj.tg_chat_id,
                        "message_id": exam_obj.tg_message_id,
                    },
                )
        await session.commit()
    logger.info("Session recovery complete (%d in-progress checked)", len(rows))


async def _index_rag() -> None:
    """Embed the seeded question bank into Qdrant (idempotent, best-effort)."""
    import asyncio

    from sqlalchemy import select as _select

    from app.db.models import Origin, Question
    from app.services.rag import RagStore

    try:
        async with SessionFactory() as session:
            rows = (
                await session.execute(
                    _select(Question).where(Question.origin == Origin.BANK)
                )
            ).scalars().all()
            payload = [
                {
                    "id": q.id,
                    "stem": q.stem,
                    "options": q.options,
                    "skill_type": q.skill_type,
                    "year": q.year,
                }
                for q in rows
            ]
        if payload:
            await asyncio.to_thread(RagStore().index_questions, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG indexing on startup failed (non-fatal): %s", exc)


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start the bot / main menu"),
            BotCommand("newexam", "Start a new exam"),
            BotCommand("stats", "Show my score progress"),
            BotCommand("help", "How it works"),
        ]
    )
    await _recover_sessions(application)
    await _index_rag()


async def _on_error(update: object, context) -> None:
    """Log unhandled handler errors instead of crashing the update loop."""
    logger.error("Unhandled exception while processing update", exc_info=context.error)


def build_application() -> Application:
    settings = get_settings()
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        # Process updates concurrently so a slow handler (e.g. AI exam
        # generation, ~20-30s) does not block answering other callbacks and
        # cause "query is too old" errors.
        .concurrent_updates(True)
        .build()
    )
    application.add_error_handler(_on_error)

    application.add_handler(CommandHandler("start", start.start_command))
    application.add_handler(CommandHandler("help", start.help_command))
    application.add_handler(CommandHandler("newexam", exam.newexam_command))
    application.add_handler(CommandHandler("stats", stats.stats_command))

    application.add_handler(CallbackQueryHandler(start.menu_router, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(exam.on_source, pattern=r"^src:"))
    application.add_handler(CallbackQueryHandler(exam.on_year, pattern=r"^year:"))
    application.add_handler(CallbackQueryHandler(exam.on_count, pattern=r"^count:"))
    application.add_handler(CallbackQueryHandler(exam.on_time, pattern=r"^time:"))
    application.add_handler(CallbackQueryHandler(exam.on_answer, pattern=r"^ans:"))
    application.add_handler(CallbackQueryHandler(exam.on_nav, pattern=r"^nav:"))
    application.add_handler(CallbackQueryHandler(exam.on_jump, pattern=r"^jump:"))
    application.add_handler(CallbackQueryHandler(review.review_router, pattern=r"^rev:"))

    return application


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    application = build_application()
    logger.info("Bot starting (polling)…")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
