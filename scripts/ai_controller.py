"""
ai_controller.py — The AI brain of the generation loop.

This is the main script executed by GitHub Actions. It:
1. Reads/initializes state from state.json
2. Loops: picks next section, writes it, commits, decides what to do next
3. Triggers another workflow run if it needs to pause
4. Generates the PDF when all sections are done
"""

import os
import sys
import time
import json
import re
import subprocess
import traceback
from datetime import datetime, timezone

# ── Add scripts dir to path ───────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from state_manager import (
    load_state,
    save_state,
    initialize_state,
    start_session,
    end_session,
    get_next_pending_section,
    mark_section_in_progress,
    mark_section_done,
    mark_section_error,
    reset_errored_sections,
    increment_api_stats,
    get_progress_summary,
)
from outline_parser import parse_outline, build_outline_overview
from content_writer import write_section, extract_summary
from pdf_generator import generate_pdf

# ── Environment ───────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
HF_TOKEN       = os.environ.get("HF_TOKEN", "")
GH_PAT         = os.environ["GH_PAT"]
REPO_OWNER     = os.environ["REPO_OWNER"]
REPO_NAME      = os.environ["REPO_NAME"]
SESSION_TYPE   = os.environ.get("SESSION_TYPE", "resume")  # start_fresh | resume

# Paths (inside the checked-out repo)
REPO_ROOT   = os.path.join(os.path.dirname(__file__), "..")
STATE_PATH  = os.path.join(REPO_ROOT, "state", "state.json")
CONTENT_DIR = os.path.join(REPO_ROOT, "content")
INPUT_DIR   = os.path.join(REPO_ROOT, "input")
OUTPUT_DIR  = os.path.join(REPO_ROOT, "output")

# Timing
SESSION_START  = time.time()
MAX_RUN_SECS   = 50 * 60   # 50 minutes — leave 5 min buffer for GitHub Actions 55-min limit
INTER_CALL_GAP = 8          # seconds between API calls (avoid > 15 RPM burst)

consecutive_errors = 0
last_api_status    = "ok"
last_error         = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def elapsed_min() -> float:
    return (time.time() - SESSION_START) / 60


def remaining_min() -> float:
    return (MAX_RUN_SECS - (time.time() - SESSION_START)) / 60


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def git_commit_all(message: str):
    """Stage all changes and commit (git is configured in workflow)."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=REPO_ROOT, check=True)
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:  # There are staged changes
            subprocess.run(
                ["git", "commit", "-m", f"{message} [skip ci]"],
                cwd=REPO_ROOT, check=True,
            )
            subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
            log(f"✔ Committed & pushed: {message}")
        else:
            log("  (no changes to commit)")
    except subprocess.CalledProcessError as e:
        log(f"⚠️  Git operation failed: {e}")


def trigger_next_run():
    """Trigger another workflow_dispatch run to continue later."""
    import requests
    url = (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        f"/actions/workflows/generate.yml/dispatches"
    )
    headers = {
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {"ref": "main", "inputs": {"session_type": "resume"}}
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code == 204:
        log("🔁 Next workflow run triggered successfully.")
    else:
        log(f"⚠️  Failed to trigger next run: {r.status_code} {r.text}")


def ask_controller(state: dict) -> str:
    """
    Use Gemini Flash to make a decision about what to do next.
    Fallback to simple heuristics if AI call fails.
    """
    global last_api_status, last_error

    prog = get_progress_summary(state)

    # ── Simple heuristic shortcuts (no API call needed) ──
    if prog["pending"] == 0:
        return "GENERATE_PDF"
    if remaining_min() < 8:
        return "RESCHEDULE"
    if consecutive_errors >= 3:
        return "PAUSE_2MIN"

    # ── AI decision (light Gemini Flash call) ────────────────
    try:
        prompt_path = os.path.join(REPO_ROOT, "prompts", "controller.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()

        prompt = template.format(
            done_count=prog["done"],
            total_count=prog["total"],
            pending_count=prog["pending"],
            error_count=prog.get("error", 0),
            time_elapsed_min=round(elapsed_min(), 1),
            time_remaining_min=round(remaining_min(), 1),
            api_calls=state["api_stats"]["total_api_calls"],
            last_api_status=last_api_status,
            last_error=last_error or "None",
        )

        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()

        match = re.search(r"DECISION:\s*(CONTINUE|PAUSE_30S|PAUSE_2MIN|RESCHEDULE|GENERATE_PDF)", text)
        if match:
            decision = match.group(1)
            reason_match = re.search(r"REASON:\s*(.+)", text)
            reason = reason_match.group(1).strip() if reason_match else ""
            log(f"🤖 AI Controller → {decision} | {reason}")
            return decision

    except Exception as e:
        log(f"⚠️  Controller AI call failed ({e}), using heuristic.")

    # Heuristic fallback
    return "CONTINUE"


# ── Initialization ────────────────────────────────────────────────────────────

def initialize_fresh() -> dict:
    """Set up state for a brand-new course from input/ files."""
    log("🌱 Starting fresh course generation...")

    outline_path = os.path.join(INPUT_DIR, "outline.txt")
    config_path  = os.path.join(INPUT_DIR, "config.json")

    with open(outline_path, "r", encoding="utf-8") as f:
        outline_raw = f.read()

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    course_title = config.get("course_title", "Untitled Course")
    sections = parse_outline(outline_raw)

    if not sections:
        log("❌ No sections parsed from outline. Check outline format.")
        sys.exit(1)

    log(f"📋 Parsed {len(sections)} sections for course: '{course_title}'")

    state = initialize_state(course_title, outline_raw, sections)
    save_state(state)
    git_commit_all("🌱 Initialize new course generation")
    return state


# ── Main generation loop ──────────────────────────────────────────────────────

def run():
    global consecutive_errors, last_api_status, last_error

    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Load or initialize state ──────────────────────────────────
    if SESSION_TYPE == "start_fresh":
        state = initialize_fresh()
    else:
        state = load_state()
        if not state.get("sections"):
            log("⚠️  No sections in state. Attempting fresh init...")
            state = initialize_fresh()

    state = start_session(state)
    save_state(state)

    course_title   = state["course_title"]
    outline_overview = build_outline_overview(state["sections"])

    log(f"\n{'='*60}")
    log(f"📚 Course: {course_title}")
    prog = get_progress_summary(state)
    log(f"📊 Progress: {prog['done']}/{prog['total']} sections done ({prog['percent']}%)")
    log(f"⏱  Session budget: ~{round(remaining_min())} minutes")
    log(f"{'='*60}\n")

    # Reset any sections stuck in "in_progress" from a previous crash
    for s in state["sections"]:
        if s["status"] == "in_progress":
            s["status"] = "pending"

    # ── Main loop ─────────────────────────────────────────────────
    while True:
        decision = ask_controller(state)

        # ── Handle decisions ──────────────────────────────────────
        if decision == "GENERATE_PDF":
            log("\n🎉 All sections complete! Generating PDF...")
            try:
                pdf_path = generate_pdf(state, CONTENT_DIR, OUTPUT_DIR)
                state["pdf_ready"] = True
                state["pdf_path"]  = "output/course_final.pdf"
                state = end_session(state, "pdf_ready")
                save_state(state)
                git_commit_all("📄 Course PDF generated — generation complete!")
                log("✅ PDF committed. Job done!")
            except Exception as e:
                log(f"❌ PDF generation failed: {e}")
                traceback.print_exc()
                state = end_session(state, "pdf_error")
                save_state(state)
                git_commit_all("⚠️ PDF generation failed")
            break

        elif decision == "RESCHEDULE":
            log("🔁 Approaching time limit — saving state and scheduling next run...")
            state = end_session(state, "time_limit")
            save_state(state)
            git_commit_all("⏸ Session paused — will resume in next run")
            trigger_next_run()
            break

        elif decision == "PAUSE_30S":
            log("⏳ Short pause (30s)...")
            time.sleep(30)
            continue

        elif decision == "PAUSE_2MIN":
            log("⏳ Rate limit pause (2 min)...")
            time.sleep(120)
            consecutive_errors = 0
            continue

        elif decision == "CONTINUE":
            section = get_next_pending_section(state)
            if section is None:
                # Double-check: maybe all done
                state = end_session(state, "all_done")
                save_state(state)
                git_commit_all("✅ All sections written")
                break

            # Mark in-progress
            state = mark_section_in_progress(state, section["id"])

            # Write the section
            content, tokens, status = write_section(
                section,
                outline_overview,
                state.get("context_window", []),
                course_title,
                GEMINI_API_KEY,
                HF_TOKEN,
            )

            last_api_status = status

            if content:
                # Save markdown file
                md_path = os.path.join(CONTENT_DIR, section["filename"])
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(content)

                # Extract summary for context continuity
                summary = extract_summary(content, section)
                word_count = len(content.split())

                # Update state
                state = mark_section_done(state, section["id"], word_count, summary)
                state = increment_api_stats(state, tokens)
                consecutive_errors = 0
                last_error = ""

                # Commit every section
                save_state(state)
                prog = get_progress_summary(state)
                git_commit_all(
                    f"✍️ [{prog['done']}/{prog['total']}] {section['full_title']}"
                )

                # Brief inter-call gap to stay under RPM limits
                if remaining_min() > 10:
                    time.sleep(INTER_CALL_GAP)

            else:
                # Write failed
                consecutive_errors += 1
                last_error = f"Write failed for {section['id']} (status: {status})"
                log(f"  ⚠️  {last_error}")
                state = mark_section_error(state, section["id"], last_error)

                if status == "rate_limited":
                    last_api_status = "rate_limited"
                    log("  💤 Rate limited — pausing 90s...")
                    time.sleep(90)
                    # Reset the section to pending so it can be retried
                    for s in state["sections"]:
                        if s["id"] == section["id"]:
                            s["status"] = "pending"
                            break

                elif consecutive_errors >= 5:
                    log("❌ Too many consecutive errors — rescheduling.")
                    state = end_session(state, "too_many_errors")
                    save_state(state)
                    git_commit_all("⚠️ Session ended due to errors")
                    trigger_next_run()
                    break

    log("\n✅ Session complete.")


if __name__ == "__main__":
    run()
