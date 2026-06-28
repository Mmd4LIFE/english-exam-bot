"""seed question bank from committed JSON artifact

Loads ``app/data/seed/question_bank.json`` (produced by the ingestion
pipeline, ``make ingest``) and inserts the real past-konkoor questions so that
``alembic upgrade head`` on a fresh server reproduces the full bank — no PDFs
or OpenAI calls required at deploy time.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-28
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.seed")

SEED_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "data" / "seed" / "question_bank.json"
)

# Lightweight table definitions for inserts (subset of real columns).
_passages = sa.table(
    "passages",
    sa.column("id", sa.Integer),
    sa.column("source", sa.String),
    sa.column("year", sa.Integer),
    sa.column("title", sa.String),
    sa.column("body", sa.Text),
)
_questions = sa.table(
    "questions",
    sa.column("passage_id", sa.Integer),
    sa.column("origin", sa.String),
    sa.column("source", sa.String),
    sa.column("year", sa.Integer),
    sa.column("number", sa.Integer),
    sa.column("skill_type", sa.String),
    sa.column("stem", sa.Text),
    sa.column("options", postgresql.JSONB),
    sa.column("correct_index", sa.Integer),
    sa.column("explanation", sa.Text),
)


def _load_seed() -> dict:
    if not SEED_PATH.exists():
        logger.warning("Seed file %s not found — skipping bank seed.", SEED_PATH)
        return {"passages": [], "questions": []}
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return {"passages": data.get("passages", []), "questions": data.get("questions", [])}


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT COUNT(*) FROM questions WHERE origin = 'bank'")
    ).scalar_one()
    if existing:
        logger.info("Bank already seeded (%d questions) — skipping.", existing)
        return

    seed = _load_seed()
    if not seed["questions"]:
        return

    # Insert passages first, mapping their seed key -> generated id.
    key_to_id: dict[str, int] = {}
    for p in seed["passages"]:
        new_id = bind.execute(
            _passages.insert()
            .values(
                source=p["source"],
                year=p.get("year"),
                title=p.get("title"),
                body=p["body"],
            )
            .returning(_passages.c.id)
        ).scalar_one()
        key_to_id[p["key"]] = new_id

    rows = []
    for q in seed["questions"]:
        rows.append(
            {
                "passage_id": key_to_id.get(q.get("passage_key")) if q.get("passage_key") else None,
                "origin": "bank",
                "source": q.get("source"),
                "year": q.get("year"),
                "number": q.get("number"),
                "skill_type": q.get("skill_type", "grammar"),
                "stem": q["stem"],
                "options": q["options"],
                "correct_index": int(q["correct_index"]),
                "explanation": q.get("explanation"),
            }
        )
    if rows:
        op.bulk_insert(_questions, rows)
    logger.info(
        "Seeded %d passages and %d bank questions.",
        len(seed["passages"]),
        len(rows),
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM questions WHERE origin = 'bank'"))
    bind.execute(sa.text("DELETE FROM passages WHERE source <> 'ai'"))
