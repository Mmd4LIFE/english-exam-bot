"""Exam lifecycle: setup wizard, navigation, answering, finishing."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import keyboards as kb
from app.bot.handlers.common import (
    cancel_timer,
    db_session,
    safe_answer,
    safe_edit,
    schedule_timer,
    show_current_question,
)
from app.bot.render import render_question, render_result_summary
from app.config import get_settings
from app.db import repositories as repo
from app.db.models import ExamSession
from app.services.exam_service import build_ai_session, build_bank_session
from app.utils import remaining_seconds

logger = logging.getLogger(__name__)
settings = get_settings()


# --------------------------------------------------------------------------- #
#  Setup wizard
# --------------------------------------------------------------------------- #
async def prompt_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    async with db_session() as session:
        active = await repo.get_active_session(session, user_id)
        years = await repo.available_bank_years(session)
        has_active = active is not None and remaining_seconds(active.deadline_at) > 0

    context.user_data["new_years"] = years
    if has_active:
        text = (
            "⚠️ <b>You already have an exam in progress.</b>\n\n"
            "Resume it, or abandon it and start a new one?"
        )
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("▶️ Resume", callback_data=f"{kb.CB_NAV}:resume")],
                [InlineKeyboardButton("🆕 Abandon & new", callback_data=f"{kb.CB_NAV}:abandon")],
                [InlineKeyboardButton("« Menu", callback_data=f"{kb.CB_MENU}:home")],
            ]
        )
        await safe_edit(query, text, markup)
        return

    await safe_edit(
        query,
        "📝 <b>New exam</b>\n\nChoose your question source:",
        kb.source_menu(has_bank=bool(years)),
    )


async def on_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_answer(query)
    source = query.data.split(":", 1)[1]
    context.user_data["new_source"] = source

    if source == "bank":
        years = context.user_data.get("new_years") or []
        await safe_edit(
            query,
            "📚 <b>Real past konkoor</b>\n\nChoose a year (or a mixed set):",
            kb.year_menu(years),
        )
    else:
        await safe_edit(
            query,
            "🤖 <b>AI-generated exam</b>\n\nHow many questions?",
            kb.count_menu(),
        )


async def on_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_answer(query)
    raw = query.data.split(":", 1)[1]
    context.user_data["new_year"] = None if raw == "mixed" else int(raw)
    await safe_edit(query, "How many questions?", kb.count_menu())


async def on_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_answer(query)
    context.user_data["new_count"] = int(query.data.split(":", 1)[1])
    await safe_edit(
        query,
        "⏱ <b>Time limit</b>\n\nWhen the time is up, the exam closes "
        "automatically. Pick a duration:",
        kb.time_menu(settings.time_choices),
    )


async def on_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Final step — build the exam and show question 1 in this same message."""
    query = update.callback_query
    await safe_answer(query)
    minutes = int(query.data.split(":", 1)[1])
    duration = minutes * 60
    user_id = update.effective_user.id
    source = context.user_data.get("new_source", "ai")
    count = context.user_data.get("new_count", settings.default_num_questions)
    year = context.user_data.get("new_year")

    if source == "ai":
        await safe_edit(
            query,
            "⏳ <b>Generating your exam…</b>\nThis can take a few seconds while the "
            "AI writes fresh questions.",
        )

    try:
        async with db_session() as session:
            if source == "ai":
                exam = await build_ai_session(
                    session, user_id=user_id, num_questions=count,
                    duration_seconds=duration,
                )
            else:
                exam = await build_bank_session(
                    session, user_id=user_id, year=year, num_questions=count,
                    duration_seconds=duration,
                )
            exam.tg_chat_id = query.message.chat_id
            exam.tg_message_id = query.message.message_id
            await session.flush()
            exam = await repo.load_session(session, exam.id)
            text = render_question(exam)
            markup = kb.question_keyboard(exam, exam.current_position)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build exam")
        await safe_edit(
            query,
            "⚠️ Sorry, I couldn't build the exam right now. Please try again.",
            kb.main_menu(),
        )
        return

    schedule_timer(context, exam)
    context.user_data.pop("new_source", None)
    context.user_data.pop("new_year", None)
    context.user_data.pop("new_count", None)
    await safe_edit(query, text, markup)


# --------------------------------------------------------------------------- #
#  In-exam interaction
# --------------------------------------------------------------------------- #
async def _expire_if_needed(query, context, session, exam: ExamSession) -> bool:
    """If the deadline passed, finalize and show the summary. Returns True if expired."""
    if remaining_seconds(exam.deadline_at) > 0:
        return False
    await repo.finalize_session(session, exam, expired=True)
    cancel_timer(context, exam.id)
    await safe_edit(
        query, render_result_summary(exam, expired=True), kb.review_open_keyboard(exam.id)
    )
    return True


async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    selected = int(query.data.split(":", 1)[1])
    user_id = update.effective_user.id
    async with db_session() as session:
        exam = await repo.get_active_session(session, user_id)
        if exam is None:
            await safe_answer(query, "This exam is closed.", show_alert=False)
            return
        if await _expire_if_needed(query, context, session, exam):
            await safe_answer(query, "⏰ Time is up!")
            return
        await repo.record_answer(session, exam, exam.current_position, selected)
        # auto-advance to the next question ("remove" the answered one)
        if exam.current_position < exam.num_questions - 1:
            exam.current_position += 1
        await session.flush()
        exam = await repo.load_session(session, exam.id)
        text = render_question(exam)
        markup = kb.question_keyboard(exam, exam.current_position)
    await safe_answer(query, "Saved ✓")
    await safe_edit(query, text, markup)


async def on_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action = query.data.split(":", 1)[1]
    user_id = update.effective_user.id

    async with db_session() as session:
        exam = await repo.get_active_session(session, user_id)
        if exam is None:
            await safe_answer(query, "This exam is closed.", show_alert=False)
            return

        if action in ("back", "next", "resume", "jumpmenu"):
            if await _expire_if_needed(query, context, session, exam):
                await safe_answer(query, "⏰ Time is up!")
                return

        if action == "back":
            exam.current_position = max(0, exam.current_position - 1)
        elif action == "next":
            exam.current_position = min(exam.num_questions - 1, exam.current_position + 1)
        elif action == "abandon":
            await repo.finalize_session(session, exam, expired=False)
            cancel_timer(context, exam.id)
            await safe_answer(query, "Old exam abandoned.")
            await safe_edit(
                query, "📝 <b>New exam</b>\n\nChoose your question source:",
                kb.source_menu(has_bank=bool(await repo.available_bank_years(session))),
            )
            return
        elif action == "jumpmenu":
            await safe_answer(query)
            await safe_edit(
                query,
                "🔢 <b>Jump to question</b>\n🔵 answered  ⚪ blank",
                kb.jump_grid(exam, review=False),
            )
            return
        elif action == "finish":
            answered = sum(1 for i in exam.items if i.selected_index is not None)
            await safe_answer(query)
            await safe_edit(
                query,
                "🏁 <b>Finish exam?</b>\n\nYou can still go back and keep answering.",
                kb.confirm_finish_keyboard(answered, exam.num_questions),
            )
            return
        elif action == "confirm":
            await repo.finalize_session(session, exam, expired=False)
            cancel_timer(context, exam.id)
            exam = await repo.load_session(session, exam.id)
            await safe_answer(query, "Exam finished!")
            await safe_edit(
                query, render_result_summary(exam), kb.review_open_keyboard(exam.id)
            )
            return

        await session.flush()
        exam = await repo.load_session(session, exam.id)
        text = render_question(exam)
        markup = kb.question_keyboard(exam, exam.current_position)

    await safe_answer(query)
    await safe_edit(query, text, markup)


async def on_jump(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    pos = int(query.data.split(":", 1)[1])
    user_id = update.effective_user.id
    async with db_session() as session:
        exam = await repo.get_active_session(session, user_id)
        if exam is None:
            await safe_answer(query, "This exam is closed.")
            return
        if await _expire_if_needed(query, context, session, exam):
            await safe_answer(query, "⏰ Time is up!")
            return
        exam.current_position = max(0, min(exam.num_questions - 1, pos))
        await session.flush()
        exam = await repo.load_session(session, exam.id)
        text = render_question(exam)
        markup = kb.question_keyboard(exam, exam.current_position)
    await safe_answer(query)
    await safe_edit(query, text, markup)


async def newexam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newexam — start the wizard from a command (sends a fresh message)."""
    msg = await update.effective_message.reply_html("📝 <b>New exam</b>")
    # Re-use the callback flow by faking a query target: simplest is to show menu.
    async with db_session() as session:
        years = await repo.available_bank_years(session)
    await msg.edit_text(
        "📝 <b>New exam</b>\n\nChoose your question source:",
        parse_mode="HTML",
        reply_markup=kb.source_menu(has_bank=bool(years)),
    )
    context.user_data["new_years"] = years
