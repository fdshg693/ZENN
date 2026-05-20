r"""Search with Tavily and then extract content from the discovered URLs.

This script composes the reusable search helper from search_topic.py and the
reusable extraction helper from extract_url_content.py. Callers only provide a
query, an optional detail preset, and optional domain filters. The preset for
this pipeline is resolved inside this file into concrete Tavily arguments
before the helper functions are called.

PowerShell example:
    python .\.claude\skills\use-tavily\src\search_extract_topic.py "Azure API Management policy expressions limitations" --output temp\web\search_extract_apim_policy_limitations.json

bash example:
    python ./.claude/skills/use-tavily/src/search_extract_topic.py "Azure API Management policy expressions limitations" --output temp/web/search_extract_apim_policy_limitations.json
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tavily.errors import InvalidAPIKeyError

from extract_url_content import run_extract_request
from search_topic import run_search_request
from tavily_common import build_response_payload, create_tavily_client, dedupe_preserve_order, emit_payload


MAX_EXTRACT_URLS = 20
DETAIL_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "quick": {
        "search": {
            "search_depth": "fast",
            "topic": "general",
            "max_results": 5,
            "chunks_per_source": 2,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
            "timeout": 60.0,
        },
        "extract": {
            "extract_depth": "basic",
            "chunks_per_source": 2,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
    "balanced": {
        "search": {
            "search_depth": "advanced",
            "topic": "general",
            "max_results": 5,
            "chunks_per_source": 3,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
            "timeout": 60.0,
        },
        "extract": {
            "extract_depth": "advanced",
            "chunks_per_source": 3,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
    "max": {
        "search": {
            "search_depth": "advanced",
            "topic": "general",
            "max_results": 8,
            "chunks_per_source": 5,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
            "timeout": 60.0,
        },
        "extract": {
            "extract_depth": "advanced",
            "chunks_per_source": 5,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
}
DEFAULT_DETAIL = "balanced"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search with Tavily and extract content from the resulting URLs."
    )
    parser.add_argument(
        "query",
        help="Search query to run, and also the relevance query for extraction.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level preset shared by the search and extraction steps.",
    )
    parser.add_argument(
        "--include-domain",
        action="append",
        default=[],
        help="Optional domain to include. Repeat to allow multiple domains.",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="Optional domain to exclude. Repeat to exclude multiple domains.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON response.",
    )
    return parser.parse_args(argv)


def resolve_pipeline_options(detail: str, *, has_query: bool) -> dict[str, dict[str, Any]]:
    preset = DETAIL_PRESETS[detail]
    extract_options = dict(preset["extract"])
    if not has_query:
        extract_options["chunks_per_source"] = None
    return {
        "search": dict(preset["search"]),
        "extract": extract_options,
    }


def select_urls(search_response: dict[str, Any]) -> list[str]:
    results = search_response.get("results") or []
    urls = [result.get("url", "") for result in results if isinstance(result, dict)]
    return dedupe_preserve_order(urls)[:MAX_EXTRACT_URLS]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    pipeline_options = resolve_pipeline_options(args.detail, has_query=bool(args.query))

    try:
        client, dotenv_path = create_tavily_client()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        search_run = run_search_request(
            client,
            query=args.query,
            search_options=pipeline_options["search"],
            include_domains=args.include_domain,
            exclude_domains=args.exclude_domain,
        )
        selected_urls = select_urls(search_run["response"])
        extraction = None
        if selected_urls:
            extraction = run_extract_request(
                client,
                urls=selected_urls,
                query=args.query,
                extract_options=pipeline_options["extract"],
            )
    except InvalidAPIKeyError as exc:
        print(f"Invalid Tavily API key: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Search and extract failed: {exc}", file=sys.stderr)
        return 1

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "query": search_run["query"],
            "detail": args.detail,
            "include_domains": search_run["include_domains"],
            "exclude_domains": search_run["exclude_domains"],
            "selected_url_limit": MAX_EXTRACT_URLS,
            "search": pipeline_options["search"],
            "extract": pipeline_options["extract"] if extraction else None,
        },
        response={
            "search": search_run["response"],
            "selected_urls": selected_urls,
            "extract": extraction["response"] if extraction else None,
        },
        dotenv_path=dotenv_path,
    )

    emit_payload(
        payload,
        args.output,
        public_payload=(extraction["response"].get("results") or []) if extraction else [],
    )

    if not selected_urls:
        print("Search returned no URLs to extract.", file=sys.stderr)
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())