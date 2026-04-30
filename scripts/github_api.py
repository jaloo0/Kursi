"""
github_api.py — GitHub API helpers: commit files, read files, trigger workflows.
"""

import os
import base64
import json
import time
import requests
from typing import Optional


GH_API = "https://api.github.com"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ── File operations ───────────────────────────────────────────────────────────

def get_file_sha(token: str, owner: str, repo: str, path: str) -> Optional[str]:
    """Get SHA of an existing file (needed for updates)."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/{path}"
    r = requests.get(url, headers=_headers(token), timeout=15)
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def commit_file(
    token: str,
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
) -> bool:
    """Create or update a file in the repo via the GitHub API."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/{path}"
    sha = get_file_sha(token, owner, repo, path)

    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    payload: dict = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_headers(token), json=payload, timeout=30)
    return r.status_code in (200, 201)


def read_file(
    token: str,
    owner: str,
    repo: str,
    path: str,
    branch: str = "main",
) -> Optional[str]:
    """Read a file's decoded content from the repo."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    r = requests.get(url, headers=_headers(token), timeout=15)
    if r.status_code == 200:
        return base64.b64decode(r.json()["content"]).decode("utf-8")
    return None


def read_state(token: str, owner: str, repo: str) -> Optional[dict]:
    """Read and parse state.json from the repo."""
    raw = read_file(token, owner, repo, "state/state.json")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def commit_state(token: str, owner: str, repo: str, state: dict) -> bool:
    """Write state.json to the repo."""
    content = json.dumps(state, indent=2, ensure_ascii=False)
    return commit_file(
        token, owner, repo, "state/state.json",
        content, "📊 Update generation state [skip ci]",
    )


def commit_section_content(
    token: str,
    owner: str,
    repo: str,
    filename: str,
    content: str,
) -> bool:
    """Commit a generated section markdown file."""
    return commit_file(
        token, owner, repo, f"content/{filename}",
        content, f"✍️ Write section: {filename} [skip ci]",
    )


def commit_pdf(
    token: str,
    owner: str,
    repo: str,
    pdf_bytes: bytes,
    filename: str = "output/course_final.pdf",
) -> bool:
    """Commit the final PDF file to the repo."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/{filename}"
    sha = get_file_sha(token, owner, repo, filename)
    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    payload: dict = {
        "message": "📄 Course PDF generated [skip ci]",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=_headers(token), json=payload, timeout=60)
    return r.status_code in (200, 201)


def get_pdf_download_url(
    token: str,
    owner: str,
    repo: str,
    filename: str = "output/course_final.pdf",
) -> Optional[str]:
    """Get download URL for the PDF."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/{filename}"
    r = requests.get(url, headers=_headers(token), timeout=15)
    if r.status_code == 200:
        return r.json().get("download_url")
    return None


# ── Workflow operations ───────────────────────────────────────────────────────

def trigger_workflow(
    token: str,
    owner: str,
    repo: str,
    workflow_file: str = "generate.yml",
    ref: str = "main",
    inputs: Optional[dict] = None,
) -> bool:
    """Trigger a workflow_dispatch event."""
    url = f"{GH_API}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": ref, "inputs": inputs or {"session_type": "resume"}}
    r = requests.post(url, headers=_headers(token), json=payload, timeout=15)
    return r.status_code == 204


def get_latest_workflow_run(
    token: str,
    owner: str,
    repo: str,
    workflow_file: str = "generate.yml",
) -> Optional[dict]:
    """Get the most recent run of a workflow."""
    url = f"{GH_API}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/runs"
    r = requests.get(url, headers=_headers(token), params={"per_page": 1}, timeout=15)
    if r.status_code == 200:
        runs = r.json().get("workflow_runs", [])
        return runs[0] if runs else None
    return None


def list_content_files(
    token: str,
    owner: str,
    repo: str,
) -> list:
    """List all markdown files in the content/ directory."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/content"
    r = requests.get(url, headers=_headers(token), timeout=15)
    if r.status_code == 200:
        return [f for f in r.json() if f["name"].endswith(".md")]
    return []


def upload_outline(
    token: str,
    owner: str,
    repo: str,
    outline_text: str,
    course_title: str,
) -> bool:
    """Upload the outline and config to the repo to kick off a new course."""
    ok1 = commit_file(
        token, owner, repo, "input/outline.txt",
        outline_text, "📋 Upload course outline [skip ci]",
    )
    config = json.dumps({"course_title": course_title}, indent=2)
    ok2 = commit_file(
        token, owner, repo, "input/config.json",
        config, "⚙️ Upload course config [skip ci]",
    )
    return ok1 and ok2
