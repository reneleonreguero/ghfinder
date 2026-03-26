"""Repository analysis — enriches raw search results with extra API calls."""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

import requests
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .utils import gh_get


def _extract_excerpt(text: str, max_chars: int = 600) -> str:
    """Extract a clean, meaningful excerpt from raw README Markdown."""
    lines = text.splitlines()
    clean: list[str] = []

    for line in lines:
        # Skip badge lines
        if "![" in line or "[![" in line:
            continue
        # Skip pure HTML tags lines
        if re.match(r"^\s*<[^>]+>\s*$", line):
            continue
        # Skip horizontal rules
        if re.match(r"^\s*[-=]{3,}\s*$", line):
            continue
        # Strip inline HTML
        line = re.sub(r"<[^>]+>", "", line)
        # Strip Markdown links but keep text: [text](url) → text
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        # Strip bold/italic markers
        line = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", line)
        # Strip heading hashes but keep text
        line = re.sub(r"^#{1,6}\s*", "", line)
        clean.append(line)

    # Join, collapse multiple blank lines, strip leading/trailing blanks
    text = "\n".join(clean)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) <= max_chars:
        return text

    # Truncate at last sentence boundary before max_chars
    truncated = text[:max_chars]
    last_period = max(truncated.rfind(". "), truncated.rfind(".\n"))
    if last_period > max_chars // 2:
        return truncated[: last_period + 1] + "…"
    # Fallback: truncate at last word
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space] + "…"
    return truncated + "…"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _days_ago(dt_str: str) -> int:
    try:
        return (_now() - _parse_dt(dt_str)).days
    except Exception:
        return -1


class RepoAnalyzer:
    def __init__(self, session: requests.Session):
        self.session = session
        self._lang_cache: dict[str, dict] = {}

    def get_languages(self, owner: str, repo: str) -> dict[str, float]:
        """Return language → percentage dict."""
        cache_key = f"{owner}/{repo}"
        if cache_key in self._lang_cache:
            return self._lang_cache[cache_key]

        resp = gh_get(self.session, f"/repos/{owner}/{repo}/languages")
        if resp.status_code != 200:
            return {}
        raw = resp.json()
        total = sum(raw.values()) or 1
        result = {lang: round(bytes_ / total * 100, 1) for lang, bytes_ in raw.items()}
        self._lang_cache[cache_key] = result
        return result

    def get_contributor_count(self, owner: str, repo: str) -> int:
        """Estimate contributor count via Link header pagination trick."""
        resp = gh_get(
            self.session,
            f"/repos/{owner}/{repo}/contributors",
            params={"per_page": 1, "anon": "true"},
        )
        if resp.status_code == 204:
            return 0
        if resp.status_code != 200:
            return -1

        link = resp.headers.get("Link", "")
        match = re.search(r'page=(\d+)>; rel="last"', link)
        if match:
            return int(match.group(1))
        # No pagination — count items on single page
        try:
            return len(resp.json())
        except Exception:
            return -1

    def check_ci_presence(self, owner: str, repo: str) -> dict[str, bool]:
        """Check for common CI/CD config files."""
        checks = {
            "github_actions": f"/repos/{owner}/{repo}/contents/.github/workflows",
            "travis": f"/repos/{owner}/{repo}/contents/.travis.yml",
            "circleci": f"/repos/{owner}/{repo}/contents/.circleci/config.yml",
            "jenkins": f"/repos/{owner}/{repo}/contents/Jenkinsfile",
        }
        result = {}
        for name, path in checks.items():
            resp = gh_get(self.session, path)
            result[name] = resp.status_code == 200
        return result

    def get_readme_content(self, owner: str, repo: str) -> str:
        """Fetch and decode README content. Returns empty string if not found."""
        resp = gh_get(self.session, f"/repos/{owner}/{repo}/readme")
        if resp.status_code != 200:
            return ""
        try:
            data = resp.json()
            encoded = data.get("content", "")
            return base64.b64decode(encoded).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def analyze_repo(self, repo_data: dict, deep: bool = True) -> dict:
        """Enrich raw repo dict with additional API data."""
        owner = repo_data["owner"]["login"]
        name = repo_data["name"]

        languages = {}
        contributor_count = -1
        ci = {"github_actions": False, "travis": False, "circleci": False, "jenkins": False}
        has_readme = False
        readme_excerpt = ""

        if deep:
            languages = self.get_languages(owner, name)
            contributor_count = self.get_contributor_count(owner, name)
            ci = self.check_ci_presence(owner, name)
            readme_raw = self.get_readme_content(owner, name)
            has_readme = bool(readme_raw)
            readme_excerpt = _extract_excerpt(readme_raw) if readme_raw else ""

        license_info = repo_data.get("license")
        license_name = license_info.get("spdx_id") if license_info else "None"

        created_at = repo_data.get("created_at", "")
        pushed_at = repo_data.get("pushed_at", "")

        return {
            "name": repo_data["name"],
            "full_name": repo_data["full_name"],
            "description": repo_data.get("description") or "",
            "url": repo_data["html_url"],
            "stars": repo_data.get("stargazers_count", 0),
            "forks": repo_data.get("forks_count", 0),
            "watchers": repo_data.get("watchers_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0),
            "size_kb": repo_data.get("size", 0),
            "language": repo_data.get("language") or "—",
            "license": license_name or "None",
            "topics": repo_data.get("topics", []),
            "has_readme": has_readme,
            "created_at": created_at,
            "pushed_at": pushed_at,
            "updated_at": repo_data.get("updated_at", ""),
            "age_days": _days_ago(created_at) if created_at else -1,
            "days_since_push": _days_ago(pushed_at) if pushed_at else -1,
            "is_fork": repo_data.get("fork", False),
            "is_archived": repo_data.get("archived", False),
            "default_branch": repo_data.get("default_branch", "main"),
            "languages": languages,
            "contributor_count": contributor_count,
            "ci": ci,
            "readme_excerpt": readme_excerpt,
        }

    def analyze_batch(
        self, repos: list[dict], deep: bool = True
    ) -> list[dict]:
        """Analyze a list of repos with a progress bar."""
        results = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Analyzing repositories...", total=len(repos))
            for repo in repos:
                name = repo.get("full_name", repo.get("name", "?"))
                progress.update(task, description=f"Analyzing [cyan]{name}[/cyan]")
                results.append(self.analyze_repo(repo, deep=deep))
                progress.advance(task)
        return results
