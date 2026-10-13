"""
DISHA - Memory
Rolling log of recent exchanges so DISHA can reference "what we talked about earlier",
plus persistent structured facts store (facts.json) across restarts.
"""

import json
import re
from datetime import datetime
from config import MEMORY_FILE, MEMORY_MAX_ENTRIES, FACTS_FILE


def log_exchange(user_input: str, disha_response: str) -> None:
    """Append one exchange to the local memory log."""
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "user": user_input,
        "disha": disha_response,
    }
    try:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim_log()
    except OSError:
        # Memory logging should never crash the assistant
        pass


import os


def _atomic_write_text(filepath, content: str) -> None:
    """Write text atomically via temporary file and os.replace to prevent corruption."""
    temp_path = filepath.with_suffix(".tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, filepath)
    except OSError:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def _trim_log() -> None:
    """Keep only the most recent MEMORY_MAX_ENTRIES lines."""
    if not MEMORY_FILE.exists():
        return
    try:
        lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > MEMORY_MAX_ENTRIES:
            trimmed = lines[-MEMORY_MAX_ENTRIES:]
            _atomic_write_text(MEMORY_FILE, "\n".join(trimmed) + "\n")
    except OSError:
        pass


def get_recent_context(n: int = 5) -> str:
    """Return the last n exchanges formatted as plain text context for Gemini."""
    if not MEMORY_FILE.exists():
        return ""
    try:
        lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return ""
    if not lines:
        return ""

    formatted = []
    for line in lines:
        try:
            entry = json.loads(line)
            formatted.append(f"User: {entry['user']}\nDISHA: {entry['disha']}")
        except (json.JSONDecodeError, KeyError):
            continue

    if not formatted:
        return ""
    return "Recent conversation for context:\n" + "\n\n".join(formatted)


# ── Fact Store ────────────────────────────────────────────────────────────────

def save_fact(key: str, value: str) -> None:
    """
    Persist a user fact (e.g. "user_name" -> "Sudhan").
    Creates facts.json if absent. Atomically writes to avoid corruption.
    key: lowercase snake_case string
    value: string
    """
    facts = load_all_facts()
    facts[key] = value
    try:
        _atomic_write_text(FACTS_FILE, json.dumps(facts, ensure_ascii=False, indent=2))
    except OSError:
        pass


def get_fact(key: str, default: str = "") -> str:
    """Return a stored fact or default. Never raises."""
    return load_all_facts().get(key, default)


def load_all_facts() -> dict:
    """Load all facts from facts.json. Returns {} if file missing/corrupt."""
    if not FACTS_FILE.exists():
        return {}
    try:
        return json.loads(FACTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ── Fact Extraction (called from route_request before AI) ─────────────────────

COMMON_NON_NAMES = {
    "not", "good", "fine", "ok", "okay", "here", "there", "back", "done",
    "ready", "tired", "busy", "happy", "sad", "sorry", "just", "sure",
    "trying", "going", "looking", "working", "feeling", "wondering",
    "asking", "curious", "bored", "hungry", "free", "human", "user",
    "admin", "disha", "someone", "nobody", "anybody", "anything", "nothing",
    "something", "them", "him", "her", "it", "this", "that"
}

_FACT_PATTERNS = [
    # Explicit name introductions — single or first/last name
    (r"(?:my name is|call me|you can call me|i am called)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", "user_name"),
    # "remember that X" or "remember to X" or "remember: X"
    (r"remember\s*(?:that|to|:)?\s*(.+)", "memory_note"),
]


def extract_and_store_facts(text: str) -> None:
    """
    Scan text for learnable facts and persist them.
    Called before routing to Gemini so facts are captured even from AI queries.
    Never modifies the text — side-effect only.
    """
    for pattern, key in _FACT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw_val = m.group(1).strip()
            if key == "user_name":
                words = raw_val.split()
                if any(w.lower() in COMMON_NON_NAMES for w in words) or len(raw_val) < 2:
                    continue
                value = raw_val.title()
                try:
                    import config
                    config.USER_NAME = value
                except Exception:
                    pass
            else:
                value = raw_val
            save_fact(key, value)
