import tempfile
import unittest
from pathlib import Path

from zjjjzx.config import evaluation_scope, load_config, make_profile, validate_config
from zjjjzx.core.parser import Listing
from zjjjzx.core.store import Store


class ConfigTests(unittest.TestCase):
    def test_load_and_profile(self):
        config = load_config()
        self.assertIn("source", config)
        profile = make_profile(config)
        self.assertIsInstance(profile.areas, tuple)
        self.assertIsInstance(profile.subjects, tuple)
        scope = evaluation_scope(config)
        self.assertEqual(len(scope), 64)  # SHA-256 hex string

    def test_validate_config(self):
        issues = validate_config({})
        self.assertTrue(any("source.url" in issue for issue in issues))


class StoreHelperTests(unittest.TestCase):
    def test_extended_store_queries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "test.db")
            store = Store(db_path)
            try:
                listing = Listing(
                    external_id="cand_1",
                    site_job_id="101",
                    title="高一数学辅导",
                    grade="高一",
                    subject="数学",
                    price_text="120元/小时",
                    price_value=120,
                    address="鄞州区测试小区",
                    teaching_mode="上门",
                    gender="男",
                    teaching_time="周六上午",
                    requirements="经验丰富",
                    publish_date="2026-09-01",
                    detail_url="https://zjjjzx.com/teacher/",
                    raw_text="原文内容",
                )
                store.upsert(listing)
                store.save_evaluation("cand_1", {
                    "hard_pass": True,
                    "llm_pass": True,
                    "llm_reason": "符合全部条件",
                    "score": 55.0,
                    "extracted": {"hourly_rate_min": 120, "hourly_rate_max": 120},
                })
                store.save_map_cache("鄞州区测试小区", 29.8, 121.5, 4500)

                candidates = store.get_candidates()
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["external_id"], "cand_1")
                self.assertEqual(candidates[0]["score"], 55.0)
                self.assertEqual(candidates[0]["distance_meters"], 4500)

                store.mark_notified("cand_1", True)
                cand_after = store.get_candidates()
                self.assertTrue(cand_after[0]["notified"])

                stats = store.get_stats()
                self.assertEqual(stats["total_listings"], 1)
                self.assertEqual(stats["candidates"], 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
