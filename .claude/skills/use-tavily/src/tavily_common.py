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
import re
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
SHOW_LOG_PATH_ENV = "TAVILY_SHOW_LOG_PATH"
DEFAULT_OUTPUT_DIR = "temp/web"
INDEX_FILE_NAME = "index.json"

# Shared ``--topic`` help, reused by every wrapper's ``--topic`` argument so the
# accumulate-into-role-subfolders contract is described in exactly one place (§4
# of PLAN.md "集約 vs 分割をコード/CLI ヘルプから明確化").
TOPIC_ARG_HELP = (
    "Accumulate this run into <TAVILY_OUTPUT_DIR>/NAME/. Discovery commands "
    "(search/map) append one list file under search/ or map/; content commands "
    "(extract/crawl) write one .md per page under pages/ (indexed by pages/index.json); "
    "research writes one .md under research/. Existing files are kept (never "
    "overwritten). Omit --topic to print one ResultEnvelope to stdout."
)

# ---------------------------------------------------------------------------
# Role-based topic layout (PLAN.md §0-§3). A ``--topic`` run's output is filed by
# the *role* of its ``result_kind`` — never one flat namespace — so the kinds of
# output (a discovery menu, fetched page bodies, a finished report) never mix:
#
#   discovery (search/map) -> aggregate JSON list, one file per task:
#                             <topic>/search/NNNN-<slug>.json or <topic>/map/...
#   content   (extract/crawl) -> one Markdown page per URL + a pages/index.json:
#                             <topic>/pages/NNNN-<slug>.md
#   report    (research) -> one Markdown report per question:
#                             <topic>/research/NNNN-<slug>.md (.json on failure)
#
# ``NNNN`` is allocated independently inside each subfolder (never a cross-role
# running number) and continues from the existing max on re-runs, so the same
# topic *accumulates* (appends) instead of overwriting.
# ---------------------------------------------------------------------------
ROLE_DISCOVERY = "discovery"
ROLE_CONTENT = "content"
ROLE_REPORT = "report"

ROLE_FOR_KIND: dict["ResultKind", str] = {}      # filled after ResultKind is defined
SUBDIR_FOR_KIND: dict["ResultKind", str] = {}    # role subfolder name per result_kind

# Projection allow-lists (PLAN.md §4③): the ONLY keys kept when a result item is
# written to a topic file or printed to stdout. Everything else (raw_content==None
# on search, empty images on extract, fetch metadata on site pages, ...) is research-
# irrelevant noise and dropped. The full untouched objects still live in the audit
# log. Edit these tuples to change what survives projection.
PROJECTION_KEYS: dict["ResultKind", tuple[str, ...]] = {}  # filled after ResultKind


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


# Populate the role-layout tables now that ResultKind exists (see the role-layout
# block near the top of this module for what each entry means).
ROLE_FOR_KIND.update(
    {
        ResultKind.SEARCH_RESULTS: ROLE_DISCOVERY,
        ResultKind.SITE_PAGES: ROLE_DISCOVERY,
        ResultKind.EXTRACT_RESULTS: ROLE_CONTENT,
        ResultKind.CRAWL_RESULTS: ROLE_CONTENT,
        ResultKind.RESEARCH_REPORT: ROLE_REPORT,
    }
)
SUBDIR_FOR_KIND.update(
    {
        ResultKind.SEARCH_RESULTS: "search",
        ResultKind.SITE_PAGES: "map",
        ResultKind.EXTRACT_RESULTS: "pages",
        ResultKind.CRAWL_RESULTS: "pages",
        ResultKind.RESEARCH_REPORT: "research",
    }
)
PROJECTION_KEYS.update(
    {
        # search rows: triage columns only. raw_content is always None under our flags.
        ResultKind.SEARCH_RESULTS: ("url", "title", "content", "score"),
        # extract pages: identity + body. images is always empty under our flags.
        ResultKind.EXTRACT_RESULTS: ("url", "title", "raw_content"),
        # crawl pages: url + body only (crawl items never carry a title).
        ResultKind.CRAWL_RESULTS: ("url", "raw_content"),
        # site-page menu: url + readable titles; fetch metadata is dropped.
        ResultKind.SITE_PAGES: ("url", "title", "short_title"),
        # research_report has no per-item projection (it is a single str/dict).
    }
)


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
    RESULT_FILE = "result_file"       # .json (discovery list / index / failed report) or .md (page / report) -> a topic-folder file.
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
class TopicArtifact:
    """A secondary role-output a run also wants persisted under ``--topic``.

    Composite commands produce two artifacts of *different roles*: the discovery
    menu they searched/mapped AND the page content they then extracted. ``main()``
    returns the content as the primary ``RunOutcome.result`` and the discovery
    menu as ``RunOutcome.discovery`` (one of these), so "what was searched" and
    "what was fetched" both land in the topic folder, each in its own role
    subfolder. ``slug`` names the task (query / domain) for the ``NNNN-<slug>`` file.
    """

    result_kind: ResultKind
    result: Any
    slug: str | None = None


@dataclass(slots=True)
class BackgroundTask:
    """A fully detached follow-on process a run wants launched after it returns.

    The wrapper scripts block their caller (often an AI agent) only briefly. A
    long-running op — today only ``research`` — whose foreground wait expires
    returns ``INCOMPLETE`` immediately AND attaches one of these so the work is
    not abandoned: ``finalize()`` (the sole side-effect site) spawns ``argv`` as a
    detached process that outlives this one and finishes the job. ``main()`` stays
    pure by merely *describing* the process to launch; nothing is spawned until
    ``finalize()`` runs. ``argv`` is the complete command (interpreter + script +
    args); ``cwd`` fixes the working directory so output-dir resolution matches
    the parent (see ``get_output_dir``).
    """

    argv: list[str]
    cwd: str | None = None


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
    - ``topic``: the ``--topic`` value. When set, ``finalize()`` files the result
      into ``<TAVILY_OUTPUT_DIR>/<topic>/`` under the role subfolder for
      ``result_kind`` (search/ map/ pages/ research/). When ``None``, the single
      ``ResultEnvelope`` goes to stdout (pipe use).
    - ``slug``: task-level slug hint for the ``NNNN-<slug>`` file name of the
      discovery/report writers (the search query, the mapped domain, the research
      question). Ignored by the content writer, which slugs each page from its own
      title. ``None`` falls back to a generic stem.
    - ``discovery``: an optional second ``TopicArtifact`` (composite commands only)
      filed alongside the primary result in its own role subfolder; ignored on the
      stdout path so the pipe contract stays one envelope.
    - ``message``: a single stderr line to print, if any (errors, empty/incomplete
      notices). ``None`` means stay silent on stderr.
    - ``background``: an optional ``BackgroundTask`` ``finalize()`` spawns detached
      after emitting this run's output. Used by ``research`` to keep polling a job
      whose foreground wait expired. ``None`` means no follow-on process.
    """

    exit_code: ExitCode
    topic: str | None = None
    log: ResponseEnvelope | None = None
    result_kind: ResultKind | None = None
    result: Any = None
    message: str | None = None
    slug: str | None = None
    discovery: TopicArtifact | None = None
    background: BackgroundTask | None = None


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
            slug=outcome.slug,
            discovery=outcome.discovery,
        )
    if outcome.message:
        emit(OutputChannel.DIAGNOSTIC, outcome.message)
    if outcome.background is not None:
        spawn_detached(outcome.background)
    return outcome.exit_code


def spawn_detached(task: BackgroundTask) -> None:
    """Launch ``task.argv`` as a process that fully outlives this one.

    The child must survive the parent exiting and must not hold the parent's
    console (the parent typically returns control to an interactive caller right
    after). On Windows that means ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP``;
    on POSIX a new session (``start_new_session``). The child's std streams are
    detached: it talks to no one — it persists its result to the topic folder and
    its outcome to the audit log. A spawn failure is swallowed to a stderr
    ``DIAGNOSTIC`` so it can never turn a returned ``INCOMPLETE`` into a crash.
    """
    import subprocess

    kwargs: dict[str, Any] = {
        "cwd": task.cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(task.argv, **kwargs)  # noqa: S603 — argv is built internally, not from user shell input
    except OSError as exc:
        emit(OutputChannel.DIAGNOSTIC, f"Could not spawn background poller: {exc}")


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


_FALSEY_ENV_VALUES = {"", "false", "0", "no", "off"}


def _env_flag(name: str, *, default: bool = True) -> bool:
    """Parse a boolean toggle env var with the shared falsey convention.

    Default (unset) is ``default``. Values ``false`` / ``0`` / ``no`` / ``off`` /
    empty (case-insensitive) read as ``False``; anything else reads as ``True``.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSEY_ENV_VALUES


def should_write_log() -> bool:
    """Whether to write ``logs/<script>-log.json``, from ``TAVILY_WRITE_LOG``.

    Default (unset) is ``True`` — the historical always-on behavior. Values
    ``false`` / ``0`` / ``no`` / ``off`` / empty (case-insensitive) suppress it.
    """
    return _env_flag(WRITE_LOG_ENV)


def should_show_log_path() -> bool:
    """Whether to echo the "Wrote full log to <path>" notice, from ``TAVILY_SHOW_LOG_PATH``.

    Default (unset) is ``True``. Same falsey convention as ``should_write_log()``.
    This toggles ONLY the stderr ``DIAGNOSTIC`` notice for the *audit log* path,
    and only when an audit log is actually written (``should_write_log()``).
    Result/output file path notices are always shown — they point to the records
    the caller asked for — and the files themselves are unaffected.
    """
    return _env_flag(SHOW_LOG_PATH_ENV)


def resolve_output_target(topic: str, *, output_dir: Path | None = None) -> Path:
    """Resolve the topic folder ``<TAVILY_OUTPUT_DIR>/<topic>/`` for ``--topic``.

    ``topic`` is used as a single folder name; any stray path separators are
    flattened to ``_`` so it can never escape the output directory.
    """
    base = output_dir if output_dir is not None else get_output_dir()
    safe_topic = topic.strip().replace("\\", "_").replace("/", "_") or "topic"
    return base / safe_topic


def role_for(result_kind: ResultKind) -> str:
    """The output role (discovery / content / report) a ``result_kind`` belongs to.

    This 3-way dispatch is the single source of truth for "where does this land":
    discovery -> a list file under search/ or map/, content -> Markdown pages
    under pages/, report -> a Markdown report under research/ (see ROLE_FOR_KIND).
    """
    return ROLE_FOR_KIND[result_kind]


_SLUG_SEPARATOR = re.compile(r"[^\w]+", re.UNICODE)
_SEQUENCE_PREFIX = re.compile(r"^(\d{4})")


def slugify(text: str | None, *, max_length: int = 50) -> str:
    """Turn arbitrary text (a query / domain / title) into a safe file-name stem.

    Collapses runs of non-word characters to single hyphens and lowercases ASCII,
    so ``"Fabric vs Synapse"`` -> ``"fabric-vs-synapse"`` and
    ``"learn.microsoft.com"`` -> ``"learn-microsoft-com"``. Unicode word characters
    (e.g. Japanese) are kept verbatim — they are valid, self-describing file names.
    Empty / punctuation-only input falls back to ``"item"``.
    """
    lowered = (text or "").strip().lower()
    slug = _SLUG_SEPARATOR.sub("-", lowered).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "item"


def next_sequence(directory: Path) -> int:
    """Next ``NNNN`` to allocate inside one role subfolder (existing max + 1).

    Scans for files whose name starts with a 4-digit number and returns one past
    the highest, so re-running the same topic *appends* (``0003`` after ``0002``)
    rather than overwriting. Sequencing is per-subfolder, so search/ and pages/
    keep independent series. Assumes sequential (non-concurrent) runs against a
    topic — parallel allocation could collide.
    """
    if not directory.exists():
        return 1
    highest = 0
    for entry in directory.iterdir():
        match = _SEQUENCE_PREFIX.match(entry.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def slim_result_item(result_kind: ResultKind, item: Any) -> Any:
    """Project one result item down to its research-relevant keys (PLAN.md §4③).

    Drops keys that carry no signal for research triage/reading (per
    ``PROJECTION_KEYS``). Non-dict items (e.g. a research report str) and kinds
    with no projection are returned unchanged. The full objects still live in the
    audit log; this only shapes what reaches topic files / stdout.
    """
    keys = PROJECTION_KEYS.get(result_kind)
    if keys is None or not isinstance(item, dict):
        return item
    return {key: item[key] for key in keys if key in item}


def project_result(result_kind: ResultKind, result: Any) -> Any:
    """Apply ``slim_result_item`` across a result (list -> list, else unchanged)."""
    if isinstance(result, list):
        return [slim_result_item(result_kind, item) for item in result]
    return result


def render_page_markdown(title: str | None, body: str | None) -> str:
    """Render one fetched page as ``# <title>`` + body Markdown (content role).

    The body (Tavily's ``raw_content``, already Markdown under our ``format``
    flag) is written as-is — far more readable than the same text escaped inside a
    JSON string. ``images`` / fetch metadata are intentionally NOT carried in (the
    projection already dropped them); url<->file<->title structure lives in
    ``pages/index.json``.
    """
    heading = (title or "Untitled").strip() or "Untitled"
    body_text = (body or "").strip()
    if body_text:
        return f"# {heading}\n\n{body_text}\n"
    return f"# {heading}\n"


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
    slug: str | None = None,
    discovery: TopicArtifact | None = None,
    pretty: bool = True,
) -> None:
    """Emit a run's record artifacts, routed through ``emit()``.

    Audit log: the full, unprojected ``ResponseEnvelope`` -> ``logs/<script>-log.json``
    (``AUDIT_LOG``), only when ``should_write_log()`` is true.

    Result, by ``topic``:

    - ``topic is None``: a single ``ResultEnvelope`` (with ``result`` *projected*
      to research-relevant keys) -> stdout (``RESULT_STDOUT``). The pipe contract
      stays one envelope; ``discovery`` is ignored here.
    - ``topic`` set: filed into ``<TAVILY_OUTPUT_DIR>/<topic>/`` by ``result_kind``'s
      role — discovery (a list file under search/ or map/), content (Markdown pages
      under pages/ + index), or report (a Markdown report under research/). A
      ``discovery`` artifact, when present, is filed alongside in its own role
      subfolder so a composite run keeps both its menu and its fetched bodies.

    Every accompanying notice is a ``DIAGNOSTIC`` on stderr. Result/output file
    path notices are always shown; only the audit-log path notice is gated by
    ``should_show_log_path()``.
    """
    script_name = payload.get("script", "payload")

    if should_write_log():
        log_path = build_log_output_path(script_name=script_name)
        emit(OutputChannel.AUDIT_LOG, payload, path=log_path, pretty=pretty)
        if should_show_log_path():
            emit(OutputChannel.DIAGNOSTIC, f"Wrote full log to {log_path}")

    if topic is None:
        result_envelope = build_result_envelope(
            script_name=script_name,
            result_kind=result_kind,
            result=project_result(result_kind, result),
            exit_code=exit_code,
        )
        emit(OutputChannel.RESULT_STDOUT, result_envelope, pretty=pretty)
        return

    target_dir = resolve_output_target(topic)
    write_topic_artifact(
        target_dir,
        script_name=script_name,
        result_kind=result_kind,
        result=result,
        slug=slug,
        exit_code=exit_code,
        topic=topic,
        pretty=pretty,
    )
    if discovery is not None:
        write_topic_artifact(
            target_dir,
            script_name=script_name,
            result_kind=discovery.result_kind,
            result=discovery.result,
            slug=discovery.slug,
            exit_code=exit_code,
            topic=topic,
            pretty=pretty,
        )


def write_topic_artifact(
    target_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    slug: str | None,
    exit_code: ExitCode,
    topic: str,
    pretty: bool = True,
) -> None:
    """Dispatch one (result_kind, result) to its role writer under ``target_dir``.

    The role (``role_for``) picks both the writer and the subfolder
    (``SUBDIR_FOR_KIND``): discovery -> ``write_discovery_list``, content ->
    ``write_content_pages``, report -> ``write_report``.
    """
    role = role_for(result_kind)
    role_dir = target_dir / SUBDIR_FOR_KIND[result_kind]
    if role == ROLE_CONTENT:
        write_content_pages(
            role_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            exit_code=exit_code,
            topic=topic,
            pretty=pretty,
        )
    elif role == ROLE_REPORT:
        write_report(
            role_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            slug=slug,
            exit_code=exit_code,
            pretty=pretty,
        )
    else:
        write_discovery_list(
            role_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            slug=slug,
            exit_code=exit_code,
            pretty=pretty,
        )


def write_discovery_list(
    role_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    slug: str | None,
    exit_code: ExitCode,
    pretty: bool = True,
) -> None:
    """Discovery role: append one projected list file ``NNNN-<slug>.json``.

    ``search`` / ``map`` menus are skimmed as a table AND fed to the next extract
    step, so they stay machine-readable JSON and stay *aggregated* (one task = one
    file): splitting a 5-row menu across 5 files would destroy its at-a-glance
    value. No side index — the file name is self-describing (``ls`` is enough).
    """
    items = [slim_result_item(result_kind, item) for item in (result or []) if isinstance(item, dict)]
    sequence = next_sequence(role_dir)
    file_name = f"{sequence:04d}-{slugify(slug)}.json"
    envelope = build_result_envelope(
        script_name=script_name,
        result_kind=result_kind,
        result=items,
        exit_code=exit_code,
    )
    file_path = role_dir / file_name
    emit(OutputChannel.RESULT_FILE, envelope, path=file_path, pretty=pretty)
    emit(OutputChannel.DIAGNOSTIC, f"Wrote {len(items)} {result_kind.value} row(s) to {file_path}")


def write_report(
    research_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    slug: str | None,
    exit_code: ExitCode,
    pretty: bool = True,
) -> None:
    """Report role: write one ``NNNN-<slug>.md`` report ONLY on success.

    A successful run (a Markdown ``str``) is written as ``.md`` so it reads
    straight through. Any non-success outcome — the foreground wait expiring
    (``INCOMPLETE``) or a failed/cancelled terminal (``RUNTIME_ERROR``) — writes
    NO file: research output is "the report or nothing", so a timed-out/failed
    run must not leave a half-baked ``.json`` artifact in ``research/``. The
    failure is still fully recorded in the audit log (``logs/<script>-log.json``),
    and for a foreground timeout a detached poller (``research_background_poll.py``)
    keeps going and writes the real ``.md`` here if the job later completes.
    """
    if exit_code == ExitCode.SUCCESS and isinstance(result, str):
        sequence = next_sequence(research_dir)
        file_path = research_dir / f"{sequence:04d}-{slugify(slug)}.md"
        markdown = result if result.endswith("\n") else result + "\n"
        emit(OutputChannel.RESULT_FILE, markdown, path=file_path, pretty=pretty)
        emit(OutputChannel.DIAGNOSTIC, f"Wrote research report to {file_path}")
        return
    emit(
        OutputChannel.DIAGNOSTIC,
        "Research produced no report (non-success outcome); wrote no file. "
        "See the audit log for the failure detail.",
    )


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


def load_pages_index(pages_dir: Path, *, topic: str) -> dict[str, Any]:
    """Load ``pages/index.json`` for append, or seed a fresh one.

    The index is the ONE shared file the content role accumulates (its ``entries``
    grow across runs). An unreadable / old-schema file is discarded and rebuilt
    (no migration), so a corrupt index never blocks a run.
    """
    index_path = pages_dir / INDEX_FILE_NAME
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    return {"topic": topic, "entries": []}


def write_content_pages(
    pages_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode,
    topic: str,
    pretty: bool = True,
) -> None:
    """Content role: one Markdown page per URL + an appended ``pages/index.json``.

    Page bodies are *split* (one ``NNNN-<slug>.md`` each) because they are large
    and read one at a time; aggregating them would be unreadable. Titles are
    back-filled first (``ensure_item_titles`` — direct HTML fetch, never Tavily) so
    each page gets a self-describing slug + H1 and the index carries a real title.
    Sequence numbers continue from the existing pages (append, never overwrite);
    re-extracting the same URL adds another page + index entry (duplicates kept).
    ``pages/index.json`` is the only url<->file<->title<->source map.
    """
    items: list[dict[str, Any]] = [item for item in (result or []) if isinstance(item, dict)]
    titles = ensure_item_titles(items)

    index = load_pages_index(pages_dir, topic=topic)
    start = next_sequence(pages_dir)
    written = 0
    for offset, (item, (title, title_source)) in enumerate(zip(items, titles)):
        sequence = start + offset
        file_name = f"{sequence:04d}-{slugify(title)}.md"
        markdown = render_page_markdown(title, item.get("raw_content"))
        emit(OutputChannel.RESULT_FILE, markdown, path=pages_dir / file_name, pretty=pretty)
        index["entries"].append(
            {
                "file": file_name,
                "url": item.get("url"),
                "title": title,
                "title_source": title_source,
                "script": script_name,
                "result_kind": result_kind.value,
                "exit_code": int(exit_code),
            }
        )
        written += 1

    index_path = pages_dir / INDEX_FILE_NAME
    emit(OutputChannel.RESULT_FILE, index, path=index_path, pretty=pretty)
    emit(
        OutputChannel.DIAGNOSTIC,
        f"Wrote {written} page .md file(s); index now has {len(index['entries'])} entr(ies) at {index_path}",
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
    """Write a file. A ``str`` payload (Markdown) is written verbatim; anything
    else is JSON-serialized. This is what lets ``RESULT_FILE`` carry both the
    ``.json`` discovery/index files and the ``.md`` content/report files without a
    new channel (PLAN.md §2)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else render_json(payload, pretty=pretty)
    output_path.write_text(text, encoding="utf-8")