"""Small shared helpers."""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_duration(seconds: int) -> str:
    """Render seconds as ``MM:SS`` (or ``H:MM:SS`` past an hour)."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def remaining_seconds(deadline: datetime) -> int:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return int((deadline - utcnow()).total_seconds())


# Letters for the four options (used in message text)
OPTION_LETTERS = ["A", "B", "C", "D"]
