"""
state_manager.py — Read, write, and update state.json for the generation session.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "state.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Load / Save ───────────────────────────────────────────────────────────────

def load_state() -> Dict:
    """Load state from disk. Returns empty state dict if file missing or corrupt."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty_state()


def save_state(state: Dict) -> None:
    """Save state to disk."""
    state["last_updated"] = _now_iso()
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _empty_state() -> Dict:
    return {
        "course_title": "",
        "status": "idle",
        "outline_raw": "",
        "sections": [],
        "current_index": 0,
        "total_sections": 0,
        "context_window": [],
        "api_stats": {
            "total_api_calls": 0,
            "total_tokens": 0,
            "sessions_count": 0,
        },
        "sessions": [],
        "last_updated": _now_iso(),
        "pdf_ready": False,
        "pdf_path": "",
    }


# ── Initialization ────────────────────────────────────────────────────────────

def initialize_state(course_title: str, outline_raw: str, sections: List[Dict]) -> Dict:
    """Create a fresh state for a new course generation."""
    state = _empty_state()
    state["course_title"] = course_title
    state["status"] = "running"
    state["outline_raw"] = outline_raw
    state["sections"] = sections
    state["current_index"] = 0
    state["total_sections"] = len(sections)
    state["sessions"] = []
    state["context_window"] = []
    return state


# ── Session management ────────────────────────────────────────────────────────

def start_session(state: Dict) -> Dict:
    """Record the start of a new generation session."""
    session = {
        "session_id": f"session_{len(state['sessions']) + 1}",
        "started_at": _now_iso(),
        "ended_at": None,
        "sections_written": 0,
        "reason_stopped": None,
    }
    state["sessions"].append(session)
    state["api_stats"]["sessions_count"] += 1
    state["status"] = "running"
    return state


def end_session(state: Dict, reason: str) -> Dict:
    """Record the end of the current session."""
    if state["sessions"]:
        state["sessions"][-1]["ended_at"] = _now_iso()
        state["sessions"][-1]["reason_stopped"] = reason
    if reason == "all_done":
        state["status"] = "done"
    elif reason == "pdf_ready":
        state["status"] = "done"
        state["pdf_ready"] = True
    else:
        state["status"] = "paused"
    return state


# ── Section tracking ──────────────────────────────────────────────────────────

def get_next_pending_section(state: Dict) -> Optional[Dict]:
    """Return the next section that hasn't been written yet."""
    for section in state["sections"]:
        if section["status"] == "pending":
            return section
    return None


def mark_section_in_progress(state: Dict, section_id: str) -> Dict:
    """Mark a section as currently being written."""
    for section in state["sections"]:
        if section["id"] == section_id:
            section["status"] = "in_progress"
            break
    return state


def mark_section_done(
    state: Dict,
    section_id: str,
    word_count: int,
    summary: str,
) -> Dict:
    """Mark a section as completed and update context window."""
    for section in state["sections"]:
        if section["id"] == section_id:
            section["status"] = "done"
            section["word_count"] = word_count
            section["summary"] = summary
            section["completed_at"] = _now_iso()
            break

    # Count completed
    done_count = sum(1 for s in state["sections"] if s["status"] == "done")
    state["current_index"] = done_count

    # Rolling context window — keep last 6 summaries
    state["context_window"].append(summary)
    if len(state["context_window"]) > 6:
        state["context_window"] = state["context_window"][-6:]

    # Update session counter
    if state["sessions"]:
        state["sessions"][-1]["sections_written"] += 1

    return state


def mark_section_error(state: Dict, section_id: str, error_msg: str) -> Dict:
    """Mark a section as errored (will be retried)."""
    for section in state["sections"]:
        if section["id"] == section_id:
            section["status"] = "error"
            section["error"] = error_msg
            break
    return state


def reset_errored_sections(state: Dict) -> Dict:
    """Reset all errored sections back to pending for retry."""
    for section in state["sections"]:
        if section["status"] == "error":
            section["status"] = "pending"
            section.pop("error", None)
    return state


# ── Stats ─────────────────────────────────────────────────────────────────────

def increment_api_stats(state: Dict, tokens_used: int = 0) -> Dict:
    state["api_stats"]["total_api_calls"] += 1
    state["api_stats"]["total_tokens"] += tokens_used
    return state


def get_progress_summary(state: Dict) -> Dict:
    total = state["total_sections"]
    done = sum(1 for s in state["sections"] if s["status"] == "done")
    in_prog = sum(1 for s in state["sections"] if s["status"] == "in_progress")
    pending = sum(1 for s in state["sections"] if s["status"] == "pending")
    error = sum(1 for s in state["sections"] if s["status"] == "error")
    return {
        "total": total,
        "done": done,
        "in_progress": in_prog,
        "pending": pending,
        "error": error,
        "percent": round(done / total * 100, 1) if total > 0 else 0,
        "total_words": sum(
            s.get("word_count", 0) for s in state["sections"] if s["status"] == "done"
        ),
    }
