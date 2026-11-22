"""Bound replayed context before A2A serialization, including JSON escaping overhead.

Only the six most recent valid turns travel to another service. Each is limited to
1,000 UTF-8 bytes, keeping questions and history within the registry's 64 KiB body cap.
"""

MAX_HISTORY_TURNS = 6
MAX_HISTORY_BYTES = 1000
MAX_QUESTION_BYTES = 4000


def bounded_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep recent user/assistant context and truncate without splitting UTF-8."""
    valid = [
        turn
        for turn in history
        if isinstance(turn, dict)
        and turn.get("role") in ("user", "assistant")
        and isinstance(turn.get("content"), str)
    ]
    return [
        {
            "role": turn["role"],
            "content": turn["content"]
            .encode("utf-8", errors="replace")[:MAX_HISTORY_BYTES]
            .decode("utf-8", errors="ignore"),
        }
        for turn in valid[-MAX_HISTORY_TURNS:]
    ]
