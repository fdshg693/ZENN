r"""Map a site with Tavily, fetch page titles, and return an aggregated outline.

This wrapper uses Tavily only for URL discovery and then fetches each mapped page
directly to resolve titles. Callers mainly provide a root URL plus a high-level
detail preset; the preset values below control both Tavily map behavior and the
local title-fetch behavior. Edit the preset table near the top of this file when
you want to change depth, breadth, fetch limits, or concurrency.

PowerShell example:
    python .\.claude\skills\use-tavily\src\map_site_titles.py https://learn.microsoft.com/azure/api-management/ --output temp\web\site_map_apim_docs.json

bash example:
    python ./.claude/skills/use-tavily/src/map_site_titles.py https://learn.microsoft.com/azure/api-management/ --output temp/web/site_map_apim_docs.json
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from tavily.errors import InvalidAPIKeyError

from tavily_common import build_response_payload, create_tavily_client, dedupe_preserve_order, emit_payload


DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "map": {
            "max_depth": 1,
            "max_breadth": 20,
            "limit": 20,
            "timeout": 30.0,
            "include_usage": False,
        },
        "titles": {
            "max_workers": 4,
            "timeout_seconds": 10.0,
            "max_bytes": 131072,
        },
    },
    "balanced": {
        "map": {
            "max_depth": 2,
            "max_breadth": 30,
            "limit": 40,
            "timeout": 45.0,
            "include_usage": False,
        },
        "titles": {
            "max_workers": 6,
            "timeout_seconds": 12.0,
            "max_bytes": 196608,
        },
    },
    "max": {
        "map": {
            "max_depth": 3,
            "max_breadth": 40,
            "limit": 80,
            "timeout": 60.0,
            "include_usage": False,
        },
        "titles": {
            "max_workers": 8,
            "timeout_seconds": 15.0,
            "max_bytes": 262144,
        },
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_ALLOW_EXTERNAL = False
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; tavily-map-site-titles/1.0)"
DEFAULT_ACCEPT_HEADER = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
TITLE_FALLBACK_LABEL = "Untitled"
TITLE_SEPARATOR_PATTERN = re.compile(r"\s*[|\-:\u2013\u2014]\s*")


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_chunks: list[str] = []
        self.og_title: str | None = None
        self.twitter_title: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True
            return

        if tag.lower() != "meta":
            return

        attributes = {name.lower(): (value or "") for name, value in attrs}
        property_name = attributes.get("property", "").lower()
        meta_name = attributes.get("name", "").lower()
        content = clean_text(attributes.get("content", ""))
        if not content:
            return
        if property_name == "og:title" and not self.og_title:
            self.og_title = content
        if meta_name == "twitter:title" and not self.twitter_title:
            self.twitter_title = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_chunks.append(data)

    @property
    def title(self) -> str | None:
        value = clean_text(" ".join(self._title_chunks))
        return value or None


@dataclass(slots=True)
class PageTitleResult:
    url: str
    title: str
    short_title: str | None
    title_source: str
    final_url: str | None
    content_type: str | None
    status_code: int | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "short_title": self.short_title,
            "title_source": self.title_source,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "error": self.error,
        }


def clean_text(value: str) -> str:
    return " ".join(unescape(value).split())


def shorten_title(title: str) -> str | None:
    parts = [clean_text(part) for part in TITLE_SEPARATOR_PATTERN.split(title) if clean_text(part)]
    if len(parts) <= 1:
        return None
    preferred = parts[0]
    return preferred if preferred != title else None


def build_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = PurePosixPath(parsed.path or "/")
    if path.name:
        raw_segment = path.name
    elif len(path.parts) > 1:
        raw_segment = path.parts[-1]
    else:
        raw_segment = parsed.netloc or TITLE_FALLBACK_LABEL
    label = raw_segment.replace("-", " ").replace("_", " ").strip()
    return clean_text(label.title()) or parsed.netloc or TITLE_FALLBACK_LABEL


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map a site with Tavily and fetch each page title with minimal arguments."
    )
    parser.add_argument(
        "url",
        help="Root URL to map.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level preset for the Tavily map request and title fetching.",
    )
    parser.add_argument(
        "--instruction",
        help="Optional natural-language focus for Tavily map.",
    )
    parser.add_argument(
        "--select-path",
        action="append",
        default=[],
        help="Optional regex path filter to include. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Optional regex path filter to exclude. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--select-domain",
        action="append",
        default=[],
        help="Optional regex domain filter to include. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="Optional regex domain filter to exclude. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--allow-external",
        action="store_true",
        default=DEFAULT_ALLOW_EXTERNAL,
        help="Include external-domain URLs in the mapped result set.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON response.",
    )
    return parser.parse_args(argv)


def resolve_map_options(detail: str) -> dict[str, dict[str, Any]]:
    preset = DETAIL_PRESETS[detail]
    return {
        "map": dict(preset["map"]),
        "titles": dict(preset["titles"]),
    }


def run_map_request(
    client: Any,
    *,
    url: str,
    map_options: Mapping[str, Any],
    instruction: str | None,
    select_paths: Sequence[str],
    exclude_paths: Sequence[str],
    select_domains: Sequence[str],
    exclude_domains: Sequence[str],
    allow_external: bool,
) -> dict[str, Any]:
    normalized_select_paths = dedupe_preserve_order(select_paths)
    normalized_exclude_paths = dedupe_preserve_order(exclude_paths)
    normalized_select_domains = dedupe_preserve_order(select_domains)
    normalized_exclude_domains = dedupe_preserve_order(exclude_domains)
    response = client.map(
        url=url,
        instructions=instruction,
        select_paths=normalized_select_paths or None,
        exclude_paths=normalized_exclude_paths or None,
        select_domains=normalized_select_domains or None,
        exclude_domains=normalized_exclude_domains or None,
        allow_external=allow_external,
        **dict(map_options),
    )
    return {
        "url": url,
        "instruction": instruction,
        "select_paths": normalized_select_paths,
        "exclude_paths": normalized_exclude_paths,
        "select_domains": normalized_select_domains,
        "exclude_domains": normalized_exclude_domains,
        "allow_external": allow_external,
        "options": dict(map_options),
        "response": response,
    }


def fetch_page_title(url: str, *, timeout_seconds: float, max_bytes: int) -> PageTitleResult:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": DEFAULT_ACCEPT_HEADER,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = getattr(response, "status", None)
            final_url = response.geturl()
            headers = response.headers
            content_type = headers.get("Content-Type")
            charset = headers.get_content_charset() if hasattr(headers, "get_content_charset") else None
            body = response.read(max_bytes)
    except Exception as exc:
        fallback = build_title_from_url(url)
        return PageTitleResult(
            url=url,
            title=fallback,
            short_title=None,
            title_source="url_fallback",
            final_url=None,
            content_type=None,
            status_code=None,
            error=str(exc),
        )

    parsed_content_type = (content_type or "").lower()
    if "html" not in parsed_content_type and "xml" not in parsed_content_type:
        fallback = build_title_from_url(final_url or url)
        return PageTitleResult(
            url=url,
            title=fallback,
            short_title=None,
            title_source="url_fallback",
            final_url=final_url,
            content_type=content_type,
            status_code=status_code,
            error=f"Unsupported content type for title parsing: {content_type}",
        )

    encoding = charset or "utf-8"
    html = body.decode(encoding, errors="replace")
    parser = TitleParser()
    parser.feed(html)

    title = parser.og_title or parser.twitter_title or parser.title
    if title:
        return PageTitleResult(
            url=url,
            title=title,
            short_title=shorten_title(title),
            title_source="html",
            final_url=final_url,
            content_type=content_type,
            status_code=status_code,
            error=None,
        )

    fallback = build_title_from_url(final_url or url)
    return PageTitleResult(
        url=url,
        title=fallback,
        short_title=None,
        title_source="url_fallback",
        final_url=final_url,
        content_type=content_type,
        status_code=status_code,
        error="No title metadata found in the fetched document.",
    )


def collect_titles(urls: Sequence[str], *, title_options: Mapping[str, Any]) -> list[dict[str, Any]]:
    normalized_urls = dedupe_preserve_order(urls)
    if not normalized_urls:
        return []

    max_workers = min(title_options["max_workers"], len(normalized_urls))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(
            executor.map(
                lambda current_url: fetch_page_title(
                    current_url,
                    timeout_seconds=title_options["timeout_seconds"],
                    max_bytes=title_options["max_bytes"],
                ),
                normalized_urls,
            )
        )
    return [result.as_dict() for result in results]


def summarize_pages(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hostnames = {
        urlparse(page.get("final_url") or page.get("url") or "").netloc
        for page in pages
        if page.get("final_url") or page.get("url")
    }
    titled_count = sum(1 for page in pages if page.get("title_source") == "html")
    fallback_count = sum(1 for page in pages if page.get("title_source") != "html")
    error_count = sum(1 for page in pages if page.get("error"))
    return {
        "total_urls": len(pages),
        "html_title_count": titled_count,
        "fallback_title_count": fallback_count,
        "error_count": error_count,
        "unique_host_count": len({hostname for hostname in hostnames if hostname}),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    options = resolve_map_options(args.detail)

    try:
        client, dotenv_path = create_tavily_client()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        map_run = run_map_request(
            client,
            url=args.url,
            map_options=options["map"],
            instruction=args.instruction,
            select_paths=args.select_path,
            exclude_paths=args.exclude_path,
            select_domains=args.select_domain,
            exclude_domains=args.exclude_domain,
            allow_external=args.allow_external,
        )
        mapped_urls = dedupe_preserve_order(map_run["response"].get("results") or [])
        pages = collect_titles(mapped_urls, title_options=options["titles"])
    except InvalidAPIKeyError as exc:
        print(f"Invalid Tavily API key: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Map and title aggregation failed: {exc}", file=sys.stderr)
        return 1

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "url": map_run["url"],
            "detail": args.detail,
            "instruction": map_run["instruction"],
            "select_paths": map_run["select_paths"],
            "exclude_paths": map_run["exclude_paths"],
            "select_domains": map_run["select_domains"],
            "exclude_domains": map_run["exclude_domains"],
            "allow_external": map_run["allow_external"],
            "map": map_run["options"],
            "titles": options["titles"],
        },
        response={
            "map": map_run["response"],
            "pages": pages,
            "summary": summarize_pages(pages),
        },
        dotenv_path=dotenv_path,
    )

    emit_payload(payload, args.output, public_payload=pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())