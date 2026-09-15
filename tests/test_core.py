import tempfile
import unittest
from pathlib import Path

from zjjjzx.core.filters import Profile, deterministic_score, hard_filter, sort_key
from zjjjzx.core.parser import parse_listings
from zjjjzx.core.report import write_report
from zjjjzx.core.store import Store


SAMPLE = """
<div class="job-card" data-job-id="1" data-publish-date="2026-08-09 10:00:00"
 data-job-number="d100" data-salary="140元/次，2h" data-address="鄞州区某小区"
 data-teaching-mode="上门" data-grade="初5年级" data-subject="数学" data-gender="不限"
 data-teaching-time="周末下午" data-requirements="认真负责" data-is-fulltime="0">
 <div class="job-header"><h3 class="job-title">初5年级 - 数学</h3><span class="job-price">140元/次，2h</span></div>
 <div class="job-details"><span class="info-label">发布时间：</span><span class="info-value">2026-08-09</span></div>
</div>
"""


class ParserTests(unittest.TestCase):
    def test_parses_data_attributes(self):
        listings = parse_listings(SAMPLE, "https://zjjjzx.com/?city=宁波市")
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.external_id, "d100")
        self.assertEqual(listing.subject, "数学")
        self.assertEqual(listing.address, "鄞州区某小区")
        self.assertEqual(listing.price_value, 140)
        self.assertEqual(listing.detail_url, "https://zjjjzx.com/teacher/")


class FilterAndStoreTests(unittest.TestCase):
    def test_filter_and_deduplicate(self):
        listing = parse_listings(SAMPLE, "https://zjjjzx.com/")[0]
        profile = Profile(areas=("鄞州区",), subjects=("数学",), max_distance_meters=10000)
        passed, reason = hard_filter(listing, profile, 5000)
        self.assertTrue(passed, reason)
        extracted = {"hourly_rate_max": 70, "hourly_rate_min": 70, "grade_rank": 7}
        self.assertGreater(deterministic_score(extracted, 5000, 10000), 0)
        self.assertEqual(sort_key(extracted, 5000), (-70.0, -7.0, 5000))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "watcher.db"))
            try:
                self.assertTrue(store.upsert(listing))
                self.assertFalse(store.upsert(listing))
            finally:
                store.close()


class ReportTests(unittest.TestCase):
    def test_writes_complete_html_report(self):
        listing = parse_listings(SAMPLE, "https://zjjjzx.com/")[0]
        candidates = [
            {
                "listing": listing,
                "extracted": {"subject": "数学", "grade": "初5年级", "hourly_rate_min": 70, "hourly_rate_max": 70, "schedule_text": "周末下午"},
                "reason": "符合条件",
                "points": 42.5,
                "distance_meters": 5000,
            }
        ]
        rejected = [
            {"listing": listing, "stage": "硬过滤", "reason": "距离超出范围", "distance_meters": None},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = write_report(
                Path(directory) / "report.html",
                source_url="https://zjjjzx.com/",
                origin="浙江万里学院",
                max_distance_meters=10000,
                fetched=10,
                new_count=3,
                candidates=candidates,
                rejected=rejected,
            )
            content = path.read_text(encoding="utf-8")
        self.assertIn("d100", content)
        self.assertIn("原始详情", content)
        self.assertIn("认真负责", content)
        self.assertIn("70 元/时", content)
        self.assertIn("5.00 公里", content)
        self.assertIn("未入选 1 条", content)
        self.assertIn("距离超出范围", content)


if __name__ == "__main__":
    unittest.main()
