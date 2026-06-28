"""/start, /help, and main-menu routing."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import keyboards as kb
from app.bot.handlers.common import db_session, ensure_user, safe_edit
from app.db import repositories as repo

WELCOME = (
    "👋 <b>Welcome to the English Exam Bot</b>\n\n"
    "Practise konkoor-style English exams:\n"
    "• 🤖 AI-generated exams or 📚 real past konkoor questions\n"
    "• Choose 25/30 questions and your own time limit ⏱\n"
    "• Navigate freely, then review every answer 🔍\n"
    "• Track your progress with charts 📊\n\n"
    "Pick an option to begin:"
)

HELP = (
    "<b>ℹ️ How it works</b>\n\n"
    "1️⃣ <b>New exam</b> → pick a source (AI or real past konkoor), "
    "the number of questions, and a time limit.\n"
    "2️⃣ Answer with the <b>A–D</b> buttons. Use <b>◀ Back</b>, <b>Next ▶</b> "
    "and <b>🔢</b> to jump to any question.\n"
    "3️⃣ When time runs out (or you tap <b>🏁 Finish</b>) the exam closes "
    "automatically.\n"
    "4️⃣ <b>Review</b> every question — correct answers and explanations — and "
    "jump to any question number.\n"
    "5️⃣ <b>📊 My stats</b> shows your score progress and accuracy by skill.\n\n"
    "Commands: /start /newexam /stats /help"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    await update.effective_message.reply_html(WELCOME, reply_markup=kb.main_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(HELP, reply_markup=kb.main_menu())


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route ``menu:*`` callbacks to the right feature."""
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "home":
        await safe_edit(query, WELCOME, kb.main_menu())
    elif action == "help":
        await safe_edit(query, HELP, kb.main_menu())
    elif action == "new":
        from app.bot.handlers.exam import prompt_source

        await prompt_source(update, context)
    elif action == "stats":
        from app.bot.handlers.stats import show_stats

        await show_stats(update, context)
