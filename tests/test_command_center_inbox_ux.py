import os
import tempfile
import time
import unittest
from pathlib import Path

from run_app import founder_report_events, humanize_ceo_text


class CommandCenterInboxUXTests(unittest.TestCase):
    def write_report(self, root: Path, relative: str, body: str, mtime: float) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_newest_canonical_report_sorts_first_even_if_old_file_was_touched_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_now = time.time()
            new_old_mtime = old_now - 10000
            self.write_report(
                root,
                "executive_reports/2026-08-17/eod_2026-08-17_20260817T160655-0400_eod-v1.1-canonical_final.md",
                "# Old EOD\n\n- Phase 3: ACTIVE\n",
                old_now,
            )
            self.write_report(
                root,
                "executive_reports/2026-08-19/eod_2026-08-19_20260819T160502-0400_eod-v1.1-canonical_final.md",
                "# New EOD\n\n- Phase 3: ACTIVE\n",
                new_old_mtime,
            )

            events = founder_report_events(root)

        self.assertEqual(events[0]["title"], "End-of-Day Executive Report — Aug 19, 2026")
        self.assertEqual(events[0]["ordering_source"], "canonical_report_generation_timestamp")
        self.assertEqual(events[1]["title"], "End-of-Day Executive Report — Aug 17, 2026")

    def test_duplicate_event_ids_are_not_present(self):
        events = founder_report_events()
        ids = [event["id"] for event in events]

        self.assertEqual(len(ids), len(set(ids)))

    def test_page_one_contains_newer_items_than_page_two(self):
        events = founder_report_events()
        page_one = events[:20]
        page_two = events[20:40]

        if page_two:
            self.assertGreaterEqual(page_one[-1]["ordering_timestamp_iso"], page_two[0]["ordering_timestamp_iso"])

    def test_human_readable_titles_are_generated_for_executive_reports(self):
        events = founder_report_events()
        eod = next(event for event in events if "eod" in event["path"].lower())
        opening = next(event for event in events if "opening" in event["path"].lower())

        self.assertRegex(eod["title"], r"End-of-Day Executive Report — [A-Z][a-z]{2} \d{1,2}, 20\d{2}")
        self.assertRegex(opening["title"], r"Opening Executive Report — [A-Z][a-z]{2} \d{1,2}, 20\d{2}")
        self.assertNotIn("202608", eod["title"])

    def test_humanize_preserves_ids_and_readablizes_statuses(self):
        self.assertEqual(humanize_ceo_text("P3-H006"), "P3-H006")
        self.assertEqual(humanize_ceo_text("QQQ"), "QQQ")
        self.assertEqual(humanize_ceo_text("WAITING_FOR_FORWARD_EVIDENCE"), "Waiting for Forward Evidence")
        self.assertEqual(humanize_ceo_text("autonomous_local_paper_research"), "Autonomous Paper Research")
        self.assertEqual(humanize_ceo_text("stop_loss_5m"), "5-Minute Stop Loss")

    def test_technical_metadata_remains_accessible(self):
        event = next(event for event in founder_report_events() if event["category"] == "Executive")
        details = event["technical_details"]

        self.assertIn("artifact_path", details)
        self.assertIn("report_revision", details)
        self.assertIn("canonical_source", details)
        self.assertIn("ordering_source", details)

    def test_js_pagination_and_filters_are_bounded(self):
        app_js = Path("app/app.js").read_text(encoding="utf-8")

        self.assertIn("const commandCenterInboxPageSize = 20;", app_js)
        self.assertIn("Page ${page} of ${totalPages}", app_js)
        self.assertIn("EXECUTIVE REPORTS", app_js)
        self.assertIn("ALERTS / ACTION REQUIRED", app_js)


if __name__ == "__main__":
    unittest.main()
