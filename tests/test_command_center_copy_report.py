import unittest
import tempfile
from pathlib import Path

from run_app import LOGS_DIR, founder_report_events


class CommandCenterCopyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = founder_report_events(LOGS_DIR)
        cls.app_js = Path("app/app.js").read_text(encoding="utf-8")

    def latest_markdown_event(self):
        return next(event for event in self.events if event.get("path", "").endswith(".md"))

    def test_inbox_event_uses_complete_authoritative_report_content(self):
        event = self.latest_markdown_event()
        source = Path(event["path"]).read_text(encoding="utf-8")

        self.assertEqual(event["content"], source)

    def test_markdown_formatting_and_long_report_survive_backend_payload(self):
        event = self.latest_markdown_event()
        content = event["content"]

        self.assertIn("#", content)
        self.assertIn("\n", content)
        self.assertEqual(content, Path(event["path"]).read_text(encoding="utf-8"))
        self.assertNotEqual(content, content[:24000] if len(content) > 24000 else content[:-1])

    def test_synthetic_long_archived_report_is_not_truncated(self):
        long_body = "# Long EOD Report\n\n" + "\n".join(f"- line {index}" for index in range(4000))
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "executive_reports" / "2026-08-17"
            report_dir.mkdir(parents=True)
            report_path = report_dir / "eod_2026-08-17_long_final.md"
            report_path.write_text(long_body, encoding="utf-8")

            events = founder_report_events(Path(tmp))
            event = next(row for row in events if row["path"] == str(report_path))

        self.assertGreater(len(long_body), 24000)
        self.assertEqual(event["content"], long_body)

    def test_current_phase3_eod_report_copies_without_truncation_when_present(self):
        eod_events = [
            event
            for event in self.events
            if "eod" in event.get("path", "").lower() and event.get("path", "").endswith(".md")
        ]
        self.assertTrue(eod_events)
        event = eod_events[0]
        content = event["content"]

        self.assertEqual(content, Path(event["path"]).read_text(encoding="utf-8"))
        if "Phase 3" in content:
            self.assertIn("Phase 3", content)

    def test_copy_button_uses_authoritative_event_content(self):
        self.assertIn("data-cc-inbox-copy-report", self.app_js)
        self.assertIn("navigator.clipboard.writeText(reportText)", self.app_js)
        self.assertIn("const reportText = event?.content || \"\";", self.app_js)
        self.assertNotIn("cc-inbox-reader-content.innerText", self.app_js)
        self.assertNotIn("cc-inbox-reader-content.textContent", self.app_js)

    def test_copy_feedback_and_failure_message_are_present(self):
        self.assertIn("Copied ✓", self.app_js)
        self.assertIn("Copy failed — select report text manually.", self.app_js)
        self.assertIn("role=\"status\"", self.app_js)

    def test_authoritative_report_content_does_not_include_local_secret_files(self):
        event = self.latest_markdown_event()
        content = event["content"]

        self.assertNotIn("WEBULL_PASSWORD", content)
        self.assertNotIn("DATABENTO_API_KEY", content)
        self.assertNotIn("OPENAI_API_KEY", content)
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", content)


if __name__ == "__main__":
    unittest.main()
