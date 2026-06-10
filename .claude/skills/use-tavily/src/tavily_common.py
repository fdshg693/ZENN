"""Shared helpers for Tavily wrapper scripts in this directory.

These scripts intentionally expose only a small set of CLI arguments.
Change shared environment-loading or JSON output behavior here when you want
to affect multiple wrapper scripts at once.

This module also defines the **CLI return contract** shared by every wrapper
script, so the value a caller gets back is never script-specific guesswork:

1. Process exit code -> ``ExitCode`` (an ``IntEnum``). Every ``main()`` reports
   one of these members; callers branch on the number.
2. Emitted data -> ``ResultEnvelope`` (a ``TypedDict``). Every script emits the
   SAME self-describing envelope, with a ``result_kind`` discriminator that tells
   the caller how to read ``result``. Where it lands depends on ``--topic`` (see
   ``OutputChannel`` / ``emit_payload``): stdout when absent, files under the
   topic folder when present.
3. Full audit log -> ``ResponseEnvelope`` (a ``TypedDict``), written to
   ``logs/<script>-log.json`` whenever ``should_write_log()`` (``TAVILY_WRITE_LOG``).
4. Output destination -> ``OutputChannel`` (an ``Enum``). Fixes *where* each of
   the above goes: stdout carries the machine-readable result and nothing else,
   every human/AI notice is a stderr ``DIAGNOSTIC``, and durable records are
   files. ``emit()`` is the single sink that routes by this enum, so a caller
   can parse stdout verbatim and read stderr as pure diagnostics.

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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum, IntEnum
import json
import os
import sys
from pathlib import Path
from typing import Any, TypedDict

from dotenv import find_dotenv, load_dotenv
from tavily import TavilyClient

from title_fetch import DEFAULT_TITLE_OPTIONS, build_title_from_url, fetch_page_title


LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"

# Output-layout settings, read from the environment (see README "設定とパス解決").
OUTPUT_DIR_ENV = "TAVILY_OUTPUT_DIR"
WRITE_LOG_ENV = "TAVILY_WRITE_LOG"
DEFAULT_OUTPUT_DIR = "temp/web"
INDEX_FILE_NAME = "index.json"


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
    The concrete element type each member names is defined below as a
    ``TypedDict`` (e.g. ``SEARCH_RESULTS`` -> ``list[SearchResultItem]``).
    """

    SEARCH_RESULTS = "search_results"      # list[SearchResultItem]: Tavily search result objects.
    EXTRACT_RESULTS = "extract_results"    # list[ExtractResultItem]: Tavily extract result objects.
    CRAWL_RESULTS = "crawl_results"        # list[CrawlResultItem]: Tavily crawl result objects.
    SITE_PAGES = "site_pages"              # list[SitePageItem]: page-title records (see PageTitleResult / SitePageItem).
    RESEARCH_REPORT = "research_report"    # str (markdown report) on success, else the raw final response dict.


# ---------------------------------------------------------------------------
# Tavily per-item result types — EMPIRICALLY pinned, not copied from the docs.
#
# Each TypedDict names the concrete shape of one object inside the ``result``
# list that ``ResultKind`` discriminates, as observed from the LIVE Tavily API
# (tavily-python 0.7.x) when called with THIS skill's fixed wrapper flags
# (``include_raw_content`` / ``include_images`` / ``include_favicon`` all False,
# ``format="markdown"``). They are deliberately narrower than "some dict":
# downstream code may rely on every key declared here. Real captured responses
# live in ``tests/fixtures/`` and ``tests/test_result_types.py`` keeps these
# definitions honest against them.
#
# Where the published reference disagreed with reality, reality wins (verified
# against live responses on 2026-06-10):
#   - search items ALWAYS carry a ``raw_content`` key — value ``None`` under our
#     flags (the docs imply the key only appears with ``include_raw_content``).
#   - extract items carry an UNDOCUMENTED ``title``; ``images`` is a (usually
#     empty) list even with ``include_images=False``.
#   - crawl items carry ONLY ``url`` + ``raw_content`` (nullable) under our flags
#     — no ``title`` / ``images`` / ``favicon``.
#   - a completed research response's ``sources[]`` are ``{url, title, favicon}``
#     (the docs said ``{url, title, citation}``).
# ---------------------------------------------------------------------------


class SearchResultItem(TypedDict):
    """One object in ``search_topic.py`` results (``ResultKind.SEARCH_RESULTS``)."""

    title: str
    url: str
    content: str          # NLP summary or reranked chunks, depending on search_depth
    score: float          # semantic relevance, 0-1
    raw_content: str | None  # None under our flags; str only if include_raw_content is enabled


class ExtractResultItem(TypedDict):
    """One object in extract results (``ResultKind.EXTRACT_RESULTS``).

    Shared by ``extract_url_content`` / ``search_extract_topic`` /
    ``map_extract_site_content`` (they all emit Tavily extract objects).
    """

    url: str
    title: str         # present in practice, though absent from the published Response Fields
    raw_content: str   # full page content, or query-reranked chunks joined by " [...] "
    images: list[str]  # empty list under our flags (include_images=False)


class ExtractFailedItem(TypedDict):
    """One object in an extract response's ``failed_results``.

    Failures are surfaced as a non-success ``ExitCode`` and the details are
    discarded downstream, so this is typed only lightly.
    """

    url: str
    error: str


class CrawlResultItem(TypedDict):
    """One object in ``crawl_site_content.py`` results (``ResultKind.CRAWL_RESULTS``)."""

    url: str
    raw_content: str | None  # None when the crawled page yielded no extractable content


class SitePageItem(TypedDict):
    """One object in ``map_site_titles.py`` results (``ResultKind.SITE_PAGES``).

    Built locally from ``PageTitleResult.as_dict()`` (NOT a raw Tavily object),
    so this shape is fully under our control. The underlying ``map`` call's own
    ``results`` is a ``list[str]`` of URLs, consumed internally to produce these
    records. Mirror this with ``map_site_titles.PageTitleResult``.
    """

    url: str
    title: str
    short_title: str | None
    title_source: str        # "html" | "url_fallback"
    final_url: str | None
    content_type: str | None
    status_code: int | None
    error: str | None


class ResearchSource(TypedDict):
    """One object in a completed research response's ``sources`` list."""

    url: str
    title: str
    favicon: str


class CompletedResearchResponse(TypedDict):
    """Shape of a COMPLETED ``get_research`` response.

    ``research_topic.py`` emits ``content`` (a ``str``) as its
    ``RESEARCH_REPORT`` result on success, falling back to this whole dict on a
    non-completed terminal status. ``status`` is ``"completed"`` here.
    """

    status: str
    content: str
    sources: list[ResearchSource]
    created_at: str
    response_time: float
    request_id: str


class OutputChannel(str, Enum):
    """Authoritative set of destinations a run may write to (the 4th contract).

    Alongside ``ExitCode`` (the outcome), ``ResultEnvelope`` (the data) and
    ``ResponseEnvelope`` (the record), this enum fixes *where* each kind of
    output goes, so a caller never has to guess which stream carries data and
    which carries noise. Every byte this module emits passes through ``emit()``
    tagged with one of these members, and that is the ONLY place output happens.

    The discipline these members encode:

    - stdout carries the machine-readable result and NOTHING else
      (``RESULT_STDOUT``), so a caller can parse stdout verbatim.
    - Every human/AI-facing notice is a ``DIAGNOSTIC`` on stderr; it is never
      structured and never lands on stdout.
    - Durable records are files: the public envelope (``RESULT_FILE``) and the
      full audit log (``AUDIT_LOG``).
    """

    RESULT_STDOUT = "result_stdout"   # ResultEnvelope JSON -> stdout (only when --topic is absent).
    RESULT_FILE = "result_file"       # ResultEnvelope / index JSON -> a file in the topic folder.
    AUDIT_LOG = "audit_log"           # ResponseEnvelope JSON -> logs/<script>-log.json (when TAVILY_WRITE_LOG).
    DIAGNOSTIC = "diagnostic"         # one human/AI-facing line -> stderr (never stdout, never structured).


class EnvironmentInfo(TypedDict):
    """Environment provenance recorded in every ``ResponseEnvelope``."""

    dotenv_loaded: bool
    dotenv_path: str | None
    api_key_present: bool


class ResponseEnvelope(TypedDict):
    """Full audit record written to ``logs/<script>-log.json`` (when enabled).

    Written whenever ``should_write_log()`` is true (``TAVILY_WRITE_LOG``, default
    on). This is the verbose, reproduce-everything view. The slim public output is
    ``ResultEnvelope`` instead.
    """

    script: str
    request: dict[str, Any]
    environment: EnvironmentInfo
    response: dict[str, Any]


class ResultEnvelope(TypedDict):
    """Self-describing payload emitted to stdout or a topic-folder file.

    Every wrapper script emits this exact top-level shape. ``result_kind`` is the
    discriminator; ``result`` holds the data whose shape it names. ``exit_code``
    mirrors the process exit code so the file alone is enough to know the outcome.
    In the split layout, each per-URL file is one of these with ``result`` set to
    a single content item rather than a list.
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
    - ``topic``: the ``--topic`` value. When set, ``finalize()`` writes the result
      into ``<TAVILY_OUTPUT_DIR>/<topic>/`` using the layout for ``result_kind``.
      When ``None``, the single ``ResultEnvelope`` goes to stdout (pipe use).
    - ``message``: a single stderr line to print, if any (errors, empty/incomplete
      notices). ``None`` means stay silent on stderr.
    """

    exit_code: ExitCode
    topic: str | None = None
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
            topic=outcome.topic,
            result_kind=outcome.result_kind,
            result=outcome.result,
            exit_code=outcome.exit_code,
        )
    if outcome.message:
        emit(OutputChannel.DIAGNOSTIC, outcome.message)
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


def get_output_dir() -> Path:
    """Base directory for ``--topic`` output, from ``TAVILY_OUTPUT_DIR``.

    Resolution base (IMPORTANT — this is the source of truth for the contract):

    - An **absolute** ``TAVILY_OUTPUT_DIR`` is used verbatim.
    - A **relative** one (including the ``temp/web`` default) is resolved against
      the **current working directory** at invocation — NOT the .env location and
      NOT this file's directory. So output lands under ``<cwd>/<value>/<topic>/``.
      Run the wrapper scripts / ``tav`` from the repo root to get the intended
      ``./temp/web/<topic>/`` (this matches the old ``--output temp/web/...``
      behavior, which was likewise cwd-relative).

    Falls back to ``temp/web`` (the historical naming convention) when unset or
    blank.
    """
    value = os.getenv(OUTPUT_DIR_ENV, "").strip()
    return Path(value or DEFAULT_OUTPUT_DIR)


def should_write_log() -> bool:
    """Whether to write ``logs/<script>-log.json``, from ``TAVILY_WRITE_LOG``.

    Default (unset) is ``True`` — the historical always-on behavior. Values
    ``false`` / ``0`` / ``no`` / ``off`` / empty (case-insensitive) suppress it.
    """
    raw = os.getenv(WRITE_LOG_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"", "false", "0", "no", "off"}


def resolve_output_target(topic: str, *, output_dir: Path | None = None) -> Path:
    """Resolve the topic folder ``<TAVILY_OUTPUT_DIR>/<topic>/`` for ``--topic``.

    ``topic`` is used as a single folder name; any stray path separators are
    flattened to ``_`` so it can never escape the output directory.
    """
    base = output_dir if output_dir is not None else get_output_dir()
    safe_topic = topic.strip().replace("\\", "_").replace("/", "_") or "topic"
    return base / safe_topic


def output_shape_for(result_kind: ResultKind) -> str:
    """Classify a ``result_kind`` into one of the three output layouts.

    - ``"aggregate"``: one file holding the whole url+title list (no page content).
    - ``"split"``: one file per URL plus an ``index.json`` (page content present).
    - ``"single"``: one file for a single indivisible artifact (research report).
    """
    if result_kind in (ResultKind.SEARCH_RESULTS, ResultKind.SITE_PAGES):
        return "aggregate"
    if result_kind in (ResultKind.EXTRACT_RESULTS, ResultKind.CRAWL_RESULTS):
        return "split"
    return "single"


def layout_filename_for(result_kind: ResultKind) -> str:
    """File name used by the aggregate / single layouts (command-named)."""
    return {
        ResultKind.SEARCH_RESULTS: "search.json",
        ResultKind.SITE_PAGES: "map.json",
        ResultKind.RESEARCH_REPORT: "research.json",
    }.get(result_kind, f"{result_kind.value}.json")


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
    """Assemble the self-describing public envelope emitted to a file or stdout."""
    return {
        "script": script_name,
        "result_kind": result_kind.value,
        "exit_code": int(exit_code),
        "result": result,
    }


def render_json(payload: Any, *, pretty: bool = True) -> str:
    indent = 2 if pretty else None
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def build_log_output_path(*, script_name: str) -> Path:
    return LOG_DIRECTORY / f"{Path(script_name).stem}-log.json"


def emit(channel: OutputChannel, payload: Any, *, path: Path | None = None, pretty: bool = True) -> None:
    """The single sink for every stdout / stderr / file write in this module.

    Routing is keyed by ``channel`` (see ``OutputChannel``) so the output
    contract lives in one place instead of being scattered across ``print``
    calls. The file channels (``RESULT_FILE`` / ``AUDIT_LOG``) require ``path``;
    the stream channels ignore it. Keeping this the ONLY place output happens is
    what lets ``OutputChannel`` actually govern where bytes go.
    """
    if channel is OutputChannel.DIAGNOSTIC:
        print(payload, file=sys.stderr)
        return
    if channel is OutputChannel.RESULT_STDOUT:
        print(render_json(payload, pretty=pretty), end="")
        return
    if path is None:
        raise ValueError(f"{channel.value} requires a destination path")
    write_output(path, payload, pretty=pretty)


def emit_payload(
    payload: ResponseEnvelope,
    *,
    topic: str | None,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode = ExitCode.SUCCESS,
    pretty: bool = True,
) -> None:
    """Emit a run's record artifacts under the topic layout, routed through ``emit()``.

    Audit log: the full ``ResponseEnvelope`` -> ``logs/<script>-log.json``
    (``AUDIT_LOG``), only when ``should_write_log()`` is true.

    Result, by ``topic``:

    - ``topic is None``: a single ``ResultEnvelope`` -> stdout (``RESULT_STDOUT``),
      preserving the pipe contract for callers that read ``result`` off stdout.
    - ``topic`` set: written into ``<TAVILY_OUTPUT_DIR>/<topic>/`` using the layout
      that ``output_shape_for(result_kind)`` selects — aggregate (one file), split
      (per-URL files + ``index.json``), or single (one file).

    ``result_kind`` and ``exit_code`` make every emitted ``ResultEnvelope``
    self-describing. Every accompanying notice is a ``DIAGNOSTIC`` on stderr.
    """
    script_name = payload.get("script", "payload")

    if should_write_log():
        log_path = build_log_output_path(script_name=script_name)
        emit(OutputChannel.AUDIT_LOG, payload, path=log_path, pretty=pretty)
        emit(OutputChannel.DIAGNOSTIC, f"Wrote full log to {log_path}")

    if topic is None:
        result_envelope = build_result_envelope(
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            exit_code=exit_code,
        )
        emit(OutputChannel.RESULT_STDOUT, result_envelope, pretty=pretty)
        return

    target_dir = resolve_output_target(topic)
    shape = output_shape_for(result_kind)
    if shape == "split":
        write_split_results(
            target_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            exit_code=exit_code,
            topic=topic,
            pretty=pretty,
        )
    else:
        # aggregate and single both write one command-named ResultEnvelope file.
        write_single_file_result(
            target_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            exit_code=exit_code,
            pretty=pretty,
        )


def write_single_file_result(
    target_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode,
    pretty: bool = True,
) -> None:
    """Write one command-named ``ResultEnvelope`` file (aggregate / single layouts).

    ``search`` / ``map`` write their whole url+title list here (aggregate);
    ``research`` writes its single markdown report here (single). The file name
    comes from ``layout_filename_for(result_kind)`` (e.g. ``search.json``).
    """
    envelope = build_result_envelope(
        script_name=script_name,
        result_kind=result_kind,
        result=result,
        exit_code=exit_code,
    )
    file_path = target_dir / layout_filename_for(result_kind)
    emit(OutputChannel.RESULT_FILE, envelope, path=file_path, pretty=pretty)
    emit(OutputChannel.DIAGNOSTIC, f"Wrote result envelope to {file_path}")


def ensure_item_titles(items: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    """Resolve a ``(title, title_source)`` for each content item.

    An item that already carries a non-empty ``title`` keeps it
    (``title_source="existing"``); one without (notably ``crawl`` items) has its
    title back-filled via a direct HTML fetch — never Tavily — falling back to a
    URL-derived slug. Missing titles are fetched concurrently.
    """
    resolved: list[tuple[str, str] | None] = [None] * len(items)
    to_fetch: list[int] = []
    for index, item in enumerate(items):
        existing = (item.get("title") or "").strip()
        if existing:
            resolved[index] = (existing, "existing")
        else:
            to_fetch.append(index)

    if to_fetch:
        def fetch(index: int) -> tuple[str, str]:
            url = (items[index].get("url") or "").strip()
            if not url:
                return (build_title_from_url(""), "url_fallback")
            page = fetch_page_title(
                url,
                timeout_seconds=DEFAULT_TITLE_OPTIONS["timeout_seconds"],
                max_bytes=DEFAULT_TITLE_OPTIONS["max_bytes"],
            )
            return (page.title, page.title_source)

        max_workers = min(DEFAULT_TITLE_OPTIONS["max_workers"], len(to_fetch))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for index, pair in zip(to_fetch, executor.map(fetch, to_fetch)):
                resolved[index] = pair

    return [pair if pair is not None else ("", "url_fallback") for pair in resolved]


def write_split_results(
    target_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode,
    topic: str,
    pretty: bool = True,
) -> None:
    """Write one ``NNNN.json`` per URL plus a master ``index.json`` (split layout).

    Used by content-series commands (``extract`` / ``crawl`` / ``search_extract`` /
    ``map_extract``). Each per-URL file is a self-describing ``ResultEnvelope``
    whose ``result`` is that one content item; titles are back-filled first so the
    index always carries a human-readable title. Files are numbered from
    ``0001.json`` (4-digit). A re-run with the same topic overwrites these files.
    """
    items: list[dict[str, Any]] = [item for item in (result or []) if isinstance(item, dict)]
    titles = ensure_item_titles(items)

    entries: list[dict[str, Any]] = []
    for position, (item, (title, title_source)) in enumerate(zip(items, titles), start=1):
        file_name = f"{position:04d}.json"
        enriched = dict(item)
        if not (enriched.get("title") or "").strip():
            enriched["title"] = title
        envelope = build_result_envelope(
            script_name=script_name,
            result_kind=result_kind,
            result=enriched,
            exit_code=exit_code,
        )
        emit(OutputChannel.RESULT_FILE, envelope, path=target_dir / file_name, pretty=pretty)
        entries.append(
            {
                "file": file_name,
                "url": item.get("url"),
                "title": title,
                "title_source": title_source,
                "exit_code": int(exit_code),
            }
        )

    index = {
        "script": script_name,
        "result_kind": result_kind.value,
        "topic": topic,
        "entries": entries,
    }
    index_path = target_dir / INDEX_FILE_NAME
    emit(OutputChannel.RESULT_FILE, index, path=index_path, pretty=pretty)
    emit(
        OutputChannel.DIAGNOSTIC,
        f"Wrote {len(entries)} per-URL file(s) and index to {index_path}",
    )


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