r"""Single entry point that dispatches to the Tavily wrapper scripts.

Installed as the ``tav`` console command (see ``../pyproject.toml``), so the long
``python .\.claude\skills\use-tavily\src\<script>.py ...`` invocations collapse to
short subcommands:

    tav search "Microsoft Fabric overview" --detail balanced --topic fabric_overview
    tav extract https://learn.microsoft.com/azure/api-management/ --query "..." --topic apim
    tav crawl  https://learn.microsoft.com/azure/api-management/ --query "..." --topic apim

This is a thin router only: it maps a subcommand name to one wrapper module and
forwards the remaining arguments to that module's ``main(argv)``, then hands the
returned ``RunOutcome`` to the shared ``finalize()`` shell — the per-script CLI
arguments, presets and output contract are unchanged. Run ``tav`` (or ``tav
--help``) to list subcommands, and ``tav <subcommand> --help`` for one script's
own arguments.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence

from tavily_common import ExitCode, finalize


# subcommand -> (wrapper module name, one-line summary). The module names match
# the files in this directory; each exposes ``main(argv) -> RunOutcome``.
SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "search":         ("search_topic",            "keyword -> related URLs + snippets"),
    "search-extract": ("search_extract_topic",    "keyword -> URLs, then extract their content"),
    "research":       ("research_topic",          "hand a question to Tavily research, wait for the report"),
    "extract":        ("extract_url_content",     "known URL(s) -> page content"),
    "map":            ("map_site_titles",         "site root -> URL list with titles"),
    "map-extract":    ("map_extract_site_content","map a site, then extract chosen URLs"),
    "crawl":          ("crawl_site_content",      "crawl a site -> related page content"),
}


def render_usage() -> str:
    width = max(len(name) for name in SUBCOMMANDS)
    lines = ["Usage: tav <subcommand> [args...]", "", "Subcommands:"]
    lines += [f"  {name.ljust(width)}  {summary}" for name, (_m, summary) in SUBCOMMANDS.items()]
    lines += ["", "Run 'tav <subcommand> --help' for that subcommand's own arguments."]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help"):
        print(render_usage())
        return int(ExitCode.SUCCESS)

    name = args[0]
    entry = SUBCOMMANDS.get(name)
    if entry is None:
        print(f"Unknown subcommand: {name}\n", file=sys.stderr)
        print(render_usage(), file=sys.stderr)
        return int(ExitCode.RUNTIME_ERROR)

    module = importlib.import_module(entry[0])
    return int(finalize(module.main(args[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
