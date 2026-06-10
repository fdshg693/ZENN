r"""Offline tests for the ``--topic`` output layout (no network, no credits).

These cover the migration in ``tavily_common.py`` / ``title_fetch.py``:

  * path / shape helpers: ``resolve_output_target`` / ``output_shape_for`` /
    ``should_write_log`` / ``layout_filename_for``.
  * aggregate layout: ``search`` / ``map`` write ONE command-named file holding
    the whole url+title list.
  * split layout: ``extract`` / ``crawl`` write one ``NNNN.json`` per URL plus a
    master ``index.json``; file count == entry count; every entry has a title.
  * title back-fill: items lacking a title get one (fetch is stubbed here so the
    suite stays offline); ``build_title_from_url`` fallback is exercised directly.
  * log toggle: ``TAVILY_WRITE_LOG=false`` writes no ``logs/<script>-log.json``.
  * stdout contract: no ``--topic`` -> a single ``ResultEnvelope`` on stdout.

Run (stdlib only):
    python -m unittest discover -s .claude/skills/use-tavily/tests
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
sys.path.insert(0, str(SRC))

import tavily_common as tc  # noqa: E402
from tavily_common import (  # noqa: E402
    ExitCode,
    ResultKind,
    emit_payload,
    layout_filename_for,
    output_shape_for,
    resolve_output_target,
    should_write_log,
)
from title_fetch import PageTitleResult, build_title_from_url  # noqa: E402


def make_log(script: str) -> dict:
    return {
        "script": script,
        "request": {},
        "environment": {"dotenv_loaded": False, "dotenv_path": None, "api_key_present": False},
        "response": {},
    }


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


class EnvGuard(unittest.TestCase):
    """Snapshot/restore the env vars these tests mutate."""

    _KEYS = ("TAVILY_OUTPUT_DIR", "TAVILY_WRITE_LOG")

    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in self._KEYS}

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestHelpers(EnvGuard):
    def test_output_shape_for(self) -> None:
        self.assertEqual(output_shape_for(ResultKind.SEARCH_RESULTS), "aggregate")
        self.assertEqual(output_shape_for(ResultKind.SITE_PAGES), "aggregate")
        self.assertEqual(output_shape_for(ResultKind.EXTRACT_RESULTS), "split")
        self.assertEqual(output_shape_for(ResultKind.CRAWL_RESULTS), "split")
        self.assertEqual(output_shape_for(ResultKind.RESEARCH_REPORT), "single")

    def test_layout_filename(self) -> None:
        self.assertEqual(layout_filename_for(ResultKind.SEARCH_RESULTS), "search.json")
        self.assertEqual(layout_filename_for(ResultKind.SITE_PAGES), "map.json")
        self.assertEqual(layout_filename_for(ResultKind.RESEARCH_REPORT), "research.json")

    def test_resolve_output_target_uses_env(self) -> None:
        os.environ["TAVILY_OUTPUT_DIR"] = "some/base"
        self.assertEqual(resolve_output_target("topicx"), Path("some/base") / "topicx")

    def test_resolve_output_target_defaults_to_temp_web(self) -> None:
        os.environ.pop("TAVILY_OUTPUT_DIR", None)
        self.assertEqual(resolve_output_target("t"), Path("temp/web") / "t")

    def test_resolve_output_target_flattens_traversal(self) -> None:
        target = resolve_output_target("../../etc", output_dir=Path("base"))
        # The topic can never introduce path separators that escape ``base``.
        self.assertEqual(target.parent, Path("base"))
        self.assertNotIn("..", target.name.split(os.sep))

    def test_should_write_log_default_true(self) -> None:
        os.environ.pop("TAVILY_WRITE_LOG", None)
        self.assertTrue(should_write_log())

    def test_should_write_log_falsey_values(self) -> None:
        for value in ("false", "FALSE", "0", "no", "off", ""):
            os.environ["TAVILY_WRITE_LOG"] = value
            self.assertFalse(should_write_log(), f"{value!r} should suppress the log")
        for value in ("true", "1", "yes"):
            os.environ["TAVILY_WRITE_LOG"] = value
            self.assertTrue(should_write_log(), f"{value!r} should enable the log")


class TestLayoutWriters(EnvGuard):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        os.environ["TAVILY_OUTPUT_DIR"] = str(self.base)
        os.environ["TAVILY_WRITE_LOG"] = "false"  # keep src/logs clean in tests

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def test_aggregate_search_writes_single_list_file(self) -> None:
        results = [
            {"title": "A", "url": "https://a", "content": "c", "score": 0.5, "raw_content": None},
            {"title": "B", "url": "https://b", "content": "c2", "score": 0.4, "raw_content": None},
        ]
        emit_payload(
            make_log("search_topic.py"),
            topic="topic_s",
            result_kind=ResultKind.SEARCH_RESULTS,
            result=results,
            exit_code=ExitCode.SUCCESS,
        )
        agg = self.base / "topic_s" / "search.json"
        self.assertTrue(agg.exists())
        envelope = read_json(agg)
        self.assertEqual(envelope["result_kind"], "search_results")
        self.assertEqual([r["url"] for r in envelope["result"]], ["https://a", "https://b"])
        for item in envelope["result"]:
            self.assertIn("title", item)
        # Aggregate is a single file: no per-URL split files, no index.
        self.assertFalse((self.base / "topic_s" / "index.json").exists())
        self.assertFalse((self.base / "topic_s" / "0001.json").exists())

    def test_map_aggregate_filename(self) -> None:
        emit_payload(
            make_log("map_site_titles.py"),
            topic="topic_m",
            result_kind=ResultKind.SITE_PAGES,
            result=[{"url": "https://a", "title": "A", "title_source": "html"}],
            exit_code=ExitCode.SUCCESS,
        )
        self.assertTrue((self.base / "topic_m" / "map.json").exists())

    def test_split_writes_per_url_files_and_index(self) -> None:
        # Crawl items carry no title; stub the fetch so the suite stays offline.
        def stub(url, *, timeout_seconds, max_bytes):
            return PageTitleResult(
                url=url, title=f"Title for {url}", short_title=None,
                title_source="html", final_url=url, content_type="text/html",
                status_code=200, error=None,
            )

        original = tc.fetch_page_title
        tc.fetch_page_title = stub
        try:
            results = [
                {"url": "https://x/1", "raw_content": "one"},
                {"url": "https://x/2", "raw_content": "two"},
                {"url": "https://x/3", "raw_content": "three"},
            ]
            emit_payload(
                make_log("crawl_site_content.py"),
                topic="topic_c",
                result_kind=ResultKind.CRAWL_RESULTS,
                result=results,
                exit_code=ExitCode.SUCCESS,
            )
        finally:
            tc.fetch_page_title = original

        topic_dir = self.base / "topic_c"
        index = read_json(topic_dir / "index.json")
        self.assertEqual(index["result_kind"], "crawl_results")
        self.assertEqual(index["topic"], "topic_c")

        per_url = sorted(p.name for p in topic_dir.glob("[0-9][0-9][0-9][0-9].json"))
        # File count == entry count.
        self.assertEqual(len(per_url), len(index["entries"]))
        self.assertEqual(per_url, ["0001.json", "0002.json", "0003.json"])

        for entry in index["entries"]:
            # Every index file exists and every entry has a non-empty title.
            self.assertTrue((topic_dir / entry["file"]).exists(), entry["file"])
            self.assertTrue(entry["title"], f"title missing for {entry}")
            # Per-URL file is self-describing: its result is a single item with url.
            envelope = read_json(topic_dir / entry["file"])
            self.assertEqual(envelope["result"]["url"], entry["url"])
            self.assertEqual(envelope["result"]["title"], entry["title"])

    def test_split_title_backfill_url_fallback(self) -> None:
        # Force the fetch to fail -> build_title_from_url fallback path.
        def failing(url, *, timeout_seconds, max_bytes):
            return PageTitleResult(
                url=url, title=build_title_from_url(url), short_title=None,
                title_source="url_fallback", final_url=None, content_type=None,
                status_code=None, error="boom",
            )

        original = tc.fetch_page_title
        tc.fetch_page_title = failing
        try:
            emit_payload(
                make_log("crawl_site_content.py"),
                topic="topic_fb",
                result_kind=ResultKind.CRAWL_RESULTS,
                result=[{"url": "https://learn.microsoft.com/azure/fabric/overview", "raw_content": "x"}],
                exit_code=ExitCode.SUCCESS,
            )
        finally:
            tc.fetch_page_title = original

        index = read_json(self.base / "topic_fb" / "index.json")
        entry = index["entries"][0]
        self.assertEqual(entry["title_source"], "url_fallback")
        self.assertEqual(entry["title"], "Overview")

    def test_split_keeps_existing_title_without_fetching(self) -> None:
        # If items already carry titles, no fetch should ever happen.
        def must_not_call(url, *, timeout_seconds, max_bytes):  # pragma: no cover
            raise AssertionError("fetch_page_title must not be called when titles exist")

        original = tc.fetch_page_title
        tc.fetch_page_title = must_not_call
        try:
            emit_payload(
                make_log("extract_url_content.py"),
                topic="topic_e",
                result_kind=ResultKind.EXTRACT_RESULTS,
                result=[{"url": "https://a", "title": "Kept", "raw_content": "x", "images": []}],
                exit_code=ExitCode.SUCCESS,
            )
        finally:
            tc.fetch_page_title = original

        index = read_json(self.base / "topic_e" / "index.json")
        self.assertEqual(index["entries"][0]["title"], "Kept")
        self.assertEqual(index["entries"][0]["title_source"], "existing")

    def test_research_single_file(self) -> None:
        emit_payload(
            make_log("research_topic.py"),
            topic="topic_r",
            result_kind=ResultKind.RESEARCH_REPORT,
            result="# Report",
            exit_code=ExitCode.SUCCESS,
        )
        report = self.base / "topic_r" / "research.json"
        self.assertTrue(report.exists())
        self.assertEqual(read_json(report)["result"], "# Report")
        self.assertFalse((self.base / "topic_r" / "index.json").exists())

    def test_empty_split_writes_index_with_no_entries(self) -> None:
        emit_payload(
            make_log("search_extract_topic.py"),
            topic="topic_empty",
            result_kind=ResultKind.EXTRACT_RESULTS,
            result=[],
            exit_code=ExitCode.EMPTY_RESULT,
        )
        index = read_json(self.base / "topic_empty" / "index.json")
        self.assertEqual(index["entries"], [])


class TestLogToggle(EnvGuard):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        os.environ["TAVILY_OUTPUT_DIR"] = str(self.base)
        # Redirect the audit-log directory into the temp dir so we don't touch src/logs.
        self._orig_log_dir = tc.LOG_DIRECTORY
        tc.LOG_DIRECTORY = self.base / "logs"

    def tearDown(self) -> None:
        tc.LOG_DIRECTORY = self._orig_log_dir
        self._tmp.cleanup()
        super().tearDown()

    def _emit(self) -> None:
        emit_payload(
            make_log("search_topic.py"),
            topic="t",
            result_kind=ResultKind.SEARCH_RESULTS,
            result=[],
            exit_code=ExitCode.SUCCESS,
        )

    def test_log_suppressed_when_false(self) -> None:
        os.environ["TAVILY_WRITE_LOG"] = "false"
        self._emit()
        self.assertFalse((self.base / "logs" / "search_topic-log.json").exists())

    def test_log_written_when_enabled(self) -> None:
        os.environ["TAVILY_WRITE_LOG"] = "true"
        self._emit()
        self.assertTrue((self.base / "logs" / "search_topic-log.json").exists())


class TestStdoutContract(EnvGuard):
    def test_no_topic_prints_single_envelope_to_stdout(self) -> None:
        os.environ["TAVILY_WRITE_LOG"] = "false"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            emit_payload(
                make_log("search_topic.py"),
                topic=None,
                result_kind=ResultKind.SEARCH_RESULTS,
                result=[{"title": "A", "url": "https://a", "content": "c", "score": 0.1, "raw_content": None}],
                exit_code=ExitCode.SUCCESS,
            )
        envelope = json.loads(buffer.getvalue())
        self.assertEqual(envelope["result_kind"], "search_results")
        self.assertEqual(envelope["exit_code"], 0)
        self.assertEqual(envelope["result"][0]["url"], "https://a")


if __name__ == "__main__":
    unittest.main()
