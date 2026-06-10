"""Shared helpers for Tavily wrapper scripts in this directory.

These scripts intentionally expose only a small set of CLI arguments.
Change shared environment-loading or JSON output behavior here when you want
to affect multiple wrapper scripts at once.

This module also defines the **CLI return contract** shared by every wrapper
script, so the value a caller gets back is never script-specific guesswork:

1. Process exit code -> ``ExitCode`` (an ``IntEnum``). Every ``main()`` reports
   one of these members; callers branch on the number.
2. Emitted data -> ``ResultEnvelope`` (a ``TypedDict``). Every script writes the
   SAME self-describing envelope to ``--output`` (or stdout), with a
   ``result_kind`` discriminator that tells the caller how to read ``result``.
3. Full audit log -> ``ResponseEnvelope`` (a ``TypedDict``), always written to
   ``logs/<script>-log.json`` regardless of ``--output``.

Architecture: **functional core / imperative shell.** Each ``main()`` is a
compute step that returns a ``RunOutcome`` value (exit code + payloads + message)
and performs NO output side effects. ``finalize()`` is the single shell that
turns a ``RunOutcome`` into file writes / prints, and the ``__main__`` entry point
turns the returned code into the process exit status. This keeps the real product
of ``main()`` in its signature, so it can be tested and composed without capturing
stdout or touching the filesystem.

The enums/TypedDicts/dataclass are the authoritative source of truth; the README
tables describe the same contract for humans. Keep them in sync.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
import json
import os
import sys
from pathlib import Path
from typing import Any, TypedDict

from dotenv import find_dotenv, load_dotenv
from tavily import TavilyClient


LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"


class ExitCode(IntEnum):
    """Authoritative process exit codes for every wrapper script.

    A script's ``main()`` MUST return one of these members (callers see the
    integer value as the process exit code). The same number is mirrored into
    ``ResultEnvelope["exit_code"]`` so a consumer reading only the emitted JSON
    can still recover the outcome without inspecting the process status.
    """

    SUCCESS = 0          # Completed; the result envelope holds the data.
    RUNTIME_ERROR = 1    # Unexpected failure (network/API error, or research finished failed/cancelled).
    MISSING_API_KEY = 2  # TAVILY_API_KEY missing or empty after loading the environment.
    INVALID_API_KEY = 3  # The key was rejected by Tavily.
    EMPTY_RESULT = 4     # The call succeeded but yielded no actionable data (e.g. no URLs to extract).
    INCOMPLETE = 5       # A long-running op (research) did not reach a terminal state within the wait window.


class ResultKind(str, Enum):
    """Discriminator for ``ResultEnvelope["result"]``.

    Tells the caller how to interpret ``result`` without reading the producing
    script's source. ``str`` mixin so the value serializes as a plain string.
    """

    SEARCH_RESULTS = "search_results"      # list[dict]: Tavily search result objects.
    EXTRACT_RESULTS = "extract_results"    # list[dict]: Tavily extract result objects.
    CRAWL_RESULTS = "crawl_results"        # list[dict]: Tavily crawl result objects.
    SITE_PAGES = "site_pages"              # list[dict]: page-title records (see map_site_titles.PageTitleResult).
    RESEARCH_REPORT = "research_report"    # str | dict: research report content (markdown) or the raw final response.


class EnvironmentInfo(TypedDict):
    """Environment provenance recorded in every ``ResponseEnvelope``."""

    dotenv_loaded: bool
    dotenv_path: str | None
    api_key_present: bool


class ResponseEnvelope(TypedDict):
    """Full audit record written to ``logs/<script>-log.json`` on every run.

    This is the verbose, reproduce-everything view. The slim public output is
    ``ResultEnvelope`` instead.
    """

    script: str
    request: dict[str, Any]
    environment: EnvironmentInfo
    response: dict[str, Any]


class ResultEnvelope(TypedDict):
    """Self-describing payload written to ``--output`` (or stdout).

    Every wrapper script emits this exact top-level shape. ``result_kind`` is the
    discriminator; ``result`` holds the data whose shape it names. ``exit_code``
    mirrors the process exit code so the file alone is enough to know the outcome.
    """

    script: str
    result_kind: str   # one of ResultKind's values
    exit_code: int     # one of ExitCode's values
    result: Any        # shape determined by result_kind


@dataclass(slots=True)
class RunOutcome:
    """The complete, side-effect-free return value of a script's ``main()``.

    This is the contract between the functional core (``main()``) and the
    imperative shell (``finalize()``): ``main()`` builds and returns one of these
    without writing anything, then ``finalize()`` performs all the I/O it implies.

    - ``exit_code``: the process exit code to report (always present).
    - ``log`` + ``result_kind`` + ``result``: the data to emit. All three are set
      on a run that reached the request stage; all three stay ``None`` on an early
      failure (e.g. missing credentials) where there is nothing to emit.
    - ``output_path``: where ``result`` should be written, mirroring ``--output``.
    - ``message``: a single stderr line to print, if any (errors, empty/incomplete
      notices). ``None`` means stay silent on stderr.
    """

    exit_code: ExitCode
    output_path: Path | None = None
    log: ResponseEnvelope | None = None
    result_kind: ResultKind | None = None
    result: Any = None
    message: str | None = None


def finalize(outcome: RunOutcome) -> ExitCode:
    """Imperative shell: perform every output side effect a run implies.

    Writes the full log + result envelope (only when there is data to emit),
    prints any stderr ``message``, and returns ``outcome.exit_code`` so the entry
    point can do ``raise SystemExit(finalize(main()))``. This is the ONLY place
    wrapper scripts touch stdout/stderr/the filesystem for their result.
    """
    if outcome.log is not None and outcome.result_kind is not None:
        emit_payload(
            outcome.log,
            outcome.output_path,
            result_kind=outcome.result_kind,
            result=outcome.result,
            exit_code=outcome.exit_code,
        )
    if outcome.message:
        print(outcome.message, file=sys.stderr)
    return outcome.exit_code


def load_environment() -> str | None:
    dotenv_path = find_dotenv(filename=".env", usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)
        return dotenv_path

    load_dotenv(override=False)
    return None


def get_normalized_api_key() -> str:
    return os.getenv("TAVILY_API_KEY", "").strip()


def get_missing_api_key_message(dotenv_path: str | None) -> str:
    if dotenv_path:
        return (
            "TAVILY_API_KEY is empty after loading the final environment. "
            "Check the value in the loaded .env file and remove blank or "
            "whitespace-only assignments."
        )

    return (
        "TAVILY_API_KEY is empty after loading the final environment. "
        "Add a non-empty value to a .env file or set it in the environment."
    )


def create_tavily_client() -> tuple[TavilyClient, str | None]:
    dotenv_path = load_environment()
    api_key = get_normalized_api_key()
    if not api_key:
        raise ValueError(get_missing_api_key_message(dotenv_path))
    return TavilyClient(api_key=api_key), dotenv_path


def build_response_payload(
    *,
    script_name: str,
    request: dict[str, Any],
    response: dict[str, Any],
    dotenv_path: str | None,
) -> ResponseEnvelope:
    return {
        "script": script_name,
        "request": request,
        "environment": {
            "dotenv_loaded": bool(dotenv_path),
            "dotenv_path": dotenv_path,
            "api_key_present": bool(get_normalized_api_key()),
        },
        "response": response,
    }


def build_result_envelope(
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode,
) -> ResultEnvelope:
    """Assemble the self-describing public envelope emitted to --output/stdout."""
    return {
        "script": script_name,
        "result_kind": result_kind.value,
        "exit_code": int(exit_code),
        "result": result,
    }


def render_json(payload: Any, *, pretty: bool = True) -> str:
    indent = 2 if pretty else None
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def build_log_output_path(output_path: Path | None, *, script_name: str) -> Path:
    file_name = output_path.name if output_path else f"{Path(script_name).stem}.json"
    base_path = Path(file_name)
    suffix = base_path.suffix or ".json"
    return LOG_DIRECTORY / f"{base_path.stem}-log{suffix}"


def emit_payload(
    payload: ResponseEnvelope,
    output_path: Path | None,
    *,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode = ExitCode.SUCCESS,
    pretty: bool = True,
) -> None:
    """Write the two return-contract artifacts of a run.

    Always: the full ``ResponseEnvelope`` to ``logs/<script>-log.json``.
    Public: a ``ResultEnvelope`` (``script`` / ``result_kind`` / ``exit_code`` /
    ``result``) to ``output_path`` if given, otherwise to stdout. ``result_kind``
    and ``exit_code`` make the emitted JSON self-describing, so the caller never
    has to infer the shape or outcome from the producing script.
    """
    result_envelope = build_result_envelope(
        script_name=payload.get("script", "payload"),
        result_kind=result_kind,
        result=result,
        exit_code=exit_code,
    )
    log_path = build_log_output_path(output_path, script_name=payload.get("script", "payload"))
    write_output(log_path, payload, pretty=pretty)

    if output_path:
        write_output(output_path, result_envelope, pretty=pretty)
        print(f"Wrote result envelope to {output_path}")
        print(f"Wrote full log to {log_path}")
        return

    print(render_json(result_envelope, pretty=pretty), end="")
    print(f"Wrote full log to {log_path}", file=sys.stderr)


def dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    normalized_values: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def write_output(output_path: Path, payload: Any, *, pretty: bool = True) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_json(payload, pretty=pretty), encoding="utf-8")