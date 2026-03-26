"""Repository analysis — enriches raw search results with extra API calls."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import requests
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .utils import gh_get


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

    def check_readme(self, owner: str, repo: str) -> bool:
        """Check if README exists."""
        resp = gh_get(self.session, f"/repos/{owner}/{repo}/contents/README.md")
        if resp.status_code == 200:
            return True
        # Try uppercase variants
        resp2 = gh_get(self.session, f"/repos/{owner}/{repo}/readme")
        return resp2.status_code == 200

    def analyze_repo(self, repo_data: dict, deep: bool = True) -> dict:
        """Enrich raw repo dict with additional API data."""
        owner = repo_data["owner"]["login"]
        name = repo_data["name"]

        languages = {}
        contributor_count = -1
        ci = {"github_actions": False, "travis": False, "circleci": False, "jenkins": False}
        has_readme = False

        if deep:
            languages = self.get_languages(owner, name)
            contributor_count = self.get_contributor_count(owner, name)
            ci = self.check_ci_presence(owner, name)
            has_readme = self.check_readme(owner, name)

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
