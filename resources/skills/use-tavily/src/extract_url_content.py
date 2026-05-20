r"""Extract content from one or more URLs with a small, opinionated CLI.

This wrapper keeps Tavily-specific tuning inside the file so callers only need
to provide URLs, an optional query, and a high-level detail preset.
Adjust the preset values below when you want different Tavily behavior.
Other scripts in this directory can also import the reusable extraction helper.

PowerShell example:
    python .\.claude\skills\use-tavily\src\extract_url_content.py https://learn.microsoft.com/azure/api-management/api-management-policies --query "policy capabilities" --output temp\web\extract_apim_policies.json

bash example:
    python ./.claude/skills/use-tavily/src/extract_url_content.py https://learn.microsoft.com/azure/api-management/api-management-policies --query "policy capabilities" --output temp/web/extract_apim_policies.json
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping

from tavily.errors import InvalidAPIKeyError

from tavily_common import (
    build_response_payload,
    create_tavily_client,
    dedupe_preserve_order,
    emit_payload,
)


DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "extract_depth": "basic",
        "query_chunks_per_source": 2,
    },
    "balanced": {
        "extract_depth": "advanced",
        "query_chunks_per_source": 3,
    },
    "max": {
        "extract_depth": "advanced",
        "query_chunks_per_source": 5,
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_OUTPUT_FORMAT = "markdown"
REQUEST_TIMEOUT_SECONDS = 60.0
INCLUDE_IMAGES = False
INCLUDE_FAVICON = False
INCLUDE_USAGE = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract content from URLs with Tavily using minimal arguments."
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="One or more URLs to extract content from.",
    )
    parser.add_argument(
        "--query",
        help="Optional relevance query for focused extraction.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level extraction preset. Tavily-specific values are already defined.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON response.",
    )
    return parser.parse_args(argv)


def resolve_extract_options(detail: str, *, has_query: bool) -> dict[str, Any]:
    preset = DETAIL_PRESETS[detail]
    chunks_per_source = preset["query_chunks_per_source"] if has_query else None
    return {
        "extract_depth": preset["extract_depth"],
        "chunks_per_source": chunks_per_source,
        "format": DEFAULT_OUTPUT_FORMAT,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "include_images": INCLUDE_IMAGES,
        "include_favicon": INCLUDE_FAVICON,
        "include_usage": INCLUDE_USAGE,
    }


def run_extract_request(
    client: Any,
    *,
    urls: Sequence[str],
    query: str | None,
    extract_options: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_urls = dedupe_preserve_order(urls)
    response = client.extract(
        urls=normalized_urls,
        query=query,
        **dict(extract_options),
    )
    return {
        "urls": normalized_urls,
        "options": dict(extract_options),
        "response": response,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    extract_options = resolve_extract_options(args.detail, has_query=bool(args.query))

    try:
        client, dotenv_path = create_tavily_client()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        extraction = run_extract_request(
            client,
            urls=args.urls,
            query=args.query,
            extract_options=extract_options,
        )
    except InvalidAPIKeyError as exc:
        print(f"Invalid Tavily API key: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "urls": extraction["urls"],
            "query": args.query,
            "detail": args.detail,
            **extraction["options"],
        },
        response=extraction["response"],
        dotenv_path=dotenv_path,
    )

    emit_payload(payload, args.output, public_payload=extraction["response"].get("results") or [])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())