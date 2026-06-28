"""Matplotlib-based score-tracker visualisations.

All functions return PNG bytes so they can be sent directly as Telegram photos.
Matplotlib is used in a headless (Agg) backend — safe inside Docker.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_BG = "#0e1117"
_FG = "#e6e6e6"
_ACCENT = "#3aa0ff"
_GOOD = "#2ecc71"
_BAD = "#e74c3c"


def _new_fig(w: float = 7.2, h: float = 4.0):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    ax.tick_params(colors=_FG)
    ax.title.set_color(_FG)
    ax.xaxis.label.set_color(_FG)
    ax.yaxis.label.set_color(_FG)
    return fig, ax


def _render(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def progress_chart(scores: list[float], labels: list[str]) -> bytes:
    """Line chart of exam scores over time."""
    fig, ax = _new_fig()
    x = list(range(1, len(scores) + 1))
    ax.plot(x, scores, marker="o", color=_ACCENT, linewidth=2, markersize=6)
    ax.fill_between(x, scores, color=_ACCENT, alpha=0.12)
    avg = sum(scores) / len(scores)
    ax.axhline(avg, color=_GOOD, linestyle="--", linewidth=1, alpha=0.8,
               label=f"avg {avg:.0f}%")
    ax.set_ylim(0, 100)
    ax.set_title("Your score progress")
    ax.set_xlabel("Exam #")
    ax.set_ylabel("Score (%)")
    ax.set_xticks(x)
    if len(labels) == len(x):
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
    ax.legend(facecolor=_BG, edgecolor="#30363d", labelcolor=_FG)
    ax.grid(True, color="#21262d", linewidth=0.6)
    return _render(fig)


def skill_chart(breakdown: dict[str, tuple[int, int]]) -> bytes:
    """Horizontal bar chart of accuracy per skill type."""
    fig, ax = _new_fig(7.2, 3.6)
    skills, pcts, counts = [], [], []
    for skill, (correct, total) in sorted(breakdown.items()):
        if total == 0:
            continue
        skills.append(skill.capitalize())
        pcts.append(100.0 * correct / total)
        counts.append((correct, total))
    if not skills:
        skills, pcts, counts = ["No data"], [0], [(0, 0)]
    colors = [_GOOD if p >= 50 else _BAD for p in pcts]
    bars = ax.barh(skills, pcts, color=colors, alpha=0.9)
    ax.set_xlim(0, 100)
    ax.set_title("Accuracy by skill")
    ax.set_xlabel("Correct (%)")
    for bar, (c, t) in zip(bars, counts):
        ax.text(min(bar.get_width() + 2, 92), bar.get_y() + bar.get_height() / 2,
                f"{c}/{t}", va="center", color=_FG, fontsize=8)
    ax.grid(True, axis="x", color="#21262d", linewidth=0.6)
    return _render(fig)


def result_donut(correct: int, total: int) -> bytes:
    """Donut chart summarising a single exam result."""
    fig, ax = _new_fig(4.4, 4.4)
    wrong = max(0, total - correct)
    ax.pie(
        [correct, wrong] if total else [0, 1],
        colors=[_GOOD, _BAD],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": _BG, "linewidth": 2},
    )
    pct = (100.0 * correct / total) if total else 0.0
    ax.text(0, 0.08, f"{pct:.0f}%", ha="center", va="center",
            color=_FG, fontsize=26, fontweight="bold")
    ax.text(0, -0.22, f"{correct}/{total} correct", ha="center", va="center",
            color=_FG, fontsize=11)
    ax.set_title("Exam result")
    return _render(fig)
