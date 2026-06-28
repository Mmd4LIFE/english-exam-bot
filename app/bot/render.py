"""Render exam/question/review messages as HTML for Telegram."""
from __future__ import annotations

import html

from app.db.models import ExamSession, SessionQuestion
from app.utils import OPTION_LETTERS, format_duration, remaining_seconds


def _esc(text: str | None) -> str:
    return html.escape(text or "")


def _item_at(exam: ExamSession, position: int) -> SessionQuestion | None:
    return next((i for i in exam.items if i.position == position), None)


def _passage_block(item: SessionQuestion) -> str:
    q = item.question
    if not q.passage:
        return ""
    title = f"<b>{_esc(q.passage.title)}</b>\n" if q.passage.title else ""
    return f"📖 <i>Passage</i>\n{title}<blockquote>{_esc(q.passage.body)}</blockquote>\n\n"


def render_question(exam: ExamSession) -> str:
    """Render the current question (passage kept, options listed A–D)."""
    position = exam.current_position
    item = _item_at(exam, position)
    if item is None:
        return "No question."
    q = item.question

    remaining = remaining_seconds(exam.deadline_at)
    answered = sum(1 for i in exam.items if i.selected_index is not None)
    header = (
        f"🧠 <b>{_esc(exam.source_label)}</b>  •  "
        f"⏱ <b>{format_duration(remaining)}</b>\n"
        f"Question <b>{position + 1}</b> of {exam.num_questions}  •  "
        f"answered {answered}/{exam.num_questions}  •  "
        f"<i>{_esc(q.skill_type)}</i>\n"
        f"{'─' * 18}\n\n"
    )

    body = _passage_block(item)
    body += f"<b>{position + 1}.</b> {_esc(q.stem)}\n\n"
    for idx, opt in enumerate(q.options):
        mark = "🔘" if item.selected_index == idx else "▫️"
        body += f"{mark} <b>{OPTION_LETTERS[idx]})</b> {_esc(opt)}\n"

    body += "\n<i>Tap A–D to answer. You can go back and change it any time.</i>"
    return header + body


def render_review_question(exam: ExamSession, position: int) -> str:
    item = _item_at(exam, position)
    if item is None:
        return "No question."
    q = item.question

    head = f"🔍 <b>Review — question {position + 1}/{exam.num_questions}</b>  •  <i>{_esc(q.skill_type)}</i>\n{'─' * 18}\n\n"
    body = _passage_block(item)
    body += f"<b>{position + 1}.</b> {_esc(q.stem)}\n\n"
    for idx, opt in enumerate(q.options):
        if idx == q.correct_index:
            mark = "✅"
        elif idx == item.selected_index:
            mark = "❌"
        else:
            mark = "▫️"
        body += f"{mark} <b>{OPTION_LETTERS[idx]})</b> {_esc(opt)}\n"

    if item.selected_index is None:
        verdict = "⏭ <b>Not answered</b>"
    elif item.is_correct:
        verdict = "✅ <b>Correct</b>"
    else:
        verdict = (
            f"❌ <b>Wrong</b> — your answer: "
            f"{OPTION_LETTERS[item.selected_index]}, "
            f"correct: {OPTION_LETTERS[q.correct_index]}"
        )
    body += f"\n{verdict}"
    if q.explanation:
        body += f"\n💡 <i>{_esc(q.explanation)}</i>"
    return head + body


def render_result_summary(exam: ExamSession, *, expired: bool = False) -> str:
    total = exam.num_questions
    correct = exam.correct_count
    answered = sum(1 for i in exam.items if i.selected_index is not None)
    wrong = answered - correct
    blank = total - answered
    score = exam.score or 0.0

    title = "⏰ <b>Time is up!</b>" if expired else "🏁 <b>Exam finished!</b>"
    bar_len = 16
    filled = round(bar_len * score / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    return (
        f"{title}\n\n"
        f"<b>{_esc(exam.source_label)}</b>\n"
        f"{'─' * 18}\n"
        f"Score: <b>{score:.0f}%</b>\n"
        f"<code>{bar}</code>\n\n"
        f"✅ Correct: <b>{correct}</b>\n"
        f"❌ Wrong: <b>{wrong}</b>\n"
        f"⏭ Blank: <b>{blank}</b>\n"
        f"📋 Total: <b>{total}</b>\n\n"
        f"<i>Review every question below, or jump to any number.</i>"
    )
