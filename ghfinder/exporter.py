"""Export analyzed repo data to JSON, CSV, or Markdown."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime


class DataExporter:
    def to_json(self, analyses: list[dict], output_path: str, query_info: str = "") -> None:
        payload = {
            "query": query_info,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "total": len(analyses),
            "repositories": analyses,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)

    def to_csv(self, analyses: list[dict], output_path: str, query_info: str = "") -> None:
        if not analyses:
            return

        def flatten(a: dict) -> dict:
            row = {
                k: v
                for k, v in a.items()
                if k not in ("languages", "ci", "topics")
            }
            # Flatten languages (top 5)
            langs = a.get("languages", {})
            top_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:5]
            for lang, pct in top_langs:
                row[f"lang_{lang}"] = pct

            # Flatten CI
            for ci_name, present in a.get("ci", {}).items():
                row[f"ci_{ci_name}"] = present

            # Topics as semicolon-separated
            row["topics"] = ";".join(a.get("topics", []))
            return row

        rows = [flatten(a) for a in analyses]
        all_keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for k in row:
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def to_markdown(
        self, analyses: list[dict], output_path: str, query_info: str = ""
    ) -> None:
        lines = [
            "# GitHub Repository Search Results",
            "",
            f"**Query:** `{query_info}`  ",
            f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  ",
            f"**Total:** {len(analyses)} repositories",
            "",
            "---",
            "",
            "## Summary Table",
            "",
            "| # | Repository | Stars | Forks | Language | License | Last Push |",
            "|---|-----------|------:|------:|----------|---------|-----------|",
        ]

        def rel_date(days: int) -> str:
            if days < 0:
                return "?"
            if days < 7:
                return f"{days}d ago"
            if days < 30:
                return f"{days // 7}w ago"
            if days < 365:
                return f"{days // 30}mo ago"
            return f"{days // 365}y ago"

        for i, a in enumerate(analyses, 1):
            lines.append(
                f"| {i} | [{a['full_name']}]({a['url']}) "
                f"| {a.get('stars', 0):,} "
                f"| {a.get('forks', 0):,} "
                f"| {a.get('language', '—')} "
                f"| {a.get('license', 'None')} "
                f"| {rel_date(a.get('days_since_push', -1))} |"
            )

        lines += ["", "---", "", "## Repository Details", ""]

        for a in analyses:
            ci = a.get("ci", {})
            ci_list = [k for k, v in ci.items() if v]
            ci_str = ", ".join(ci_list) if ci_list else "None"

            langs = a.get("languages", {})
            top_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:5]
            langs_str = ", ".join(f"{l} {p:.1f}%" for l, p in top_langs) if top_langs else a.get("language", "—")

            topics = a.get("topics", [])
            topics_str = " ".join(f"`#{t}`" for t in topics) if topics else "—"

            contrib = a.get("contributor_count", -1)
            contrib_str = str(contrib) if contrib >= 0 else "?"

            excerpt = a.get("readme_excerpt", "")
            about_block = ["> " + line if line else ">" for line in excerpt.splitlines()] if excerpt else []

            lines += [
                f"### [{a['full_name']}]({a['url']})",
                "",
                f"{a.get('description') or '_No description_'}",
                *( [""] + about_block + [""] if about_block else [] ),
                "",
                f"- **Stars:** {a.get('stars', 0):,}  **Forks:** {a.get('forks', 0):,}  "
                f"**Watchers:** {a.get('watchers', 0):,}  **Open Issues:** {a.get('open_issues', 0):,}",
                f"- **Language:** {a.get('language', '—')}  **License:** {a.get('license', 'None')}",
                f"- **Languages:** {langs_str}",
                f"- **Contributors:** {contrib_str}",
                f"- **CI/CD:** {ci_str}",
                f"- **Created:** {a.get('created_at', '?')[:10]}  **Last Push:** {a.get('pushed_at', '?')[:10]}",
                f"- **Archived:** {a.get('is_archived', False)}  **Fork:** {a.get('is_fork', False)}",
                f"- **Topics:** {topics_str}",
                "",
            ]

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def export(
        self,
        analyses: list[dict],
        output_path: str,
        fmt: str | None = None,
        query_info: str = "",
    ) -> str:
        """Detect format from extension or fmt param and export."""
        if not fmt:
            ext = os.path.splitext(output_path)[1].lower()
            fmt = {".json": "json", ".csv": "csv", ".md": "markdown", ".markdown": "markdown"}.get(
                ext, "json"
            )
        if fmt == "json":
            self.to_json(analyses, output_path, query_info)
        elif fmt == "csv":
            self.to_csv(analyses, output_path, query_info)
        elif fmt in ("markdown", "md"):
            self.to_markdown(analyses, output_path, query_info)
        else:
            raise ValueError(f"Unknown export format: {fmt}")
        return fmt
