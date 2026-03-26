"""ghfinder CLI — GitHub repository search and analysis."""

from __future__ import annotations

import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .analyzer import RepoAnalyzer
from .exporter import DataExporter
from .reporter import console, print_header, print_repo_detail, print_results_table, print_summary_panel
from .search import GitHubSearcher
from .utils import GITHUB_API, create_session, gh_get, is_authenticated

err_console = Console(stderr=True)


@click.group()
@click.version_option(__version__, prog_name="ghfinder")
def cli():
    """ghfinder — Search and analyze GitHub repositories."""


@cli.command()
@click.option("-k", "--keywords", default=None, help="Keywords or repo name fragment")
@click.option("-u", "--user", default=None, help="GitHub username or organization")
@click.option("-l", "--language", default=None, help="Programming language filter")
@click.option("-c", "--country", default=None, help="Country/location of repo authors")
@click.option("-t", "--topic", multiple=True, help="Topic tag (repeatable: -t python -t web)")
@click.option("--stars-min", default=None, type=int, help="Minimum star count")
@click.option("--stars-max", default=None, type=int, help="Maximum star count")
@click.option("--forks-min", default=None, type=int, help="Minimum fork count")
@click.option("-n", "--max-results", default=20, show_default=True, type=int, help="Max repos to return")
@click.option(
    "--sort",
    default="stars",
    show_default=True,
    type=click.Choice(["stars", "forks", "updated"], case_sensitive=False),
    help="Sort order",
)
@click.option(
    "--order",
    default="desc",
    show_default=True,
    type=click.Choice(["desc", "asc"], case_sensitive=False),
    help="Sort direction",
)
@click.option("--analyze/--no-analyze", default=None, help="Run detailed analysis (default: yes with token, no without)")
@click.option("--detail", is_flag=True, default=False, help="Show full detail panel per repo")
@click.option("--export", default=None, help="Export file path (.json, .csv, or .md)")
@click.option(
    "--format", "fmt",
    default=None,
    type=click.Choice(["json", "csv", "markdown"], case_sensitive=False),
    help="Export format (overrides file extension detection)",
)
@click.option("--token", default=None, envvar="GITHUB_TOKEN", help="GitHub personal access token")
def search(
    keywords, user, language, country, topic, stars_min, stars_max, forks_min,
    max_results, sort, order, analyze, detail, export, fmt, token,
):
    """Search GitHub repositories with optional deep analysis."""
    start = time.time()

    session = create_session(token)
    authenticated = is_authenticated(session)
    searcher = GitHubSearcher(session)

    # Without token: default to no deep analysis and cap results to avoid rate limits
    if analyze is None:
        analyze = authenticated
    if not authenticated and max_results > 10:
        max_results = 10

    topics = list(topic) if topic else []

    # Build display query string
    parts = []
    if keywords:
        parts.append(keywords)
    if user:
        parts.append(f"user:{user}")
    if language:
        parts.append(f"lang:{language}")
    if country:
        parts.append(f"country:{country}")
    for t in topics:
        parts.append(f"topic:{t}")
    if stars_min:
        parts.append(f"stars>={stars_min}")
    query_display = " ".join(parts) if parts else "(all)"

    print_header(query_display, authenticated)

    if not authenticated:
        mode = "quick mode (no deep analysis)" if not analyze else "deep analysis — may be slow without token"
        err_console.print(f"[dim]No token detected — running {mode}. Use --analyze to force analysis.[/dim]")

    # --- Search ---
    with err_console.status("[cyan]Searching repositories...[/cyan]"):
        try:
            repos, query_str = searcher.search(
                keywords=keywords,
                user=user,
                language=language,
                country=country,
                topics=topics,
                stars_min=stars_min,
                stars_max=stars_max,
                forks_min=forks_min,
                sort=sort,
                order=order,
                max_results=max_results,
            )
        except RuntimeError as e:
            err_console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)

    if not repos:
        console.print(
            Panel(
                "[yellow]No repositories found.[/yellow]\n"
                "Try broadening your search: fewer filters, lower --stars-min, or different keywords.",
                border_style="yellow",
            )
        )
        return

    # --- Analyze ---
    if analyze:
        analyzer = RepoAnalyzer(session)
        analyses = analyzer.analyze_batch(repos, deep=True)
    else:
        # Light analysis (no extra API calls)
        analyzer = RepoAnalyzer(session)
        analyses = [analyzer.analyze_repo(r, deep=False) for r in repos]

    elapsed = time.time() - start

    # --- Display ---
    print_summary_panel(len(repos), len(analyses), elapsed, query_str)
    print_results_table(analyses)

    if detail:
        console.print()
        for a in analyses:
            print_repo_detail(a)

    # --- Export ---
    if export:
        exporter = DataExporter()
        try:
            used_fmt = exporter.export(analyses, export, fmt=fmt, query_info=query_str)
            console.print(f"\n[green]Exported {len(analyses)} repos as {used_fmt.upper()} → {export}[/green]")
        except Exception as e:
            err_console.print(f"[red]Export failed:[/red] {e}")


@cli.command("token-status")
@click.option("--token", default=None, envvar="GITHUB_TOKEN", help="GitHub token")
def token_status(token):
    """Show GitHub API rate limit status for your token."""
    session = create_session(token)
    resp = gh_get(session, "/rate_limit")
    if resp.status_code != 200:
        err_console.print(f"[red]Failed to fetch rate limit: HTTP {resp.status_code}[/red]")
        raise SystemExit(1)

    data = resp.json()
    resources = data.get("resources", {})

    table = Table(title="GitHub API Rate Limits", border_style="cyan")
    table.add_column("Resource", style="bold")
    table.add_column("Limit", justify="right")
    table.add_column("Used", justify="right", style="yellow")
    table.add_column("Remaining", justify="right", style="green")
    table.add_column("Reset In", justify="right")

    import time as _time

    for resource_name, info in resources.items():
        reset_in = max(0, int(info.get("reset", 0)) - int(_time.time()))
        mins, secs = divmod(reset_in, 60)
        table.add_row(
            resource_name,
            str(info.get("limit", "?")),
            str(info.get("used", "?")),
            str(info.get("remaining", "?")),
            f"{mins}m {secs}s",
        )

    auth_status = (
        "[green]Authenticated[/green]"
        if is_authenticated(session)
        else "[yellow]Unauthenticated[/yellow]"
    )
    console.print(Panel(auth_status, title="Token Status", border_style="dim"))
    console.print(table)


@cli.command()
def languages():
    """List commonly used GitHub language names for --language filter."""
    langs = [
        "1C Enterprise", "ABAP", "ActionScript", "Ada", "Agda", "AL",
        "ANTLR", "ApacheConf", "Apex", "API Blueprint", "APL", "Apollo Guidance Computer",
        "AppleScript", "Arc", "Arduino", "ASL", "ASP.NET", "Assembly",
        "Asymptote", "ATS", "Augeas", "AutoHotkey", "AutoIt", "Awk",
        "Ballerina", "Batchfile", "Beef", "Befunge", "Berry", "BibTeX",
        "Bikeshed", "Bison", "BitBake", "Blade", "BlitzBasic", "BlitzMax",
        "Bluespec", "Boo", "Boogie", "Brainfuck", "BrightScript", "Browserslist",
        "C", "C#", "C++", "C2hs Haskell", "Cabal Config", "Cap'n Proto",
        "CartoCss", "Ceylon", "Chapel", "Charity", "Chip-8", "Chuck",
        "Cirru", "Clarion", "Classic ASP", "Clean", "Click", "CLIPS",
        "Clojure", "Closure Templates", "Cloud Firestore Security Rules",
        "CMake", "COBOL", "CoffeeScript", "ColdFusion", "Common Lisp",
        "Common Workflow Language", "Component Pascal", "Cool", "Crystal",
        "CUDA", "Cython", "D", "Dart", "DataWeave", "Dhall", "Diff",
        "Dockerfile", "Dogescript", "Dylan", "E", "eC", "ECL", "ECLiPSe",
        "Eiffel", "EJS", "Elixir", "Elm", "Emacs Lisp", "EmberScript",
        "Erlang", "F#", "F*", "Factor", "Fancy", "Fantom", "Faust", "Fennel",
        "Filebench WML", "Filterscript", "fish", "Fluent", "FLUX", "Forth",
        "Fortran", "FreeBasic", "FreeMarker", "Frege", "Futhark",
        "G-code", "Game Maker Language", "GAML", "GAMS", "GAP", "GCC Machine Description",
        "GDB", "GDScript", "GEDCOM", "Genie", "Genshi", "Gentoo Ebuild",
        "Gentoo Eclass", "Gherkin", "GLSL", "Glyph", "Glyph Bitmap Distribution Format",
        "Gnuplot", "Go", "Golo", "Gosu", "Grace", "Gradle", "Grammatical Framework",
        "GraphQL", "Groovy", "Hack", "Haml", "Handlebars", "Harbour", "Haskell",
        "Haxe", "HiveQL", "HLSL", "HolyC", "HTML", "HTTP", "Hy",
        "HyPhy", "IDL", "Idris", "IGOR Pro", "Inform 7", "Ini", "Inno Setup",
        "Io", "Ioke", "Isabelle", "J", "Jasmin", "Java", "JavaScript",
        "JCL", "Jinja", "Jsonnet", "Julia", "Jupyter Notebook", "Kaitai Struct",
        "KiCad Layout", "KiCad Legacy Layout", "KiCad Schematic", "Kit", "Kotlin",
        "KRL", "LabVIEW", "Lasso", "Latte", "Lean", "Less", "Lex",
        "LFE", "LilyPond", "Limbo", "Linker Script", "Linux Kernel Module",
        "Liquid", "Literate Agda", "Literate CoffeeScript", "Literate Haskell",
        "LiveScript", "LLVM", "Logos", "Logtalk", "LOLCODE", "LookML",
        "LoomScript", "LSL", "Lua", "M", "M4", "M4Sugar", "Macaulay2",
        "Makefile", "Mako", "Markdown", "Marko", "Mask", "Mathematica",
        "MATLAB", "Max", "MAXScript", "Mercury", "Meson", "Metal",
        "MiniD", "Mirah", "Modelica", "Modula-2", "Modula-3", "MoonScript",
        "MSBuild", "MTML", "MUF", "Mustache", "Myghty", "nanorc", "NCL",
        "Nearley", "Nemerle", "nesC", "NetLinx", "NetLinx+ERB", "NetLogo",
        "NewLisp", "Nextflow", "Nginx", "Nim", "Ninja", "Nit", "Nix",
        "NL", "Nu", "NumPy", "Nunjucks", "NWScript", "Objective-C",
        "Objective-C++", "Objective-J", "OCaml", "Odin", "Omgrofl", "ooc",
        "Opa", "OpenCL", "OpenEdge ABL", "OpenQASM", "Ox", "Oxygene",
        "Oz", "P4", "Pan", "Papyrus", "Parrot", "Pascal", "Pawn",
        "PDDL", "Perl", "PHP", "PicoLisp", "PigLatin", "Pike",
        "PLpgSQL", "PLSQL", "PogoScript", "PostScript", "PowerBuilder",
        "PowerShell", "Prisma", "Processing", "Prolog", "Promela",
        "Protocol Buffer", "Puppet", "PureBasic", "PureScript", "Python",
        "q", "Q#", "QMake", "QML", "R", "Racket", "Ragel", "Raku",
        "RAML", "Rascal", "REALbasic", "Reason", "Rebol", "Red", "Redcode",
        "Regular Expression", "Ren'Py", "RenderScript", "REXX", "Ring",
        "Riot", "RMarkdown", "RobotFramework", "Roff", "Rouge", "Ruby",
        "RUNOFF", "Rust", "Sage", "SaltStack", "Sass", "Scala", "Scaml",
        "Scheme", "Scilab", "SCSS", "sed", "Self", "ShaderLab", "Shell",
        "Shen", "Slash", "Slice", "Slim", "Smali", "Smalltalk", "Smarty",
        "Solidity", "SourcePawn", "SPARQL", "Spline Font Database", "SQF",
        "SQL", "SQLPL", "Squirrel", "Stan", "Standard ML", "Starlark",
        "Stata", "StringTemplate", "Stylus", "SubRip Text", "SugarSS",
        "SuperCollider", "Svelte", "SVG", "Swift", "SWIG", "SystemVerilog",
        "Tcl", "Tcsh", "Terra", "TeX", "Thrift", "TI Program", "TLA",
        "TOML", "TSQL", "TSX", "Turing", "Turtle", "Twig", "TXL",
        "TypeScript", "Unified Parallel C", "Unity3D Asset", "Unix Assembly",
        "Uno", "UnrealScript", "UrWeb", "V", "Vala", "VBA", "VBScript",
        "VCL", "Verilog", "VHDL", "Vim Script", "Vim Snippet", "Visual Basic .NET",
        "Volt", "Vue", "Wasm", "WebAssembly", "WebIDL", "Windows Registry Entries",
        "wisp", "Wollok", "X10", "xBase", "XC", "XQuery", "XS", "XSLT",
        "Xtend", "Yacc", "YAML", "YARA", "YASnippet", "Zap", "Zeek",
        "ZenScript", "Zephir", "Zig", "ZIL", "Zimpl",
    ]

    table = Table(title="GitHub Language Names", border_style="dim")
    table.add_column("Language", style="cyan")
    table.add_column("Language", style="cyan")
    table.add_column("Language", style="cyan")

    # 3 columns
    rows = [langs[i : i + 3] for i in range(0, len(langs), 3)]
    for row in rows:
        table.add_row(*row + [""] * (3 - len(row)))

    console.print(table)
    console.print(
        "\n[dim]Use with: ghfinder search --language Python[/dim]"
    )


if __name__ == "__main__":
    cli()
