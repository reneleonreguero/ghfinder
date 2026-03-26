"""Rich terminal output for ghfinder."""

from __future__ import annotations

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(highlight=False)

# Language → color mapping
LANG_COLORS: dict[str, str] = {
    "Python": "blue",
    "JavaScript": "yellow",
    "TypeScript": "cyan",
    "Go": "green",
    "Rust": "red",
    "Java": "orange3",
    "C": "white",
    "C++": "bright_red",
    "C#": "purple",
    "Ruby": "red3",
    "PHP": "magenta",
    "Swift": "orange1",
    "Kotlin": "bright_magenta",
    "Scala": "red",
    "Shell": "green3",
    "HTML": "orange3",
    "CSS": "blue",
    "Lua": "blue3",
    "Haskell": "purple",
    "Elixir": "magenta",
    "Dart": "cyan",
    "Vim Script": "green",
    "R": "blue",
    "Julia": "bright_cyan",
}

# Unicode block chars for bar charts
BLOCKS = "█"


def _lang_color(lang: str) -> str:
    return LANG_COLORS.get(lang, "white")


def _relative_date(days: int) -> str:
    if days < 0:
        return "unknown"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        return f"{days // 7}w ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def _ci_badges(ci: dict) -> str:
    badges = []
    if ci.get("github_actions"):
        badges.append("[green]GHA[/green]")
    if ci.get("travis"):
        badges.append("[yellow]Travis[/yellow]")
    if ci.get("circleci"):
        badges.append("[blue]Circle[/blue]")
    if ci.get("jenkins"):
        badges.append("[red]Jenkins[/red]")
    return " ".join(badges) if badges else "[dim]—[/dim]"


def print_header(query_info: str, token_status: bool) -> None:
    auth = "[green]authenticated[/green]" if token_status else "[yellow]unauthenticated[/yellow]"
    console.print(
        Panel(
            f"[bold cyan]ghfinder[/bold cyan]  GitHub Repository Search & Analysis\n"
            f"Query: [italic]{query_info}[/italic]  •  Status: {auth}",
            border_style="cyan",
        )
    )


def print_summary_panel(total: int, shown: int, elapsed: float, query: str) -> None:
    console.print(
        Panel(
            f"Found [bold]{total}[/bold] repositories  •  Showing [bold]{shown}[/bold]  "
            f"•  Query: [italic]{query}[/italic]  •  Elapsed: {elapsed:.1f}s",
            border_style="dim",
        )
    )


def print_results_table(analyses: list[dict]) -> None:
    table = Table(
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("Repository", min_width=22, no_wrap=True)
    table.add_column("Description", min_width=30)
    table.add_column("Stars", justify="right", style="yellow", width=8)
    table.add_column("Language", width=13)
    table.add_column("License", width=11)
    table.add_column("Last Push", width=10)

    for i, a in enumerate(analyses, 1):
        lang = a.get("language", "—")
        lang_text = Text(lang, style=_lang_color(lang))

        flags = ""
        if a.get("is_archived"):
            flags += " [dim][archived][/dim]"
        if a.get("is_fork"):
            flags += " [dim][fork][/dim]"

        # Best available short description
        desc = a.get("description") or ""
        if not desc:
            excerpt = a.get("readme_excerpt", "") or ""
            desc = excerpt[:120].split("\n")[0]
        if len(desc) > 80:
            desc = desc[:77] + "…"
        if not desc:
            desc = "[dim]—[/dim]"

        table.add_row(
            str(i),
            f"[link={a['url']}]{a['full_name']}[/link]{flags}",
            desc,
            f"⭐ {a.get('stars', 0):,}",
            lang_text,
            a.get("license", "None"),
            _relative_date(a.get("days_since_push", -1)),
        )

    console.print(table)


def print_language_bar(languages: dict[str, float], width: int = 40) -> str:
    """Return a colored Unicode block bar string."""
    if not languages:
        return "[dim]No language data[/dim]"

    bar = ""
    label_parts = []
    sorted_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)

    for lang, pct in sorted_langs[:6]:
        color = _lang_color(lang)
        blocks = max(1, round(pct / 100 * width))
        bar += f"[{color}]{BLOCKS * blocks}[/{color}]"
        label_parts.append(f"[{color}]{lang}[/{color}] {pct:.1f}%")

    return bar + "  " + "  ".join(label_parts)


def print_repo_detail(a: dict) -> None:
    """Print full detail panel for one repo."""
    # Header
    title = Text()
    title.append(a["full_name"], style="bold cyan")
    if a.get("is_archived"):
        title.append("  [archived]", style="dim")
    if a.get("is_fork"):
        title.append("  [fork]", style="dim")

    desc = a.get("description") or "[dim]No description[/dim]"

    # Stats grid
    stats = Columns(
        [
            Panel(f"[yellow]⭐ {a.get('stars', 0):,}[/yellow]", title="Stars", width=16),
            Panel(f"[cyan]{a.get('forks', 0):,}[/cyan]", title="Forks", width=16),
            Panel(f"{a.get('watchers', 0):,}", title="Watchers", width=16),
            Panel(f"[red]{a.get('open_issues', 0):,}[/red]", title="Open Issues", width=16),
            Panel(
                str(a.get("contributor_count", "?")) if a.get("contributor_count", -1) >= 0 else "?",
                title="Contributors",
                width=14,
            ),
        ],
        equal=False,
    )

    # Language bar
    lang_bar = print_language_bar(a.get("languages", {}))

    # Activity
    activity = (
        f"Created:    {a.get('created_at', '?')[:10]}  ({_relative_date(a.get('age_days', -1))})\n"
        f"Last push:  {a.get('pushed_at', '?')[:10]}  ({_relative_date(a.get('days_since_push', -1))})\n"
        f"Branch:     {a.get('default_branch', 'main')}"
    )

    # CI/CD
    ci = a.get("ci", {})
    ci_text = _ci_badges(ci) if any(ci.values()) else "[dim]No CI/CD detected[/dim]"

    # Topics
    topics = a.get("topics", [])
    topics_text = "  ".join(f"[dim blue]#{t}[/dim blue]" for t in topics) if topics else "[dim]—[/dim]"

    # README & license
    meta = f"License: [cyan]{a.get('license', 'None')}[/cyan]  •  README: {'[green]Yes[/green]' if a.get('has_readme') else '[red]No[/red]'}  •  Size: {a.get('size_kb', 0):,} KB"

    # README excerpt
    excerpt = a.get("readme_excerpt", "")
    about_section = f"\n[bold]About (README)[/bold]\n[dim]{excerpt}[/dim]\n" if excerpt else ""

    body = (
        f"{desc}\n\n"
        f"[link={a['url']}]{a['url']}[/link]\n\n"
        f"{meta}"
        f"{about_section}\n"
        f"[bold]Languages[/bold]\n{lang_bar}\n\n"
        f"[bold]Activity[/bold]\n{activity}\n\n"
        f"[bold]CI/CD[/bold]  {ci_text}\n\n"
        f"[bold]Topics[/bold]  {topics_text}"
    )

    console.print(Panel(body, title=title, border_style="cyan", padding=(1, 2)))
    console.print(stats)
    console.print()
