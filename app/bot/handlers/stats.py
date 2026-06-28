"""Score tracker: textual summary + matplotlib charts."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import keyboards as kb
from app.bot.handlers.common import db_session, ensure_user
from app.db import repositories as repo
from app.services import charts


async def _gather(user_id: int):
    async with db_session() as session:
        sessions = await repo.user_finished_sessions(session, user_id, limit=30)
        breakdown = await repo.user_skill_breakdown(session, user_id)
    return sessions, breakdown


async def _send_stats(chat, user_id: int) -> None:
    sessions, breakdown = await _gather(user_id)
    finished = [s for s in sessions if s.score is not None]
    if not finished:
        await chat.send_message(
            "📊 You haven't finished any exams yet.\n\n"
            "Take one with /newexam and your progress will show up here!",
            reply_markup=kb.main_menu(),
        )
        return

    scores = [s.score or 0.0 for s in finished]
    avg = sum(scores) / len(scores)
    best = max(scores)
    last = scores[-1]
    summary = (
        f"📊 <b>Your stats</b>\n\n"
        f"Exams taken: <b>{len(finished)}</b>\n"
        f"Average score: <b>{avg:.0f}%</b>\n"
        f"Best score: <b>{best:.0f}%</b>\n"
        f"Last score: <b>{last:.0f}%</b>"
    )
    await chat.send_message(summary, parse_mode="HTML")

    labels = [f"#{i+1}" for i in range(len(finished))]
    await chat.send_photo(charts.progress_chart(scores, labels), caption="Score progress")
    if any(t for _, t in breakdown.values()):
        await chat.send_photo(charts.skill_chart(breakdown), caption="Accuracy by skill",
                              reply_markup=kb.main_menu())


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """From the inline menu (callback)."""
    query = update.callback_query
    if query:
        await query.answer()
    await _send_stats(update.effective_chat, update.effective_user.id)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    await _send_stats(update.effective_chat, update.effective_user.id)
