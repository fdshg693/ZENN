r"""Run Tavily research with a small, opinionated CLI.

This wrapper keeps model selection and polling behavior inside the file so
callers only need to provide a research prompt, an optional detail preset, and
an optional JSON output path. Adjust the preset values below when you want
different Tavily research behavior.

PowerShell example:
    python .\.claude\skills\use-tavily\src\research_topic.py "Microsoft Fabric の概要を整理してください" --output temp\web\research_fabric_overview.json

bash example:
    python ./.claude/skills/use-tavily/src/research_topic.py "Microsoft Fabric の概要を整理してください" --output temp/web/research_fabric_overview.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from tavily.errors import InvalidAPIKeyError

from tavily_common import build_response_payload, create_tavily_client, emit_payload


DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "model": "mini",
        "poll_interval_seconds": 5.0,
        "max_wait_seconds": 120.0,
    },
    "balanced": {
        "model": "auto",
        "poll_interval_seconds": 5.0,
        "max_wait_seconds": 180.0,
    },
    "max": {
        "model": "pro",
        "poll_interval_seconds": 10.0,
        "max_wait_seconds": 300.0,
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_CITATION_FORMAT = "numbered"
REQUEST_TIMEOUT_SECONDS = 60.0
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Tavily research with minimal arguments and wait for completion."
    )
    parser.add_argument(
        "input",
        help="Research prompt or question to investigate.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level research preset. Model and polling behavior are predefined.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON response.",
    )
    return parser.parse_args()


def wait_for_research_completion(client: Any, request_id: str, *, detail: str) -> tuple[dict[str, Any], bool, float]:
    preset = DETAIL_PRESETS[detail]
    deadline = time.monotonic() + preset["max_wait_seconds"]
    last_response = client.get_research(request_id)

    while last_response.get("status") not in TERMINAL_STATUSES:
        if time.monotonic() >= deadline:
            return last_response, False, preset["max_wait_seconds"]
        time.sleep(preset["poll_interval_seconds"])
        last_response = client.get_research(request_id)

    elapsed_seconds = preset["max_wait_seconds"] - max(deadline - time.monotonic(), 0.0)
    return last_response, True, elapsed_seconds

def main() -> int:
    args = parse_args()
    preset = DETAIL_PRESETS[args.detail]

    try:
        client, dotenv_path = create_tavily_client()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        initial_response = client.research(
            input=args.input,
            model=preset["model"],
            citation_format=DEFAULT_CITATION_FORMAT,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        request_id = initial_response.get("request_id")
        if not request_id:
            raise RuntimeError("Research response did not include request_id.")

        final_response, completed, elapsed_seconds = wait_for_research_completion(
            client,
            request_id,
            detail=args.detail,
        )
    except InvalidAPIKeyError as exc:
        print(f"Invalid Tavily API key: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Research failed: {exc}", file=sys.stderr)
        return 1

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "input": args.input,
            "detail": args.detail,
            "model": preset["model"],
            "citation_format": DEFAULT_CITATION_FORMAT,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "poll_interval_seconds": preset["poll_interval_seconds"],
            "max_wait_seconds": preset["max_wait_seconds"],
        },
        response={
            "initial": initial_response,
            "final": final_response,
            "completed_within_wait": completed,
            "elapsed_seconds": round(elapsed_seconds, 2),
        },
        dotenv_path=dotenv_path,
    )

    emit_payload(payload, args.output, public_payload=final_response.get("content") or final_response)

    final_status = final_response.get("status")
    if not completed:
        print(
            "Research did not finish within the preset wait window. Re-run later or increase the preset.",
            file=sys.stderr,
        )
        return 4
    if final_status != "completed":
        print(f"Research finished with status: {final_status}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())