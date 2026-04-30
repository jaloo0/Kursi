import streamlit as st
import requests
import json
import base64
import time
from datetime import datetime

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Kursi — AI Course Generator",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background: #0a0e1a; }

.hero-title {
    font-size: 3rem; font-weight: 800;
    background: linear-gradient(135deg, #60a5fa, #a78bfa, #f472b6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    line-height: 1.1; margin-bottom: 0.5rem;
}
.hero-sub { color: #94a3b8; font-size: 1.1rem; margin-bottom: 2rem; }

.glass-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px; padding: 1.5rem;
    margin-bottom: 1rem;
    backdrop-filter: blur(12px);
}

.stat-card {
    background: rgba(96,165,250,0.08);
    border: 1px solid rgba(96,165,250,0.2);
    border-radius: 12px; padding: 1rem 1.25rem;
    text-align: center;
}
.stat-number { font-size: 2rem; font-weight: 700; color: #60a5fa; }
.stat-label  { font-size: 0.8rem; color: #64748b; text-transform: uppercase; letter-spacing: 1px; }

.section-row {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 0.85rem;
}
.badge-done    { background:#16a34a22; color:#4ade80; border:1px solid #16a34a44; padding:2px 8px; border-radius:20px; font-size:0.75rem; }
.badge-prog    { background:#d9770622; color:#fb923c; border:1px solid #d9770644; padding:2px 8px; border-radius:20px; font-size:0.75rem; }
.badge-pend    { background:#1e293b;   color:#64748b; border:1px solid #334155;   padding:2px 8px; border-radius:20px; font-size:0.75rem; }
.badge-err     { background:#dc262622; color:#f87171; border:1px solid #dc262644; padding:2px 8px; border-radius:20px; font-size:0.75rem; }

.log-box {
    background: #0d1117; border-radius: 10px; padding: 1rem;
    font-family: monospace; font-size: 0.8rem; color: #7dd3fc;
    max-height: 200px; overflow-y: auto;
}

.status-pill {
    display:inline-block; padding:4px 14px; border-radius:20px;
    font-size:0.8rem; font-weight:600;
}
.status-running { background:#16a34a22; color:#4ade80; border:1px solid #16a34a55; }
.status-paused  { background:#d9770622; color:#fb923c; border:1px solid #d9770655; }
.status-done    { background:#7c3aed22; color:#a78bfa; border:1px solid #7c3aed55; }
.status-idle    { background:#1e293b;   color:#64748b; border:1px solid #33415577; }

div[data-testid="stButton"] button {
    background: linear-gradient(135deg,#2563eb,#7c3aed);
    color:white; border:none; border-radius:10px;
    padding:0.6rem 2rem; font-weight:600; font-size:1rem;
    transition: opacity 0.2s;
}
div[data-testid="stButton"] button:hover { opacity:0.85; }
</style>
""", unsafe_allow_html=True)

# ── Secrets ───────────────────────────────────────────────────────────────────
try:
    GH_TOKEN   = st.secrets["GITHUB_TOKEN"]
    REPO_OWNER = st.secrets["REPO_OWNER"]
    REPO_NAME  = st.secrets["REPO_NAME"]
    SECRETS_OK = True
except Exception:
    SECRETS_OK = False

GH_API   = "https://api.github.com"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_OWNER if SECRETS_OK else 'owner'}/{REPO_NAME if SECRETS_OK else 'repo'}/main"

# ── GitHub helpers ────────────────────────────────────────────────────────────

def gh_headers():
    return {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def read_state() -> dict:
    try:
        r = requests.get(f"{RAW_BASE}/state/state.json", timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def commit_file_gh(path: str, content_str: str, message: str) -> bool:
    url = f"{GH_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    # Get SHA if exists
    sha = None
    r = requests.get(url, headers=gh_headers(), timeout=10)
    if r.status_code == 200:
        sha = r.json().get("sha")
    encoded = base64.b64encode(content_str.encode()).decode()
    payload = {"message": message, "content": encoded, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=gh_headers(), json=payload, timeout=20)
    return r.status_code in (200, 201)


def trigger_workflow(session_type: str = "start_fresh") -> bool:
    url = f"{GH_API}/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/generate.yml/dispatches"
    r = requests.post(
        url, headers=gh_headers(),
        json={"ref": "main", "inputs": {"session_type": session_type}},
        timeout=15,
    )
    return r.status_code == 204


def get_workflow_runs() -> list:
    url = f"{GH_API}/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/generate.yml/runs"
    r = requests.get(url, headers=gh_headers(), params={"per_page": 5}, timeout=10)
    if r.status_code == 200:
        return r.json().get("workflow_runs", [])
    return []


def get_pdf_bytes() -> bytes | None:
    url = f"{GH_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/output/course_final.pdf"
    r = requests.get(url, headers=gh_headers(), timeout=15)
    if r.status_code == 200:
        return base64.b64decode(r.json()["content"])
    return None


# ── UI Layout ─────────────────────────────────────────────────────────────────

# Sidebar
with st.sidebar:
    st.markdown("### ⚙️ System")
    if not SECRETS_OK:
        st.error("❌ Secrets not configured.\nAdd them in `.streamlit/secrets.toml`")
    else:
        st.success("✅ Secrets loaded")

    st.divider()
    state = read_state()
    status = state.get("status", "idle")
    badge_class = {
        "running": "status-running",
        "paused":  "status-paused",
        "done":    "status-done",
    }.get(status, "status-idle")
    st.markdown(
        f"**Status:** <span class='status-pill {badge_class}'>{status.upper()}</span>",
        unsafe_allow_html=True,
    )

    if state.get("course_title"):
        st.markdown(f"**Course:** {state['course_title']}")

    st.divider()
    st.markdown("**Recent Runs**")
    if SECRETS_OK:
        runs = get_workflow_runs()
        for run in runs[:3]:
            icon = {"completed": "✅", "in_progress": "🔄", "failure": "❌"}.get(
                run.get("conclusion") or run.get("status"), "⏳"
            )
            created = run.get("created_at", "")[:16].replace("T", " ")
            st.markdown(
                f"{icon} `{created}` — [{run.get('status','')}]"
                f"({run.get('html_url','')})"
            )
    st.divider()
    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)


# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown('<div class="hero-title">📚 Kursi</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-sub">AI-powered overnight course content generator — '
    'paste your outline, sleep, wake up to a PDF.</div>',
    unsafe_allow_html=True,
)

tab_new, tab_progress, tab_download = st.tabs(["🚀 New Course", "📊 Progress", "📄 Download PDF"])

# ══════════════════════════════════════════════════════
# TAB 1 — New Course
# ══════════════════════════════════════════════════════
with tab_new:
    col1, col2 = st.columns([2, 1], gap="large")

    with col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        course_title = st.text_input(
            "📖 Course Title",
            placeholder="e.g. Complete Python Bootcamp for Beginners",
        )

        st.markdown("**📋 Course Outline** — plain text, Week X: Title → bullet topics")
        outline_file = st.file_uploader("Upload outline file (.txt, .md)", type=["txt", "md"])
        outline_text = ""
        if outline_file:
            outline_text = outline_file.read().decode("utf-8")
            st.success(f"✅ File loaded ({len(outline_text)} chars)")
            with st.expander("Preview outline"):
                st.text(outline_text[:800] + ("..." if len(outline_text) > 800 else ""))
        else:
            outline_text = st.text_area(
                "Or paste outline here",
                height=220,
                placeholder="""Week 1: Introduction to Python
- What is Python?
- Setting Up Your Environment
- Writing Your First Program

Week 2: Core Concepts
- Variables and Data Types
- Control Flow
- Functions""",
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("#### 💡 How It Works")
        st.markdown("""
1. **Paste** your detailed outline
2. **Click Start** → GitHub Actions begins
3. AI **writes** each section with full context
4. Auto **pauses** to respect rate limits
5. **Resumes** automatically overnight
6. **Morning**: download your PDF 🎉
        """)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("#### ⏱ Estimated Time")
        if outline_text:
            lines   = [l.strip() for l in outline_text.splitlines() if l.strip()]
            topics  = sum(1 for l in lines if l.startswith(("-", "•", "*")) or (l[:2].rstrip(".").isdigit()))
            est_min = max(topics * 1.5, 10)
            st.markdown(f"**~{topics} topics** → ~{round(est_min)} min")
        else:
            st.markdown("Upload outline to estimate.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    if st.button("🚀 Start Overnight Generation", use_container_width=True, disabled=not SECRETS_OK):
        if not course_title.strip():
            st.error("Please enter a course title.")
        elif not outline_text.strip():
            st.error("Please provide an outline.")
        else:
            with st.spinner("Uploading outline & triggering GitHub Actions..."):
                ok1 = commit_file_gh(
                    "input/outline.txt", outline_text,
                    "📋 Upload course outline [skip ci]",
                )
                ok2 = commit_file_gh(
                    "input/config.json",
                    json.dumps({"course_title": course_title}, indent=2),
                    "⚙️ Upload course config [skip ci]",
                )
                time.sleep(1)
                ok3 = trigger_workflow("start_fresh")

            if ok1 and ok2 and ok3:
                st.success(
                    "✅ Generation started! GitHub Actions is writing your course.\n\n"
                    "Switch to the **📊 Progress** tab to monitor in real-time."
                )
                st.balloons()
            else:
                st.error(
                    f"❌ Something failed. outline={ok1}, config={ok2}, trigger={ok3}\n"
                    "Check your GitHub token and repo name in secrets."
                )

# ══════════════════════════════════════════════════════
# TAB 2 — Progress
# ══════════════════════════════════════════════════════
with tab_progress:
    if st.button("🔄 Refresh Now"):
        st.rerun()

    state = read_state()
    sections = state.get("sections", [])
    total    = len(sections)
    done     = sum(1 for s in sections if s.get("status") == "done")
    pending  = sum(1 for s in sections if s.get("status") == "pending")
    errors   = sum(1 for s in sections if s.get("status") == "error")
    words    = sum(s.get("word_count", 0) for s in sections if s.get("status") == "done")

    # Stats row
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, num, label in [
        (c1, total,   "Total Sections"),
        (c2, done,    "Completed ✅"),
        (c3, pending, "Remaining ⏳"),
        (c4, errors,  "Errors ⚠️"),
        (c5, f"{words:,}", "Words Written"),
    ]:
        col.markdown(
            f'<div class="stat-card"><div class="stat-number">{num}</div>'
            f'<div class="stat-label">{label}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("#### Overall Progress")
    pct = done / total if total > 0 else 0
    st.progress(pct, text=f"{done}/{total} sections — {round(pct*100)}%")

    # Sessions
    sessions = state.get("sessions", [])
    if sessions:
        last = sessions[-1]
        cols = st.columns(3)
        cols[0].metric("Sessions Run", len(sessions))
        cols[1].metric("Last Session Wrote", f"{last.get('sections_written', 0)} sections")
        cols[2].metric("Stop Reason", last.get("reason_stopped", "—"))

    st.divider()

    # Section list
    st.markdown("#### Section Status")
    if sections:
        current_week = 0
        for s in sections:
            if s["week"] != current_week:
                current_week = s["week"]
                st.markdown(
                    f"**Week {s['week']}: {s['week_title']}**",
                )
            status_s = s.get("status", "pending")
            badge = {
                "done":        "<span class='badge-done'>✅ done</span>",
                "in_progress": "<span class='badge-prog'>🔄 writing</span>",
                "pending":     "<span class='badge-pend'>⏳ pending</span>",
                "error":       "<span class='badge-err'>❌ error</span>",
            }.get(status_s, "<span class='badge-pend'>?</span>")
            wc = f"  ·  {s['word_count']:,} words" if s.get("word_count") else ""
            st.markdown(
                f'<div class="section-row">{badge} &nbsp;'
                f'{s["topic_index"]}. {s["title"]}'
                f'<span style="color:#475569;font-size:0.78rem">{wc}</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("No sections found. Start a generation to see progress here.")

    # Context window (what AI remembers)
    ctx = state.get("context_window", [])
    if ctx:
        with st.expander("🧠 AI Memory (last written summaries)"):
            for i, c in enumerate(ctx[-4:], 1):
                st.markdown(f"**{i}.** {c}")

    # API stats
    api = state.get("api_stats", {})
    if api.get("total_api_calls"):
        with st.expander("📈 API Usage"):
            a1, a2, a3 = st.columns(3)
            a1.metric("Total API Calls",   api.get("total_api_calls", 0))
            a2.metric("Total Tokens Used", f"{api.get('total_tokens', 0):,}")
            a3.metric("Sessions Count",    api.get("sessions_count", 0))

    # Manual resume
    st.divider()
    st.markdown("#### Manual Controls")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("▶️ Resume Generation", disabled=not SECRETS_OK):
            if trigger_workflow("resume"):
                st.success("Resume triggered!")
            else:
                st.error("Failed to trigger workflow.")
    with col_b:
        last_updated = state.get("last_updated", "")
        if last_updated:
            st.caption(f"Last updated: {last_updated[:19].replace('T', ' ')} UTC")

# ══════════════════════════════════════════════════════
# TAB 3 — Download PDF
# ══════════════════════════════════════════════════════
with tab_download:
    state = read_state()
    if state.get("pdf_ready"):
        st.markdown(
            '<div class="glass-card" style="text-align:center; padding:3rem;">'
            '<div style="font-size:4rem">🎉</div>'
            '<h2 style="color:#a78bfa">Your Course PDF is Ready!</h2>'
            '<p style="color:#94a3b8">Click below to download your complete course book.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        title = state.get("course_title", "course")
        safe_title = title.replace(" ", "_")[:40]

        if SECRETS_OK:
            with st.spinner("Fetching PDF from GitHub..."):
                pdf_bytes = get_pdf_bytes()
            if pdf_bytes:
                st.download_button(
                    "📄 Download Course PDF",
                    data=pdf_bytes,
                    file_name=f"{safe_title}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
                prog = {}
                total = len(state.get("sections", []))
                done  = sum(1 for s in state.get("sections", []) if s.get("status") == "done")
                words = sum(s.get("word_count", 0) for s in state.get("sections", []) if s.get("status") == "done")
                st.markdown(
                    f"**Course:** {title}  \n"
                    f"**Sections:** {done}/{total}  \n"
                    f"**Total words:** ~{words:,}"
                )
            else:
                st.warning("PDF not found in repo. Try refreshing in a minute.")
    else:
        status = state.get("status", "idle")
        st.markdown(
            '<div class="glass-card" style="text-align:center; padding:3rem;">'
            f'<div style="font-size:3rem">{"⏳" if status in ("running","paused") else "🌙"}</div>'
            f'<h3 style="color:#94a3b8">{"Course generation in progress..." if status in ("running","paused") else "No active generation"}</h3>'
            '<p style="color:#64748b">The PDF will appear here automatically once generation completes.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        if status == "idle":
            st.info("Go to **🚀 New Course** tab to start a generation.")

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
