"""GitHub Search API queries."""

from __future__ import annotations

import requests

from .utils import gh_get, paginate


class GitHubSearcher:
    def __init__(self, session: requests.Session):
        self.session = session

    def build_query(
        self,
        keywords: str | None = None,
        user: str | None = None,
        language: str | None = None,
        topics: list[str] | None = None,
        stars_min: int | None = None,
        stars_max: int | None = None,
        forks_min: int | None = None,
        forks_max: int | None = None,
        archived: bool = False,
    ) -> str:
        parts: list[str] = []

        if keywords:
            # Quote multi-word phrases
            parts.append(keywords)

        if user:
            # Support org:X or user:X — default to user:
            if ":" not in user:
                parts.append(f"user:{user}")
            else:
                parts.append(user)

        if language:
            # Handle languages with spaces like "Jupyter Notebook"
            lang = language if " " not in language else f'"{language}"'
            parts.append(f"language:{lang}")

        for topic in (topics or []):
            parts.append(f"topic:{topic}")

        # Stars range
        if stars_min is not None and stars_max is not None:
            parts.append(f"stars:{stars_min}..{stars_max}")
        elif stars_min is not None:
            parts.append(f"stars:>={stars_min}")
        elif stars_max is not None:
            parts.append(f"stars:<={stars_max}")

        if forks_min is not None:
            parts.append(f"forks:>={forks_min}")

        if not archived:
            parts.append("archived:false")

        return " ".join(parts) if parts else "stars:>=0"

    def search_repos(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        max_results: int = 20,
    ) -> list[dict]:
        """Search repositories via /search/repositories."""
        params = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(100, max_results),
        }
        return paginate(
            self.session,
            "/search/repositories",
            params,
            max_results=max_results,
        )

    def search_users_by_location(
        self, country: str, max_users: int = 50
    ) -> list[str]:
        """Search GitHub users by location, return list of logins."""
        params = {
            "q": f'location:"{country}"',
            "sort": "followers",
            "order": "desc",
            "per_page": min(100, max_users),
        }
        items = paginate(
            self.session,
            "/search/users",
            params,
            max_results=max_users,
        )
        return [u["login"] for u in items]

    def search_repos_by_users(
        self,
        usernames: list[str],
        extra_query: str = "",
        max_per_user: int = 5,
        sort: str = "stars",
        order: str = "desc",
    ) -> list[dict]:
        """Fetch repos for each user and merge, deduplicated."""
        seen: set[str] = set()
        results: list[dict] = []

        for login in usernames:
            user_query = f"user:{login}"
            if extra_query:
                user_query += f" {extra_query}"
            repos = self.search_repos(user_query, sort=sort, order=order, max_results=max_per_user)
            for repo in repos:
                key = repo.get("full_name", "")
                if key not in seen:
                    seen.add(key)
                    results.append(repo)

        return results

    def search(
        self,
        keywords: str | None = None,
        user: str | None = None,
        language: str | None = None,
        country: str | None = None,
        topics: list[str] | None = None,
        stars_min: int | None = None,
        stars_max: int | None = None,
        forks_min: int | None = None,
        forks_max: int | None = None,
        sort: str = "stars",
        order: str = "desc",
        max_results: int = 20,
    ) -> tuple[list[dict], str]:
        """Unified search entry point. Returns (repos, query_string)."""
        query = self.build_query(
            keywords=keywords,
            user=user,
            language=language,
            topics=topics,
            stars_min=stars_min,
            stars_max=stars_max,
            forks_min=forks_min,
            forks_max=forks_max,
        )

        if country:
            # Country-based: find users first, then their repos
            extra = self.build_query(
                keywords=keywords,
                language=language,
                topics=topics,
                stars_min=stars_min,
                stars_max=stars_max,
                forks_min=forks_min,
                forks_max=forks_max,
            )
            users = self.search_users_by_location(country, max_users=min(50, max_results * 3))
            repos = self.search_repos_by_users(
                users,
                extra_query=extra,
                max_per_user=max(3, max_results // max(len(users), 1) + 1),
                sort=sort,
                order=order,
            )
            # Sort merged results
            key_map = {"stars": "stargazers_count", "forks": "forks_count", "updated": "pushed_at"}
            sort_key = key_map.get(sort, "stargazers_count")
            repos.sort(key=lambda r: r.get(sort_key, 0), reverse=(order == "desc"))
            return repos[:max_results], f"location:{country} + {extra}"

        repos = self.search_repos(query, sort=sort, order=order, max_results=max_results)
        return repos, query
