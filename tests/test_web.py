import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from zjjjzx.web import WebAppHandler


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Bind to port 0 to let OS assign an available port
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), WebAppHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str) -> tuple[int, dict | str]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in content_type:
                return resp.status, json.loads(raw.decode("utf-8"))
            return resp.status, raw.decode("utf-8")

    def _post(self, path: str, data: dict) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_serve_dashboard_index(self):
        status, html = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("zjjjzx 智能家教监控后台", html)
        self.assertIn("Allowed Subjects", html)

    def test_api_get_config(self):
        status, data = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertIn("config", data)
        self.assertIn("secrets", data)
        self.assertIn("validation_issues", data)

    def test_api_presets(self):
        status, data = self._get("/api/presets")
        self.assertEqual(status, 200)
        self.assertIn("presets", data)
        self.assertIn("science", data["presets"])
        self.assertIn("liberal_arts", data["presets"])

    def test_api_stats(self):
        status, data = self._get("/api/stats")
        self.assertEqual(status, 200)
        self.assertIn("stats", data)
        self.assertIn("total_listings", data["stats"])

    def test_api_candidates(self):
        status, data = self._get("/api/candidates")
        self.assertEqual(status, 200)
        self.assertIn("candidates", data)
        self.assertIsInstance(data["candidates"], list)

    def test_api_rejected(self):
        status, data = self._get("/api/rejected")
        self.assertEqual(status, 200)
        self.assertIn("rejected", data)
        self.assertIsInstance(data["rejected"], list)

    def test_api_runs(self):
        status, data = self._get("/api/runs")
        self.assertEqual(status, 200)
        self.assertIn("runs", data)
        self.assertIsInstance(data["runs"], list)

    def test_api_task_status(self):
        status, data = self._get("/api/task/status")
        self.assertEqual(status, 200)
        self.assertIn("is_running", data)
        self.assertIn("stage", data)
        self.assertIn("logs", data)

    def test_api_runtime_status(self):
        status, data = self._get("/api/runtime/status")
        self.assertEqual(status, 200)
        self.assertIn("supervisor", data)
        self.assertIn("task", data)
        self.assertIn("notifications", data)
        self.assertIn("is_enabled", data["supervisor"])

    def test_api_runtime_supervisor_lifecycle(self):
        from unittest.mock import patch
        from zjjjzx.web import SUPERVISOR

        with patch.object(SUPERVISOR, "_execute_pipeline_task"):
            # Start
            status, data = self._post("/api/runtime/supervisor", {
                "action": "start",
                "interval_minutes": 10,
                "force": True,
                "matcher_mode": "embedding",
            })
            self.assertEqual(status, 200)
            self.assertTrue(data["success"])
            self.assertTrue(data["supervisor"]["is_enabled"])
            self.assertEqual(data["supervisor"]["interval_minutes"], 10)

            # Status check
            status, check = self._get("/api/runtime/status")
            self.assertEqual(status, 200)
            self.assertTrue(check["supervisor"]["is_enabled"])

            # Stop
            status, stop_data = self._post("/api/runtime/supervisor", {"action": "stop"})
            self.assertEqual(status, 200)
            self.assertTrue(stop_data["success"])
            self.assertFalse(stop_data["supervisor"]["is_enabled"])


if __name__ == "__main__":
    unittest.main()
