"""Offline regressions using synthetic structures observed on official endpoints."""
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from incretin_watch.cli import main
from incretin_watch.collect import collect_source, feed_records, html_records
from incretin_watch.common import digest, write_json
from incretin_watch.events import stage_events
from incretin_watch.http import Client, FetchError, SafeRedirect, allowed_url

ROOT = Path(__file__).parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
SOURCES = {s["id"]: s for s in CONFIG["sources"]}
FIXTURES = Path(__file__).parent / "fixtures"
ARTICLE_URL = "https://www.fda.gov/news-events/press-announcements/fixture-wegovy"


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value


def fixture(name, mime="text/html"):
    return (FIXTURES / name).read_bytes(), mime


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.source = copy.deepcopy(SOURCES["fda_press"])
        self.feed_url = self.source["url"]
        self.alt_url = self.source["alternatives"][0]["url"]

    def collect(self, client):
        return collect_source(self.source, CONFIG, client, "2026-10-21", "2026-11-03")

    def test_published_feed_parses_dates_and_filters_unrelated_records(self):
        client = FakeClient({self.feed_url: fixture("press.xml", "application/rss+xml"), ARTICLE_URL: fixture("article.html")})
        rows, health = self.collect(client)
        self.assertEqual(health["discovered"], 2)
        self.assertEqual(health["accepted"], 1)
        self.assertEqual(rows[0]["published_date"], "2026-11-02")
        self.assertIsNone(rows[0]["modified_date"])
        self.assertEqual(rows[0]["body_status"], "fetched")
        self.assertEqual(health["endpoint_used"], self.feed_url)
        self.assertNotIn(self.alt_url, client.calls)

    def test_fda_legacy_http_links_upgrade_only_verified_host(self):
        body = fixture("press.xml")[0].replace(b"https://www.fda.gov/", b"http://www.fda.gov/")
        client = FakeClient({self.feed_url: (body, "application/rss+xml"), ARTICLE_URL: fixture("article.html")})
        rows, health = self.collect(client)
        self.assertEqual(rows[0]["url"], ARTICLE_URL)
        self.assertFalse(any(u.startswith("http:") for u in client.calls))
        self.assertEqual(health["accepted"], 1)
        for old in (b"http://www.fda.gov.evil.test/", b"http://user:fixture@www.fda.gov/", b"http://www.fda.gov:8080/"):
            raw = body.replace(b"http://www.fda.gov/", old)
            records = feed_records(raw, self.source)
            self.assertFalse(any(allowed_url(r["url"], CONFIG["allowed_domains"]) for r in records))

    def test_404_falls_back_to_official_listing_with_visible_failure(self):
        client = FakeClient({self.feed_url: FetchError("HTTP 404", "http_not_found", 404),
                             self.alt_url: fixture("press-listing.html"), ARTICLE_URL: fixture("article.html")})
        rows, h = self.collect(client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(h["status"], "partial")
        self.assertEqual(h["endpoint_used"], self.alt_url)
        self.assertEqual(h["attempts"][0]["http_status"], 404)
        self.assertEqual(rows[0]["source_id"], "fda_press")
        self.assertEqual(rows[0]["url"], ARTICLE_URL)
        self.assertEqual(h["discovered"], 2)  # excludes navigation and off-domain links

    def test_access_denial_and_rate_limit_never_try_alternative(self):
        for status, category in [(401, "access_restricted"), (403, "access_restricted"),
                                 (412, "access_restricted"), (429, "rate_limited")]:
            with self.subTest(status=status):
                client = FakeClient({self.feed_url: FetchError("blocked", category, status)})
                rows, h = self.collect(client)
                self.assertEqual(rows, [])
                self.assertEqual(h["failure_type"], category)
                self.assertEqual(h["failure_stage"], "discovery")
                self.assertEqual(client.calls, [self.feed_url])

    def test_200_challenge_is_restricted_not_parser_failure(self):
        client = FakeClient({self.feed_url: (b"<html><title>Just a moment...</title><form id='challenge-form'></form></html>", "text/html")})
        _, h = self.collect(client)
        self.assertEqual(h["failure_type"], "access_restricted")
        self.assertEqual(client.calls, [self.feed_url])

    def test_non_feed_html_can_use_public_alternative(self):
        client = FakeClient({self.feed_url: (b"<html><title>Maintenance</title></html>", "text/html"),
                             self.alt_url: fixture("press-listing.html"), ARTICLE_URL: fixture("article.html")})
        rows, h = self.collect(client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(h["attempts"][0]["failure_type"], "parse_error")

    def test_empty_valid_feed_is_partial_without_claiming_recovery(self):
        client = FakeClient({self.feed_url: (b"<rss version='2.0'><channel><title>Empty</title></channel></rss>", "application/rss+xml")})
        rows, h = self.collect(client)
        self.assertEqual(rows, [])
        self.assertEqual(h["status"], "partial")
        self.assertEqual(len(client.calls), 1)

    def test_malformed_feed_with_entries_is_not_silent_success(self):
        with self.assertRaises(FetchError):
            feed_records(b"<rss version='2.0'><channel><item><title>Wegovy</title><link>https://www.fda.gov/x</link></item>", {})

    def test_article_failure_is_separate_and_does_not_acknowledge_event(self):
        client = FakeClient({self.feed_url: fixture("press.xml", "application/rss+xml"),
                             ARTICLE_URL: FetchError("HTTP 403", "access_restricted", 403)})
        rows, h = self.collect(client)
        self.assertEqual(h["attempts"][0]["status"], "ok")
        self.assertEqual(h["article_failures"][0]["http_status"], 403)
        self.assertEqual(rows[0]["body_status"], "unavailable")
        state = {"schema_version": 1, "documents": {}, "events": {}}
        groups, _, _ = stage_events(rows, CONFIG, state, "2026-10-21", "2026-11-03")
        self.assertEqual(groups, [])
        self.assertEqual(state["documents"], {})

    def test_article_access_block_stops_further_requests_to_that_host(self):
        body = fixture("press.xml")[0].replace(b"Unrelated synthetic notice", b"Wegovy second notice")
        client = FakeClient({self.feed_url: (body, "application/rss+xml"),
                             ARTICLE_URL: FetchError("HTTP 403", "access_restricted", 403)})
        rows, h = self.collect(client)
        self.assertEqual(client.calls, [self.feed_url, ARTICLE_URL])
        self.assertEqual(len(h["article_failures"]), 2)
        self.assertTrue(all(r["body_status"] == "unavailable" for r in rows))

    def test_fda_numeric_date_is_source_specific(self):
        body = b'<main><table><tr><td>1-13-2026</td><td><a href="/drugs/drug-safety-and-availability/fixture">Wegovy safety</a></td></tr></table></main>'
        rows = html_records(body, SOURCES["fda_safety"], CONFIG)
        self.assertEqual(rows[0]["published_date"], "2026-01-13")

    def test_anvisa_loading_shell_is_not_empty_success(self):
        body = b'<main><h1>Noticias</h1><p>Carregando</p><a href="/anvisa/pt-br/assuntos/noticias-anvisa">News</a></main>'
        _, h = collect_source(SOURCES["anvisa"], CONFIG, FakeClient({SOURCES["anvisa"]["url"]: (body, "text/html")}), "2026-10-21", "2026-11-03")
        self.assertEqual(h["status"], "failed")
        self.assertEqual(h["failure_type"], "dynamic_listing")

    def test_diagnostics_never_publish_exception_content(self):
        client = FakeClient({self.feed_url: ValueError("private-path/private-note: do not publish") ,
                             self.alt_url: ValueError("private-path/private-note: do not publish")})
        _, health = self.collect(client)
        self.assertNotIn("private-path", json.dumps(health))
        self.assertEqual(health["failure_type"], "parse_error")

    def test_feed_and_fallback_preserve_deduplication_identity(self):
        from incretin_watch.events import mark_emitted
        rss = FakeClient({self.feed_url: fixture("press.xml", "application/rss+xml"), ARTICLE_URL: fixture("article.html")})
        html = FakeClient({self.feed_url: FetchError("HTTP 404", "http_not_found", 404),
                           self.alt_url: fixture("press-listing.html"), ARTICLE_URL: fixture("article.html")})
        state = {"schema_version": 1, "documents": {}, "events": {}}
        groups, _, _ = stage_events(self.collect(rss)[0], CONFIG, state, "2026-10-21", "2026-11-03")
        mark_emitted(groups, state, "2026-11-03")
        replay, _, duplicates = stage_events(self.collect(html)[0], CONFIG, state, "2026-10-21", "2026-11-03")
        self.assertEqual(replay, [])
        self.assertEqual(duplicates, 1)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = Client(Path(self.tmp.name), ["fda.gov"], retries=2)
        self.client.opener = Mock()
        self.url = "https://www.fda.gov/test"

    def test_http_classification_and_no_access_retry(self):
        for status, expected in [(404, "http_not_found"), (403, "access_restricted"),
                                 (412, "access_restricted"), (429, "rate_limited")]:
            self.client.opener.reset_mock()
            self.client.opener.open.side_effect = HTTPError(self.url, status, "not logged", {}, io.BytesIO())
            with patch("incretin_watch.http.time.sleep") as sleep, self.assertRaises(FetchError) as caught:
                self.client.get(self.url)
            self.assertEqual(caught.exception.category, expected)
            self.assertEqual(self.client.opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_transient_server_error_uses_bounded_retry(self):
        self.client.opener.open.side_effect = HTTPError(self.url, 503, "Unavailable", {}, io.BytesIO())
        with patch("incretin_watch.http.time.sleep") as sleep, self.assertRaises(FetchError) as caught:
            self.client.get(self.url)
        self.assertEqual(self.client.opener.open.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(caught.exception.category, "http_server_error")

    def test_503_challenge_is_not_retried_as_a_server_failure(self):
        for body in (b"Access Denied", b"<html><title>Just a moment</title></html>"):
            with self.subTest(body=body):
                self.client.opener.reset_mock()
                self.client.opener.open.side_effect = HTTPError(self.url, 503, "Unavailable", {}, io.BytesIO(body))
                with patch("incretin_watch.http.time.sleep") as sleep, self.assertRaises(FetchError) as caught:
                    self.client.get(self.url)
                self.assertEqual(caught.exception.category, "access_restricted")
                self.assertEqual(self.client.opener.open.call_count, 1)
                sleep.assert_not_called()

    def test_rejected_source_url_is_not_published_in_diagnostics(self):
        source = dict(SOURCES["fda_press"], url="https://www.fda.gov/a?api_key=private-fixture")
        _, health = collect_source(source, CONFIG, self.client, "2026-10-21", "2026-11-03")
        self.assertNotIn("private-fixture", json.dumps(health))
        self.assertEqual(health["failure_type"], "policy_rejected")
        self.client.opener.open.assert_not_called()

    def test_long_retry_after_is_not_shortened(self):
        self.client.opener.open.side_effect = HTTPError(self.url, 503, "Unavailable", {"Retry-After": "60"}, io.BytesIO())
        with patch("incretin_watch.http.time.sleep") as sleep, self.assertRaises(FetchError):
            self.client.get(self.url)
        sleep.assert_not_called()
        self.assertEqual(self.client.opener.open.call_count, 1)

    def test_timeout_and_network_failure_are_distinct(self):
        for error, category in [(TimeoutError(), "timeout"), (URLError("DNS failure"), "network_error")]:
            self.client.opener.open.side_effect = error
            with patch("incretin_watch.http.time.sleep"), self.assertRaises(FetchError) as caught:
                self.client.get(self.url)
            self.assertEqual(caught.exception.category, category)

    def test_304_reuses_cache_but_403_never_serves_stale_cache(self):
        key = digest(self.url)
        (Path(self.tmp.name) / (key + ".bin")).write_bytes(b"cached")
        write_json(Path(self.tmp.name) / (key + ".json"), {"etag": "fixture", "mime": "text/html"})
        self.client.opener.open.side_effect = HTTPError(self.url, 304, "Not modified", {}, io.BytesIO())
        self.assertEqual(self.client.get(self.url), (b"cached", "text/html"))
        self.client.opener.open.side_effect = HTTPError(self.url, 403, "Forbidden", {}, io.BytesIO())
        with self.assertRaises(FetchError):
            self.client.get(self.url)

    def test_credentials_and_unsafe_redirects_are_rejected(self):
        for url in ["https://www.fda.gov/a?api_key=fixture", "https://user:fixture@www.fda.gov/a", "https://www.fda.gov:invalid/a"]:
            self.assertFalse(allowed_url(url, ["fda.gov"]))
        with self.assertRaises(FetchError):
            SafeRedirect(["fda.gov"]).redirect_request(None, None, 302, "", {}, "https://outside.example/a")


class ManualCommandTests(unittest.TestCase):
    def test_check_sources_does_not_read_or_mutate_state_or_reports(self):
        health = [{"id": "fda_press", "status": "partial", "accepted": 0, "warnings": ["bounded feed"]}]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            state = base / "state.json"
            state.write_text("intentionally not JSON: state must not even be read")
            reports = base / "reports"
            reports.mkdir()
            (reports / "latest.md").write_text("existing report")
            args = ["--config", str(ROOT / "config.json"), "--state", str(state), "--output", str(reports),
                    "--cache", str(base / "cache"), "--check-sources", "--strict-coverage"]
            before = state.read_bytes()
            with patch("incretin_watch.cli.collect", return_value=([], health)):
                self.assertEqual(main(args), 3)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual((reports / "latest.md").read_text(), "existing report")
            self.assertEqual(json.loads((reports / "coverage.json").read_text()), health)
            self.assertFalse((base / "cache/last-records.json").exists())

    def test_all_failed_normal_run_preserves_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            state = base / "state.json"
            state.write_text('{"schema_version":1,"documents":{},"events":{}}')
            before = state.read_bytes()
            with patch("incretin_watch.cli.collect", return_value=([], [{"id": "lilly", "status": "failed"}])):
                rc = main(["--config", str(ROOT / "config.json"), "--state", str(state), "--output", str(base / "reports"), "--cache", str(base / "cache")])
            self.assertEqual(rc, 2)
            self.assertEqual(state.read_bytes(), before)
            self.assertFalse((base / "reports/latest.md").exists())

    def test_installed_defaults_work_outside_repository(self):
        from importlib.resources import files
        self.assertEqual(json.loads(files("incretin_watch").joinpath("default_config.json").read_text()), CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                with patch("incretin_watch.cli.collect", return_value=([], [{"id": "lilly", "status": "ok"}])) as collect:
                    self.assertEqual(main(["--check-sources", "--sources", "lilly"]), 0)
                self.assertEqual(collect.call_args.args[0], CONFIG)
                self.assertFalse(Path("state").exists())
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
