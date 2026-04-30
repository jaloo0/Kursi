"""
outline_parser.py — Parse plain-text 15-week course outlines into structured sections.

Supports formats like:
  Week 1: Introduction to Python
  - What is Python?
  - Setting Up the Environment
  - Your First Program

  Week 2: Core Concepts
  1. Variables and Types
  2. Control Flow
  3. Functions
"""

import re
from typing import List, Dict


def parse_outline(outline_text: str) -> List[Dict]:
    """
    Parse a plain-text course outline into a list of section dicts.
    Each 'section' corresponds to one topic under a week.
    """
    sections: List[Dict] = []
    lines = outline_text.strip().splitlines()

    current_week_num = 0
    current_week_title = ""
    topic_index = 0
    all_weeks = []  # for building full outline context

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # ── Week header ──────────────────────────────────────────────────────
        # Matches: "Week 1: Title", "Week 1 - Title", "WEEK 1 — Title",
        #          "1. Week Title", "Week1: Title"
        week_match = re.match(
            r'^(?:Week\s*(\d+)\s*[:\-–—]\s*(.+)|(\d+)\.\s+(.+))$',
            line,
            re.IGNORECASE,
        )
        # More relaxed week match
        if not week_match:
            week_match = re.match(r'^Week\s+(\d+)[:\-–—\s]+(.+)$', line, re.IGNORECASE)

        if week_match:
            groups = week_match.groups()
            # Determine which groups matched
            if groups[0] is not None:
                wnum, wtitle = groups[0], groups[1]
            elif groups[2] is not None:
                wnum, wtitle = groups[2], groups[3]
            else:
                continue

            current_week_num = int(wnum)
            current_week_title = wtitle.strip()
            topic_index = 0
            all_weeks.append(f"Week {current_week_num}: {current_week_title}")
            continue

        # ── Topic line ────────────────────────────────────────────────────────
        # Matches: "- Topic", "• Topic", "* Topic",
        #          "1. Topic", "1.1 Topic", "  - Topic"
        topic_match = re.match(
            r'^[\-\•\*\d\.]+\s*(?:Topic\s*[\d\.]*\s*[:\-]?\s*)?(.+)$',
            line,
        )

        if topic_match and current_week_num > 0:
            topic_index += 1
            raw_title = topic_match.group(1).strip()
            # Strip any leading numbering that slipped through
            topic_title = re.sub(r'^[\d\.]+\s*', '', raw_title).strip()
            if not topic_title:
                continue

            section_id = f"w{current_week_num}_t{topic_index}"
            safe_name = re.sub(r'[^\w\s]', '', topic_title)[:40].strip()
            safe_name = re.sub(r'\s+', '_', safe_name).lower()

            sections.append({
                "id": section_id,
                "week": current_week_num,
                "week_title": current_week_title,
                "topic_index": topic_index,
                "title": topic_title,
                "full_title": (
                    f"Week {current_week_num}: {current_week_title} — {topic_title}"
                ),
                "status": "pending",
                "word_count": 0,
                "summary": "",
                "filename": f"{section_id}_{safe_name}.md",
            })

    return sections


def build_outline_overview(sections: List[Dict]) -> str:
    """Return a compact human-readable overview of the full course structure."""
    lines = []
    current_week = 0
    for s in sections:
        if s["week"] != current_week:
            current_week = s["week"]
            lines.append(f"\nWeek {s['week']}: {s['week_title']}")
        lines.append(f"  {s['topic_index']}. {s['title']}")
    return "\n".join(lines)


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample = """
Week 1: Introduction to Python
- What is Python?
- Setting Up the Environment
- Your First Program

Week 2: Core Concepts
1. Variables and Data Types
2. Control Flow: if/else & loops
3. Functions and Scope

Week 3: Object-Oriented Programming
- Classes and Objects
- Inheritance and Polymorphism
- Special Methods (dunder methods)
"""
    parsed = parse_outline(sample)
    print(f"Parsed {len(parsed)} sections:")
    for s in parsed:
        print(f"  [{s['id']}] {s['full_title']}")
    print("\nOverview:")
    print(build_outline_overview(parsed))
