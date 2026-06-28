"""RAG store (Qdrant + OpenAI embeddings) that grounds AI exam generation in
the real past-konkoor question bank.

Design goals
------------
- **Graceful**: every public method swallows errors and degrades to "no RAG",
  so the bot keeps working if Qdrant or the embeddings API is unavailable.
- **Idempotent indexing**: questions are upserted by their DB id; re-indexing
  only embeds when the collection size differs from the bank size.
- **Sync client, async-friendly**: blocking calls are wrapped with
  ``asyncio.to_thread`` in async callers.
"""
from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def question_to_text(stem: str, options: list[str], skill: str) -> str:
    opts = " | ".join(options)
    return f"[{skill}] {stem} Options: {opts}"


class RagStore:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._enabled = self._settings.rag_enabled
        self._client = None
        self._openai = None
        self._dim: int | None = None

    # --- lazy clients -------------------------------------------------------
    def _qdrant(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                host=self._settings.qdrant_host,
                port=self._settings.qdrant_port,
                timeout=10.0,
            )
        return self._client

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._openai is None:
            from openai import OpenAI

            self._openai = OpenAI(api_key=self._settings.openai_api_key)
        resp = self._openai.embeddings.create(
            model=self._settings.openai_embed_model, input=texts
        )
        return [d.embedding for d in resp.data]

    # --- indexing -----------------------------------------------------------
    def _ensure_collection(self, dim: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        client = self._qdrant()
        names = {c.name for c in client.get_collections().collections}
        if self._settings.qdrant_collection not in names:
            client.create_collection(
                collection_name=self._settings.qdrant_collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def index_questions(self, rows: list[dict]) -> int:
        """Embed + upsert bank questions. ``rows`` = [{id, stem, options, skill_type}].

        Returns the number indexed (0 if disabled / unavailable / already current).
        """
        if not self._enabled or not rows:
            return 0
        try:
            from qdrant_client.models import PointStruct

            client = self._qdrant()
            coll = self._settings.qdrant_collection
            existing = {c.name for c in client.get_collections().collections}
            if coll in existing:
                count = client.count(coll, exact=True).count
                if count >= len(rows):
                    logger.info("RAG: collection already has %d points; skipping.", count)
                    return 0

            texts = [
                question_to_text(r["stem"], r["options"], r["skill_type"]) for r in rows
            ]
            vectors = []
            batch = 128
            for i in range(0, len(texts), batch):
                vectors.extend(self._embed(texts[i : i + batch]))
            self._ensure_collection(len(vectors[0]))
            points = [
                PointStruct(
                    id=r["id"],
                    vector=v,
                    payload={
                        "stem": r["stem"],
                        "options": r["options"],
                        "skill_type": r["skill_type"],
                        "year": r.get("year"),
                    },
                )
                for r, v in zip(rows, vectors)
            ]
            client.upsert(collection_name=coll, points=points)
            logger.info("RAG: indexed %d questions into Qdrant.", len(points))
            return len(points)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG indexing skipped (%s)", exc)
            return 0

    # --- retrieval ----------------------------------------------------------
    def search_examples(self, query: str, k: int = 8) -> list[str]:
        """Return up to ``k`` real questions (as text) most similar to ``query``."""
        if not self._enabled:
            return []
        try:
            vector = self._embed([query])[0]
            hits = self._qdrant().query_points(
                collection_name=self._settings.qdrant_collection,
                query=vector,
                limit=k,
                with_payload=True,
            ).points
            out = []
            for h in hits:
                p = h.payload or {}
                out.append(question_to_text(p.get("stem", ""), p.get("options", []), p.get("skill_type", "")))
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG search skipped (%s)", exc)
            return []
