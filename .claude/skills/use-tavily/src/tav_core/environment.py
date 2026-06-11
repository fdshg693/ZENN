"""Environment & credentials: ``.env`` loading, the Tavily client, env toggles.

Everything that reads the process environment lives here, so changing how the
skill discovers its API key, output directory, or logging toggles is a one-file
edit. The env-var names and their defaults (documented in the README under
"設定とパス解決") are the constants at the top.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from tavily import TavilyClient


# Output-layout settings, read from the environment (see README "設定とパス解決").
OUTPUT_DIR_ENV = "TAVILY_OUTPUT_DIR"
WRITE_LOG_ENV = "TAVILY_WRITE_LOG"
SHOW_LOG_PATH_ENV = "TAVILY_SHOW_LOG_PATH"
DEFAULT_OUTPUT_DIR = "temp/web"


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
