"""
content_writer.py — Write individual course sections using Gemini (primary) or HuggingFace (fallback).
"""

import os
import sys
import time
import re
from typing import Dict, Optional, Tuple

# ── API clients (lazy-loaded) ─────────────────────────────────────────────────
_gemini_model = None
_hf_client = None


def _get_gemini(api_key: str, model_name: str = "gemini-1.5-flash"):
    global _gemini_model
    if _gemini_model is None:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _gemini_model = genai.GenerativeModel(model_name)
    return _gemini_model


def _get_hf(token: str):
    global _hf_client
    if _hf_client is None:
        from huggingface_hub import InferenceClient
        _hf_client = InferenceClient(token=token)
    return _hf_client


# ── Prompt loader ─────────────────────────────────────────────────────────────

def _load_prompt_template() -> str:
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "section_writer.txt"
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _build_prompt(
    section: Dict,
    outline_overview: str,
    context_window: list,
    course_title: str,
) -> str:
    template = _load_prompt_template()
    context_text = (
        "\n".join(f"• {c}" for c in context_window)
        if context_window
        else "This is the first section — no prior context."
    )
    return template.format(
        course_title=course_title,
        outline_overview=outline_overview,
        context_window=context_text,
        week_number=section["week"],
        week_title=section["week_title"],
        section_title=section["title"],
        section_id=section["id"],
    )


# ── Generation via Gemini ─────────────────────────────────────────────────────

def _write_with_gemini(
    prompt: str,
    api_key: str,
    max_retries: int = 3,
) -> Tuple[Optional[str], int, str]:
    """
    Returns: (content_text, tokens_used, status)
    status: 'ok' | 'rate_limited' | 'error'
    """
    for attempt in range(max_retries):
        try:
            model = _get_gemini(api_key)
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.7,
                    "max_output_tokens": 2048,
                },
            )
            text = response.text
            tokens = getattr(response.usage_metadata, "total_token_count", 0)
            return text, tokens, "ok"

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                wait = 60 * (attempt + 1)
                print(f"  ⚠️  Rate limited. Waiting {wait}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait)
                return None, 0, "rate_limited"
            elif attempt < max_retries - 1:
                print(f"  ⚠️  Gemini error (attempt {attempt+1}): {e}. Retrying in 10s...")
                time.sleep(10)
            else:
                print(f"  ❌ Gemini failed after {max_retries} attempts: {e}")
                return None, 0, "error"

    return None, 0, "error"


# ── Generation via HuggingFace (fallback) ─────────────────────────────────────

def _write_with_hf(prompt: str, hf_token: str) -> Tuple[Optional[str], int, str]:
    """HuggingFace Inference API fallback using Mixtral or similar."""
    try:
        client = _get_hf(hf_token)
        # Use a capable instruction model
        result = client.text_generation(
            prompt,
            model="mistralai/Mixtral-8x7B-Instruct-v0.1",
            max_new_tokens=2000,
            temperature=0.7,
            do_sample=True,
        )
        return result, 0, "ok"
    except Exception as e:
        print(f"  ❌ HuggingFace fallback failed: {e}")
        return None, 0, "error"


# ── Main write function ───────────────────────────────────────────────────────

def write_section(
    section: Dict,
    outline_overview: str,
    context_window: list,
    course_title: str,
    gemini_api_key: str,
    hf_token: str,
) -> Tuple[Optional[str], int, str]:
    """
    Write a single course section.
    Returns: (markdown_content, tokens_used, status)
    status: 'ok' | 'rate_limited' | 'error'
    """
    print(f"\n  📝 Writing: [{section['id']}] {section['full_title']}")

    prompt = _build_prompt(section, outline_overview, context_window, course_title)

    # Primary: Gemini Flash
    content, tokens, status = _write_with_gemini(prompt, gemini_api_key)

    # Fallback: HuggingFace
    if (content is None or status == "error") and hf_token:
        print("  🔄 Falling back to HuggingFace...")
        content, tokens, status = _write_with_hf(prompt, hf_token)

    if content:
        word_count = len(content.split())
        print(f"  ✅ Done: {word_count} words (tokens: {tokens})")

    return content, tokens, status


# ── Summary extraction ────────────────────────────────────────────────────────

def extract_summary(content: str, section: Dict) -> str:
    """Extract or generate a short summary from the written content for context continuity."""
    # Try to find the Summary section
    match = re.search(r"###\s+📝\s+Summary\n(.+?)(?=###|\Z)", content, re.DOTALL)
    if match:
        raw = match.group(1).strip()
        # Truncate to 2 sentences max
        sentences = re.split(r'(?<=[.!?])\s+', raw)
        return " ".join(sentences[:2])

    # Fallback: first 200 chars
    first_para = content.strip().split("\n\n")[0] if content else ""
    short = " ".join(first_para.split()[:40])
    return f"Week {section['week']} — {section['title']}: {short}"


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    api_key = os.getenv("GEMINI_API_KEY", "")
    hf_token = os.getenv("HF_TOKEN", "")

    test_section = {
        "id": "w1_t1",
        "week": 1,
        "week_title": "Introduction to Python",
        "topic_index": 1,
        "title": "What is Python?",
        "full_title": "Week 1: Introduction to Python — What is Python?",
        "status": "pending",
        "word_count": 0,
        "summary": "",
        "filename": "w1_t1_what_is_python.md",
    }

    outline_overview = """
Week 1: Introduction to Python
  1. What is Python?
  2. Setting Up the Environment
  3. Your First Program

Week 2: Core Concepts
  1. Variables and Data Types
  2. Control Flow
"""

    content, tokens, status = write_section(
        test_section,
        outline_overview,
        [],
        "Python for Beginners",
        api_key,
        hf_token,
    )

    if content:
        print("\n" + "=" * 60)
        print(content[:800] + "...")
        print(f"\nStatus: {status} | Tokens: {tokens}")
    else:
        print(f"Failed with status: {status}")
