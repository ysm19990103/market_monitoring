import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from incretin_watch.analyze import rules
from incretin_watch.cli import main
from incretin_watch.collect import collect_source, extract_page, feed_records, html_records, literature, novo_news
from incretin_watch.common import canonical_url, digest, matches, parse_date
from incretin_watch.events import classify, mark_emitted, prepare, same_event, stage_events
from incretin_watch.http import FetchError, allowed_url
from incretin_watch.report import render, safe_csv

CONFIG = json.loads((Path(__file__).parents[1] / "config.json").read_text())


def record(**kw):
    row = {"url": "https://www.fda.gov/news/test", "title": "FDA approves Wegovy for a new indication",
           "text": "The FDA approved Wegovy for a new indication. The decision applies to this product and population only.",
           "published_date": "2026-10-29", "modified_date": None, "source_type": "regulator",
           "source_id": "fda", "source_name": "FDA", "source_region": "US", "body_status": "fetched"}
    return dict(row, **kw)


class ParsingTests(unittest.TestCase):
    def test_url_keeps_identity(self):
        self.assertEqual(canonical_url("https://www.novonordisk.com/news.html?id=1&utm_source=x#more"),
                         "https://www.novonordisk.com/news.html?id=1")
        self.assertNotEqual(canonical_url("https://a.test/?id=1"), canonical_url("https://a.test/?id=2"))

    def test_dates_never_invent_day(self):
        self.assertIsNone(parse_date("October 2026"))
        self.assertIsNone(parse_date("2026"))
        self.assertEqual(parse_date("Thu, 29 Oct 2026 12:05:31 GMT"), "2026-10-29")
        self.assertEqual(parse_date("2026年10月29日"), "2026-10-29")

    def test_no_global_footer_date(self):
        x = extract_page(b'<main><h1>Wegovy</h1><p>A trial was completed on October 20, 2026.</p></main><footer>2026-10-30</footer>', "text/html")
        self.assertIsNone(x["published_date"])
        self.assertNotIn("2026-10-30", x["text"])

    def test_dates_remain_distinct(self):
        b = b'<meta property="article:published_time" content="2026-10-29"><meta property="article:modified_time" content="2026-10-30"><main>Wegovy update</main>'
        x = extract_page(b, "text/html")
        self.assertEqual(x["published_date"], "2026-10-29")
        self.assertEqual(x["modified_date"], "2026-10-30")

    def test_fda_current_as_of_is_not_publication(self):
        x = extract_page(b'<main><h1>FDA update</h1><div>Content current as of:<p><time datetime="2026-10-01T00:00:00Z">10/01/2026</time></p></div></main>', 'text/html')
        self.assertEqual(x['modified_date'], '2026-10-01')
        self.assertIsNone(x['published_date'])

    def test_semaglutide_does_not_assign_all_brands(self):
        mol, brands, _ = matches("semaglutide results", CONFIG)
        self.assertIn("semaglutide", mol)
        self.assertEqual(brands, [])

    def test_atom_and_bad_feed(self):
        b = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>MHRA</title><entry><title>Wegovy safety</title><link href="https://www.gov.uk/a"/><updated>2026-10-29T12:00:00Z</updated></entry></feed>'
        r = feed_records(b, {})[0]
        self.assertIsNone(r["published_date"])
        self.assertEqual(r["modified_date"], "2026-10-29")
        with self.assertRaises(FetchError):
            feed_records(b'<html>Blocked</html>', {})

    def test_domain_boundary(self):
        self.assertTrue(allowed_url("https://www.fda.gov/a", ["fda.gov"]))
        for url in ["https://fda.gov.evil.test/a", "http://fda.gov/a", "https://user:secret@fda.gov/a", "https://127.0.0.1/a"]:
            self.assertFalse(allowed_url(url, ["fda.gov"]))


class EvidenceTests(unittest.TestCase):
    def test_chmp_not_approval(self):
        self.assertEqual(classify("CHMP adopts positive opinion for Foundayo", "")[1], "positive_opinion")
        self.assertEqual(classify("FDA approves Foundayo", "")[1], "approval_report")

    def test_approved_comparator_dose_is_not_new_approval(self):
        self.assertEqual(classify("Retatrutide beat Ozempic's highest approved dose in head-to-head trial", "")[1], "results_report")

    def test_financial_results_not_trial_results(self):
        self.assertEqual(classify("Lilly reports third-quarter financial results", "")[1], "financial_report")

    def test_untagged_reviews_excluded_chart_review_retained(self):
        self.assertIsNone(prepare(record(source_type="research", title="Semaglutide: A Review."), CONFIG))
        self.assertIsNotNone(prepare(record(source_type="research", title="A retrospective chart review of semaglutide", text="A retrospective cohort study included 500 patients receiving semaglutide."), CONFIG))

    def test_preview_not_results(self):
        self.assertEqual(classify("Novo to present Wegovy results", "")[1], "conference_preview")

    def test_rules_explicitly_conditional(self):
        r = prepare(record(), CONFIG)
        a = rules({"representative": r, "sources": [r]})
        self.assertEqual(a["mode"], "rules")
        self.assertTrue(a["needs_review"])
        self.assertEqual(len(a["impacts"]), 3)

    def test_csv_formula_injection(self):
        self.assertTrue(safe_csv("=HYPERLINK(1)").startswith("'"))


class DedupTests(unittest.TestCase):
    def setUp(self):
        self.state = {"schema_version": 1, "documents": {}, "events": {}}

    def test_second_run_idempotent(self):
        groups, _, _ = stage_events([record()], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(len(groups), 1)
        mark_emitted(groups, self.state, "2026-10-30")
        groups2, _, n = stage_events([record()], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(groups2, [])
        self.assertEqual(n, 1)

    def test_changed_numbers_retained(self):
        g, _, _ = stage_events([record()], CONFIG, self.state, "2026-10-16", "2026-10-30")
        mark_emitted(g, self.state, "2026-10-30")
        new = record(text="The FDA approved Wegovy for a new indication in adults aged 55 and older. This label was revised.")
        g2, _, _ = stage_events([new], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(len(g2), 1)
        self.assertIn("update_note", g2[0]["representative"])

    def test_distinct_jurisdiction_not_merged(self):
        a = prepare(record(), CONFIG)
        b = prepare(record(source_region="EU", url="https://www.ema.europa.eu/a"), CONFIG)
        self.assertFalse(same_event(a, b))

    def test_new_trial_followup_not_merged(self):
        a = prepare(record(title="Wegovy trial 52 week results"), CONFIG)
        b = prepare(record(title="Wegovy trial 104 week results"), CONFIG)
        self.assertFalse(same_event(a, b))

    def test_same_doi_grouped(self):
        a = prepare(record(source_type="research", doi="10.1/example", title="Semaglutide randomized trial"), CONFIG)
        b = copy.deepcopy(a)
        b["url"] = "https://pubmed.ncbi.nlm.nih.gov/2"
        self.assertTrue(same_event(a, b))

    def test_undated_quarantined(self):
        g, review, _ = stage_events([record(published_date=None)], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(g, [])
        self.assertEqual(len(review), 1)

    def test_date_recovered_after_undated_baseline(self):
        stage_events([record(published_date=None)], CONFIG, self.state, "2026-10-16", "2026-10-30")
        g, _, _ = stage_events([record()], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(len(g), 1)

    def test_duplicate_url_across_feeds(self):
        g, _, _ = stage_events([record(), record(source_id="fda2")], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(len(g), 1)

    def test_new_result_without_repeating_drug_name_retained(self):
        old = record(text="Wegovy was studied in adults. The primary endpoint was reduced by 10 percent.")
        g, _, _ = stage_events([old], CONFIG, self.state, "2026-10-16", "2026-10-30")
        mark_emitted(g, self.state, "2026-10-30")
        updated = record(text="Wegovy was studied in adults. The primary endpoint was reduced by 20 percent.")
        g, _, _ = stage_events([updated], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(len(g), 1)

    def test_failed_fetch_retry_not_acknowledged(self):
        g, review, _ = stage_events([record(body_status="unavailable")], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertEqual(g, [])
        self.assertFalse(self.state["documents"])

    def test_historical_notice_not_new(self):
        g, _, _ = stage_events([record(published_date="2025-01-01")], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertFalse(g)

    def test_future_publication_quarantined(self):
        g, review, _ = stage_events([record(published_date="2026-11-01")], CONFIG, self.state, "2026-10-16", "2026-10-30")
        self.assertFalse(g)
        self.assertTrue(review)


class AdapterTests(unittest.TestCase):
    def test_failure_visible(self):
        class Broken:
            def get(self, url):
                raise FetchError("HTTP 412")
        s = next(s for s in CONFIG["sources"] if s["id"] == "nmpa")
        rows, h = collect_source(s, CONFIG, Broken(), "2026-10-16", "2026-10-30")
        self.assertFalse(rows)
        self.assertEqual(h["status"], "failed")

    def test_literature_pagination_and_review_exclusion(self):
        class Fake:
            def __init__(self): self.n = 0
            def get(self, url):
                self.n += 1
                items = [{"id": "1", "title": "Semaglutide trial", "firstPublicationDate": "2026-10-20", "pubTypeList": {"pubType": ["Randomized Controlled Trial"]}},
                         {"id": "2", "pubTypeList": {"pubType": ["Review"]}}] if self.n == 1 else []
                return json.dumps({"hitCount": 2, "nextCursorMark": "next", "resultList": {"result": items}}).encode(), "application/json"
        fake = Fake()
        src = next(s for s in CONFIG["sources"] if s["id"] == "europepmc")
        rows, warnings = literature(fake, src, CONFIG, "2026-10-16", "2026-10-30")
        self.assertEqual(len(rows), 1)
        self.assertEqual(fake.n, 2)

    def test_novo_api(self):
        class Fake:
            def get(self, url):
                return json.dumps({"status": 200, "data": {"numberOfResults": 1, "resultBeanList": [
                    {"id": 17, "title": "Wegovy results", "date": "2026-10-29T12:00:00.000", "newsContent": "<p>Reported results</p>"}]}}).encode(), "application/json"
        src = next(s for s in CONFIG["sources"] if s["id"] == "novo")
        rows, _ = novo_news(Fake(), src, "2026-10-16", "2026-10-30")
        self.assertIn("?id=17", rows[0]["url"])
        self.assertEqual(rows[0]["published_date"], "2026-10-29")


class CommandTests(unittest.TestCase):
    def test_default_run_analyzes_locally_and_replay_deduplicates(self):
        health = [{"id": "fda", "name": "FDA", "url": "https://www.fda.gov",
                   "region": "US", "status": "ok", "accepted": 1, "warnings": []}]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            args = ["--config", str(Path(__file__).parents[1] / "config.json"),
                    "--state", str(base / "state.json"), "--output", str(base / "reports"),
                    "--cache", str(base / "cache"), "--as-of", "2026-10-30"]
            # Collection is supplied as a fixture; downstream analysis must be local.
            with patch("incretin_watch.cli.collect", return_value=([record()], health)), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network call")), \
                 patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Unexpected network call")), \
                 patch("os.getenv", side_effect=AssertionError("Unexpected environment lookup")):
                self.assertEqual(main(args), 0)
                report = json.loads((base / "reports/latest.json").read_text())
                self.assertEqual(len(report["events"]), 1)
                event = report["events"][0]
                self.assertEqual(event["analysis"]["mode"], "rules")
                self.assertEqual(set(event["analysis"]["impacts"]),
                                 {"competitiveness", "clinical_use", "future_market"})
                self.assertEqual(event["sources"][0]["url"], record()["url"])
                self.assertTrue(event["analysis"]["needs_review"])
                self.assertIn("本地规则分析", (base / "reports/latest.md").read_text())
                self.assertEqual(main(args + ["--analysis", "rules"]), 0)
                replay = json.loads((base / "reports/latest.json").read_text())
                self.assertEqual(replay["events"], [])
                self.assertEqual(replay["metadata"]["duplicates"], 1)
                self.assertEqual(len(json.loads((base / "state.json").read_text())["events"]), 1)

    def test_unsupported_analysis_rejected_before_collection(self):
        with patch("incretin_watch.cli.collect") as collect, patch("sys.stderr"):
            with self.assertRaises(SystemExit) as caught:
                main(["--analysis", "remote"])
        self.assertEqual(caught.exception.code, 2)
        collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
