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
import time
from pathlib import Path
from typing import Any

from tavily.errors import InvalidAPIKeyError

from tavily_common import (
    ExitCode,
    ResultKind,
    RunOutcome,
    build_response_payload,
    create_tavily_client,
    finalize,
)


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

def resolve_exit_code(*, completed: bool, final_status: str | None) -> ExitCode:
    """Map a finished research run to its exit code (see ``ExitCode``).

    ``INCOMPLETE`` (did not reach a terminal state within the wait window) is
    deliberately distinct from ``RUNTIME_ERROR`` (reached a terminal but
    non-``completed`` status, i.e. failed/cancelled).
    """
    if not completed:
        return ExitCode.INCOMPLETE
    if final_status != "completed":
        return ExitCode.RUNTIME_ERROR
    return ExitCode.SUCCESS


def describe_outcome(exit_code: ExitCode, final_status: str | None) -> str | None:
    """The stderr line for a finished research run, or ``None`` to stay silent."""
    if exit_code is ExitCode.INCOMPLETE:
        return "Research did not finish within the preset wait window. Re-run later or increase the preset."
    if exit_code is ExitCode.RUNTIME_ERROR:
        return f"Research finished with status: {final_status}"
    return None


def main() -> RunOutcome:
    """Run research, wait for completion, and return a ``RunOutcome`` (no I/O;
    ``finalize()`` emits it).

    The success ``result`` is the report content (markdown) when available, else
    the raw final response, carried as ``RESEARCH_REPORT``. Returns ``SUCCESS`` when
    the run completed; ``INCOMPLETE`` if it did not finish within the preset wait
    window; ``RUNTIME_ERROR`` on failure or a failed/cancelled terminal status;
    ``MISSING_API_KEY`` / ``INVALID_API_KEY`` on credential problems.
    """
    args = parse_args()
    preset = DETAIL_PRESETS[args.detail]

    try:
        client, dotenv_path = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

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
        return RunOutcome(exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}")
    except Exception as exc:
        return RunOutcome(exit_code=ExitCode.RUNTIME_ERROR, message=f"Research failed: {exc}")

    final_status = final_response.get("status")
    exit_code = resolve_exit_code(completed=completed, final_status=final_status)

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

    return RunOutcome(
        exit_code=exit_code,
        output_path=args.output,
        log=payload,
        result_kind=ResultKind.RESEARCH_REPORT,
        result=final_response.get("content") or final_response,
        message=describe_outcome(exit_code, final_status),
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))