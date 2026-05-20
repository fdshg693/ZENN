"""Shared helpers for Tavily wrapper scripts in this directory.

These scripts intentionally expose only a small set of CLI arguments.
Change shared environment-loading or JSON output behavior here when you want
to affect multiple wrapper scripts at once.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from tavily import TavilyClient


LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"


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
) -> dict[str, Any]:
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


def render_json(payload: Any, *, pretty: bool = True) -> str:
    indent = 2 if pretty else None
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def build_log_output_path(output_path: Path | None, *, script_name: str) -> Path:
    file_name = output_path.name if output_path else f"{Path(script_name).stem}.json"
    base_path = Path(file_name)
    suffix = base_path.suffix or ".json"
    return LOG_DIRECTORY / f"{base_path.stem}-log{suffix}"


def emit_payload(
    payload: dict[str, Any],
    output_path: Path | None,
    *,
    public_payload: Any | None = None,
    pretty: bool = True,
) -> None:
    display_payload = payload if public_payload is None else public_payload
    log_path = build_log_output_path(output_path, script_name=payload.get("script", "payload"))
    write_output(log_path, payload, pretty=pretty)

    if output_path:
        write_output(output_path, display_payload, pretty=pretty)
        print(f"Wrote response to {output_path}")
        print(f"Wrote full log to {log_path}")
        return

    print(render_json(display_payload, pretty=pretty), end="")
    print(f"Wrote full log to {log_path}", file=os.sys.stderr)


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