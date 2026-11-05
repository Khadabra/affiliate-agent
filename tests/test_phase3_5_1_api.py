"""Tests for Phase 3.5.1 FastAPI and Telemetry Foundation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from affiliate_factory.api.app import create_app
from affiliate_factory.api.config import APISettings
from affiliate_factory.api.telemetry import TelemetryService
from affiliate_factory.db import Database


class TestApiFoundation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "api_test.db"
        self.settings = APISettings(
            host="127.0.0.1",
            port=8000,
            db_path=self.db_path,
            telemetry_cache_seconds=1.0,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health_endpoint(self) -> None:
        """GET /health must return 200 and report connected database with WAL mode."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "connected")
        self.assertIn("timestamp", data)
        self.assertEqual(data["journal_mode"], "wal")

    def test_system_info_endpoint(self) -> None:
        """GET /api/v1/system/info must return application metadata and local-only config."""
        response = self.client.get("/api/v1/system/info")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["app_name"], "AI Affiliate Content Factory")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["environment"], "local")
        self.assertEqual(data["host"], "127.0.0.1")
        self.assertEqual(data["worker_status"], "idle_not_started")
        self.assertEqual(data["api_cost_policy"], "zero_mandatory_cost")

    def test_system_resources_telemetry_endpoint(self) -> None:
        """GET /api/v1/system/resources must return valid CPU, memory, GPU, and disk telemetry."""
        response = self.client.get("/api/v1/system/resources")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check CPU fields
        self.assertIn("cpu", data)
        self.assertIsInstance(data["cpu"]["logical_cores"], int)
        self.assertGreater(data["cpu"]["logical_cores"], 0)

        # Check Memory fields
        self.assertIn("memory", data)
        self.assertIsInstance(data["memory"]["total_gb"], (int, float))
        self.assertGreater(data["memory"]["total_gb"], 0)

        # Check GPU fields
        self.assertIn("gpu", data)
        self.assertIn("available", data["gpu"])
        self.assertIsInstance(data["gpu"]["available"], bool)

        # Check Disk fields
        self.assertIn("disk", data)
        self.assertIn("drive", data["disk"])

    def test_telemetry_caching(self) -> None:
        """Rapid calls to TelemetryService must return cached data without re-sampling."""
        svc = TelemetryService(cache_ttl_seconds=5.0)
        t1 = svc.get_telemetry()
        t2 = svc.get_telemetry()
        self.assertEqual(t1.sampled_at, t2.sampled_at, "Rapid calls must share same sampled_at timestamp")

    def test_telemetry_gpu_fallback_when_unavailable(self) -> None:
        """When NVML is not available, GPU telemetry returns available=False gracefully."""
        svc = TelemetryService()
        svc._nvml_available = False
        sample = svc.get_telemetry(force_refresh=True)
        self.assertFalse(sample.gpu.available)
        self.assertIsNone(sample.gpu.name)
        self.assertIsNone(sample.gpu.vram_used_mb)

    def test_local_host_binding_invariant(self) -> None:
        """Host setting must be strictly 127.0.0.1."""
        settings = APISettings()
        self.assertEqual(settings.host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
