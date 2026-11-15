"""Fire-and-forget mastery writeback to the RootsEDU taxonomy service.

Contract (docs/rootsedu/phase5-closed-loop-spec.md 1.2/1.4):
- score is the verdict-marker mapping 1.0/0.5/0.0 — never a guess from prose;
- topic_id must be a cn-math-taxonomy canonical id, otherwise nothing is sent;
- any failure (timeout, 4xx/5xx, unreachable) is logged and swallowed: the
  judgment has already reached the learner, so the writeback must not break
  the WebSocket close path.
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

TOPIC_ID_RE = re.compile(r"^cn[a-z]_[A-Za-z0-9_]+$")

# The judge prompts pin one verdict marker to the first non-empty line.
_VERDICT_SCORES: dict[str, tuple[str, float]] = {
    "✅": ("correct", 1.0),
    "⚠️": ("partial", 0.5),
    "❌": ("incorrect", 0.0),
}


def parse_verdict(text: str) -> tuple[str, float | None]:
    """Map the first-line verdict marker to ``(verdict, score)``.

    Returns ``("unknown", None)`` when no marker is found — the caller must
    neither send a score nor record an event in that case.
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for marker, (verdict, score) in _VERDICT_SCORES.items():
            if marker in line:
                return verdict, score
        # Only the first non-empty line counts; later lines legitimately
        # repeat markers when quoting examples.
        break
    return "unknown", None


def record_learning_event(
    *,
    student_id: str,
    topic_id: str | None,
    activity_type: str,
    score: float,
    result: str,
) -> bool:
    """POST one learning event; return True only on a 2xx. Never raises."""
    base = (os.getenv("ROOTSEDU_TAXONOMY_API_URL") or "").rstrip("/")
    if not base:
        return False
    if not topic_id or not TOPIC_ID_RE.match(topic_id):
        logger.debug("Writeback skipped: topic_id %r is not a cn-math id", topic_id)
        return False
    payload = {
        "student_id": student_id,
        "topic_id": topic_id,
        "activity_type": activity_type,
        "score": round(score, 4),
        "result": (result or "")[:2000],
    }
    try:
        import httpx

        response = httpx.post(
            f"{base}/api/record",
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=3,
        )
        return 200 <= response.status_code < 300
    except Exception as exc:
        logger.info("Taxonomy writeback failed (quiz feedback already delivered): %s", exc)
        return False
