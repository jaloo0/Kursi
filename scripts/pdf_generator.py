"""
pdf_generator.py — Convert all generated markdown sections into a single formatted PDF.
"""

import os
import re
import json
import glob
from typing import Dict, List
from datetime import datetime

try:
    import markdown2
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


# ── CSS styling ───────────────────────────────────────────────────────────────

PDF_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Fira+Code:wght@400;500&display=swap');

@page {
    size: A4;
    margin: 2.5cm 2.8cm 2.5cm 2.8cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-size: 9pt;
        color: #666;
        font-family: 'Inter', sans-serif;
    }
    @top-right {
        content: string(course-title);
        font-size: 8pt;
        color: #888;
        font-family: 'Inter', sans-serif;
    }
}

@page :first {
    @bottom-center { content: none; }
    @top-right { content: none; }
}

/* ── Base ─────────────────────────────────────── */
body {
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.75;
    color: #1a1a2e;
    text-rendering: optimizeLegibility;
}

/* ── Cover page ────────────────────────────────── */
.cover {
    page-break-after: always;
    min-height: 240mm;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: flex-start;
    padding: 0 0 0 0;
}

.cover-badge {
    background: #e8f4fd;
    color: #1565c0;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 4px 12px;
    border-radius: 20px;
    margin-bottom: 24px;
    display: inline-block;
}

.cover h1 {
    font-size: 34pt;
    font-weight: 700;
    line-height: 1.15;
    color: #0d1b4b;
    margin: 0 0 12px 0;
    string-set: course-title content();
}

.cover-subtitle {
    font-size: 14pt;
    color: #555;
    font-weight: 300;
    margin-bottom: 40px;
}

.cover-meta {
    font-size: 9pt;
    color: #888;
    border-top: 1px solid #ddd;
    padding-top: 16px;
    width: 100%;
}

.cover-divider {
    width: 60px;
    height: 5px;
    background: linear-gradient(90deg, #1565c0, #42a5f5);
    border-radius: 3px;
    margin: 20px 0 28px 0;
}

/* ── TOC ────────────────────────────────────────── */
.toc {
    page-break-after: always;
}

.toc h2 {
    font-size: 20pt;
    font-weight: 700;
    color: #0d1b4b;
    margin-bottom: 24px;
    border-bottom: 2px solid #1565c0;
    padding-bottom: 8px;
}

.toc-week {
    margin-top: 14px;
    font-weight: 600;
    font-size: 11pt;
    color: #1a1a2e;
}

.toc-topic {
    font-size: 10pt;
    color: #555;
    padding-left: 16px;
    line-height: 2;
}

/* ── Week/Chapter break ─────────────────────────── */
.week-header {
    page-break-before: always;
    background: linear-gradient(135deg, #0d1b4b 0%, #1565c0 100%);
    color: white;
    padding: 48px 40px;
    margin: -2.5cm -2.8cm 0 -2.8cm;
    margin-bottom: 40px;
}

.week-header .week-label {
    font-size: 10pt;
    letter-spacing: 3px;
    text-transform: uppercase;
    opacity: 0.7;
    margin-bottom: 8px;
}

.week-header h2 {
    font-size: 24pt;
    font-weight: 700;
    color: white;
    margin: 0;
    border: none;
}

/* ── Section content ───────────────────────────── */
.section-content {
    padding-top: 8px;
}

h2 { font-size: 18pt; font-weight: 700; color: #0d1b4b; margin: 32px 0 12px; }
h3 { font-size: 13pt; font-weight: 600; color: #1565c0; margin: 24px 0 8px; }
h4 { font-size: 11pt; font-weight: 600; color: #333; margin: 16px 0 6px; }

p { margin: 0 0 12px; }

/* ── Tables ─────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0 20px;
    font-size: 10pt;
}
th {
    background: #1565c0;
    color: white;
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
}
td { padding: 7px 12px; border-bottom: 1px solid #e0e0e0; }
tr:nth-child(even) td { background: #f5f8ff; }

/* ── Code ───────────────────────────────────────── */
pre {
    background: #0d1117;
    color: #c9d1d9;
    padding: 16px 20px;
    border-radius: 6px;
    font-size: 9.5pt;
    font-family: 'Fira Code', 'Courier New', monospace;
    overflow-x: auto;
    margin: 12px 0 16px;
    line-height: 1.5;
}
code {
    font-family: 'Fira Code', 'Courier New', monospace;
    background: #eef2ff;
    color: #1565c0;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 9.5pt;
}
pre code { background: none; color: inherit; padding: 0; }

/* ── Blockquotes / Callouts ─────────────────────── */
blockquote {
    border-left: 4px solid #42a5f5;
    background: #e3f2fd;
    padding: 10px 16px;
    margin: 12px 0;
    border-radius: 0 6px 6px 0;
    color: #0d47a1;
    font-size: 10.5pt;
}

/* ── Lists ──────────────────────────────────────── */
ul, ol { margin: 8px 0 12px 20px; }
li { margin-bottom: 4px; }

/* ── Section separator ──────────────────────────── */
hr {
    border: none;
    border-top: 1px solid #e0e0e0;
    margin: 32px 0;
}

/* ── Section footer ─────────────────────────────── */
.section-footer {
    font-size: 8.5pt;
    color: #aaa;
    margin-top: 24px;
    font-style: italic;
}
"""


# ── HTML builders ─────────────────────────────────────────────────────────────

def _build_cover(state: Dict) -> str:
    title       = state.get("course_title", "Untitled Course")
    total       = state.get("total_sections", 0)
    total_words = sum(
        s.get("word_count", 0)
        for s in state.get("sections", [])
        if s.get("status") == "done"
    )
    generated   = datetime.utcnow().strftime("%B %d, %Y")
    return f"""
<div class="cover">
    <div class="cover-badge">📚 Course Textbook</div>
    <h1>{title}</h1>
    <div class="cover-divider"></div>
    <div class="cover-subtitle">A Comprehensive {len(set(s['week'] for s in state.get('sections', [])))} ‑Week Course</div>
    <div class="cover-meta">
        {total} topics · ~{total_words:,} words · Generated {generated}<br>
        Created with Kursi AI Course Generator
    </div>
</div>
"""


def _build_toc(state: Dict) -> str:
    sections    = state.get("sections", [])
    lines       = ['<div class="toc"><h2>📋 Table of Contents</h2>']
    current_week = 0
    for s in sections:
        if s["week"] != current_week:
            current_week = s["week"]
            lines.append(
                f'<div class="toc-week">Week {s["week"]}: {s["week_title"]}</div>'
            )
        lines.append(
            f'<div class="toc-topic">{'&nbsp;' * 4}{s["topic_index"]}. {s["title"]}</div>'
        )
    lines.append("</div>")
    return "\n".join(lines)


def _convert_md(md_text: str) -> str:
    return markdown2.markdown(
        md_text,
        extras=[
            "fenced-code-blocks",
            "tables",
            "strike",
            "footnotes",
            "header-ids",
            "break-on-newline",
        ],
    )


# ── Main PDF generator ────────────────────────────────────────────────────────

def generate_pdf(state: Dict, content_dir: str, output_dir: str) -> str:
    """
    Assemble all written sections into a single PDF.
    Returns: absolute path to the generated PDF.
    """
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError(
            "weasyprint or markdown2 not installed. Run: pip install weasyprint markdown2"
        )

    sections = [s for s in state.get("sections", []) if s.get("status") == "done"]
    if not sections:
        raise ValueError("No completed sections to include in PDF.")

    print(f"  📄 Assembling PDF from {len(sections)} sections...")

    html_parts = [
        "<!DOCTYPE html><html><head>",
        '<meta charset="utf-8">',
        f'<title>{state.get("course_title", "Course")}</title>',
        "</head><body>",
        _build_cover(state),
        _build_toc(state),
    ]

    current_week = 0
    for section in sections:
        # Week header page-break
        if section["week"] != current_week:
            current_week = section["week"]
            html_parts.append(f"""
<div class="week-header">
    <div class="week-label">Week {section['week']}</div>
    <h2>{section['week_title']}</h2>
</div>
""")

        # Load markdown file
        md_path = os.path.join(content_dir, section["filename"])
        if not os.path.exists(md_path):
            print(f"  ⚠️  Missing file: {section['filename']} — skipping.")
            continue

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        html_parts.append('<div class="section-content">')
        html_parts.append(_convert_md(md_content))
        html_parts.append("</div>")

    html_parts.append("</body></html>")
    full_html = "\n".join(html_parts)

    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, "course_final.pdf")

    HTML(string=full_html).write_pdf(
        pdf_path,
        stylesheets=[CSS(string=PDF_CSS)],
    )

    size_mb = os.path.getsize(pdf_path) / 1_048_576
    print(f"  ✅ PDF generated: {pdf_path} ({size_mb:.1f} MB)")
    return pdf_path


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    repo_root   = os.path.join(os.path.dirname(__file__), "..")
    content_dir = os.path.join(repo_root, "content")
    output_dir  = os.path.join(repo_root, "output")
    state_path  = os.path.join(repo_root, "state", "state.json")

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    pdf_path = generate_pdf(state, content_dir, output_dir)
    print(f"PDF saved to: {pdf_path}")
