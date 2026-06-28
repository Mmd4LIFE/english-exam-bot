"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("language_code", sa.String(8)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "passages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("title", sa.String(255)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_passages_source", "passages", ["source"])
    op.create_index("ix_passages_year", "passages", ["year"])

    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("passage_id", sa.Integer(), sa.ForeignKey("passages.id", ondelete="SET NULL")),
        sa.Column("origin", sa.String(16), nullable=False, server_default="bank"),
        sa.Column("source", sa.String(64)),
        sa.Column("year", sa.Integer()),
        sa.Column("number", sa.Integer()),
        sa.Column("skill_type", sa.String(16), nullable=False, server_default="grammar"),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_questions_passage_id", "questions", ["passage_id"])
    op.create_index("ix_questions_origin", "questions", ["origin"])
    op.create_index("ix_questions_source", "questions", ["source"])
    op.create_index("ix_questions_year", "questions", ["year"])

    op.create_table(
        "exam_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False, server_default="bank"),
        sa.Column("source_label", sa.String(64)),
        sa.Column("num_questions", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column("current_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float()),
        sa.Column("tg_chat_id", sa.BigInteger()),
        sa.Column("tg_message_id", sa.BigInteger()),
    )
    op.create_index("ix_exam_sessions_user_id", "exam_sessions", ["user_id"])
    op.create_index("ix_exam_sessions_status", "exam_sessions", ["status"])

    op.create_table(
        "session_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("exam_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("selected_index", sa.Integer()),
        sa.Column("is_correct", sa.Boolean()),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "position", name="uq_session_position"),
    )
    op.create_index("ix_session_questions_session_id", "session_questions", ["session_id"])


def downgrade() -> None:
    op.drop_table("session_questions")
    op.drop_table("exam_sessions")
    op.drop_table("questions")
    op.drop_table("passages")
    op.drop_table("users")
