"""Inline keyboard builders for the exam bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import ExamSession, SessionQuestion
from app.utils import OPTION_LETTERS

# --- callback-data prefixes ---
CB_MENU = "menu"          # menu:new | menu:stats | menu:help | menu:home
CB_SOURCE = "src"         # src:ai | src:bank
CB_YEAR = "year"          # year:1402 | year:mixed
CB_COUNT = "count"        # count:25 | count:30
CB_TIME = "time"          # time:20  (minutes) -> starts exam
CB_ANS = "ans"            # ans:<idx>
CB_NAV = "nav"            # nav:back | nav:next | nav:jumpmenu | nav:finish | nav:confirm | nav:resume
CB_JUMP = "jump"          # jump:<pos>
CB_REVIEW = "rev"         # rev:open | rev:q:<pos> | rev:grid


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 New exam", callback_data=f"{CB_MENU}:new")],
            [InlineKeyboardButton("📊 My stats", callback_data=f"{CB_MENU}:stats")],
            [InlineKeyboardButton("ℹ️ Help", callback_data=f"{CB_MENU}:help")],
        ]
    )


def source_menu(has_bank: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🤖 AI-generated exam", callback_data=f"{CB_SOURCE}:ai")]]
    if has_bank:
        rows.append(
            [InlineKeyboardButton("📚 Real past konkoor", callback_data=f"{CB_SOURCE}:bank")]
        )
    rows.append([InlineKeyboardButton("« Back", callback_data=f"{CB_MENU}:home")])
    return InlineKeyboardMarkup(rows)


def year_menu(years: list[int]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for y in years:
        row.append(InlineKeyboardButton(str(y), callback_data=f"{CB_YEAR}:{y}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🎲 Mixed", callback_data=f"{CB_YEAR}:mixed")])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"{CB_MENU}:new")])
    return InlineKeyboardMarkup(rows)


def count_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("25 questions", callback_data=f"{CB_COUNT}:25"),
                InlineKeyboardButton("30 questions", callback_data=f"{CB_COUNT}:30"),
            ],
            [InlineKeyboardButton("« Back", callback_data=f"{CB_MENU}:new")],
        ]
    )


def time_menu(options: list[int]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for m in options:
        row.append(InlineKeyboardButton(f"⏱ {m} min", callback_data=f"{CB_TIME}:{m}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def question_keyboard(exam: ExamSession, position: int) -> InlineKeyboardMarkup:
    item = next((i for i in exam.items if i.position == position), None)
    selected = item.selected_index if item else None
    total = exam.num_questions

    opt_row = []
    for idx, letter in enumerate(OPTION_LETTERS):
        label = f"● {letter}" if selected == idx else letter
        opt_row.append(InlineKeyboardButton(label, callback_data=f"{CB_ANS}:{idx}"))

    nav = []
    if position > 0:
        nav.append(InlineKeyboardButton("◀ Back", callback_data=f"{CB_NAV}:back"))
    nav.append(
        InlineKeyboardButton(
            f"🔢 {position + 1}/{total}", callback_data=f"{CB_NAV}:jumpmenu"
        )
    )
    if position < total - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"{CB_NAV}:next"))

    last_row = [InlineKeyboardButton("🏁 Finish exam", callback_data=f"{CB_NAV}:finish")]
    return InlineKeyboardMarkup([opt_row, nav, last_row])


def jump_grid(exam: ExamSession, *, review: bool = False) -> InlineKeyboardMarkup:
    """Grid of question numbers; answered ones marked. Used for jump & review."""
    rows, row = [], []
    for item in sorted(exam.items, key=lambda i: i.position):
        n = item.position + 1
        if review:
            mark = "✅" if item.is_correct else ("❌" if item.selected_index is not None else "▫️")
            cb = f"{CB_REVIEW}:q:{item.position}"
        else:
            mark = "🔵" if item.selected_index is not None else "⚪"
            cb = f"{CB_JUMP}:{item.position}"
        row.append(InlineKeyboardButton(f"{mark}{n}", callback_data=cb))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if review:
        rows.append([InlineKeyboardButton("📊 Summary", callback_data=f"{CB_REVIEW}:open")])
        rows.append([InlineKeyboardButton("🏠 Menu", callback_data=f"{CB_MENU}:home")])
    else:
        rows.append([InlineKeyboardButton("« Back to question", callback_data=f"{CB_NAV}:resume")])
    return InlineKeyboardMarkup(rows)


def confirm_finish_keyboard(answered: int, total: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                f"✅ Yes, finish ({answered}/{total} answered)",
                callback_data=f"{CB_NAV}:confirm",
            )],
            [InlineKeyboardButton("« Keep going", callback_data=f"{CB_NAV}:resume")],
        ]
    )


def review_open_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Review all answers", callback_data=f"{CB_REVIEW}:grid")],
            [InlineKeyboardButton("📝 New exam", callback_data=f"{CB_MENU}:new")],
            [InlineKeyboardButton("📊 My stats", callback_data=f"{CB_MENU}:stats")],
        ]
    )


def review_question_keyboard(position: int, total: int) -> InlineKeyboardMarkup:
    nav = []
    if position > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"{CB_REVIEW}:q:{position-1}"))
    nav.append(InlineKeyboardButton("🔢 All", callback_data=f"{CB_REVIEW}:grid"))
    if position < total - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"{CB_REVIEW}:q:{position+1}"))
    return InlineKeyboardMarkup([nav, [InlineKeyboardButton("🏠 Menu", callback_data=f"{CB_MENU}:home")]])
