"""Post-exam review: browse every answer, jump to any question number."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import keyboards as kb
from app.bot.handlers.common import db_session, safe_answer, safe_edit
from app.bot.render import render_result_summary, render_review_question
from app.db import repositories as repo


async def review_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")  # rev:open | rev:grid | rev:q:<pos>
    action = parts[1]
    user_id = update.effective_user.id

    async with db_session() as session:
        exam = await repo.latest_finished_session(session, user_id)
        if exam is None:
            await safe_edit(query, "No finished exam to review yet.", kb.main_menu())
            return

        if action == "open":
            text = render_result_summary(exam, expired=exam.status == "expired")
            markup = kb.review_open_keyboard(exam.id)
        elif action == "grid":
            text = (
                "🔍 <b>Review — pick a question</b>\n"
                "✅ correct  ❌ wrong  ▫️ blank"
            )
            markup = kb.jump_grid(exam, review=True)
        elif action == "q":
            pos = max(0, min(exam.num_questions - 1, int(parts[2])))
            text = render_review_question(exam, pos)
            markup = kb.review_question_keyboard(pos, exam.num_questions)
        else:
            return

    await safe_edit(query, text, markup)
