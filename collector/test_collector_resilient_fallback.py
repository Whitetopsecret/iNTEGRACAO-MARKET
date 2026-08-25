import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from collector import coletor_v1
from collector.coletor_v1 import build_round_timestamp, build_simulated_round, extract_multiplier_candidates


class CollectorFallbackTests(unittest.TestCase):
    def test_extract_multiplier_candidates_from_payload(self):
        payload = {"data": {"stats": [1.25, 2.5, 3.75]}}
        self.assertEqual(extract_multiplier_candidates(payload), [1.25, 2.5, 3.75])

    def test_build_simulated_round_uses_fallback_when_real_call_fails(self):
        round_data = build_simulated_round(error_message="INVALID SESSION ID")
        self.assertEqual(round_data["source"], "simulado")
        self.assertGreaterEqual(round_data["multiplier"], 1.0)
        self.assertLessEqual(round_data["multiplier"], 1000.0)

    def test_extract_multiplier_candidates_from_real_stats_payload(self):
        payload = {
            "classification": {"sm": 49, "md": 27, "lg": 8, "xl": 0},
            "timeFrameInMinutes": 3.45,
        }
        self.assertEqual(extract_multiplier_candidates(payload), [3.45])

    def test_fetch_round_with_fallback_uses_real_stats_payload(self):
        class DummyResponse:
            status = 200

            def read(self):
                return json.dumps({
                    "classification": {"sm": 49, "md": 27, "lg": 8, "xl": 0},
                    "timeFrameInMinutes": 3.45,
                }).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(coletor_v1, "build_request_url", return_value="https://example.test"), \
             patch.object(coletor_v1, "build_request_headers", return_value={}), \
             patch.object(coletor_v1, "build_request_payload", return_value={}), \
             patch.object(coletor_v1, "urlopen", return_value=DummyResponse()):
            round_data = coletor_v1.fetch_round_with_fallback("https://example.test")

        self.assertEqual(round_data["source"], "api")
        self.assertEqual(round_data["multiplier"], 3.45)

    def test_fetch_round_with_fallback_uses_simulation_when_api_times_out(self):
        with patch.object(coletor_v1, "build_request_url", return_value="https://example.test"), \
             patch.object(coletor_v1, "build_request_headers", return_value={}), \
             patch.object(coletor_v1, "build_request_payload", return_value={}), \
             patch.object(coletor_v1, "urlopen", side_effect=TimeoutError("The read operation timed out")):
            round_data = coletor_v1.fetch_round_with_fallback("https://example.test")

        self.assertEqual(round_data["source"], "simulado")
        self.assertGreaterEqual(round_data["multiplier"], 1.0)
        self.assertLessEqual(round_data["multiplier"], 1000.0)

    def test_build_round_timestamp_includes_exact_seconds(self):
        dt = datetime(2024, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)
        self.assertEqual(build_round_timestamp(dt), "2024-01-02T03:04:05+00:00")

    def test_build_request_payload_includes_sid_for_real_session(self):
        with patch.object(coletor_v1, "REAL_STATS_SID", "abc123"), patch.object(coletor_v1, "REAL_STATS_SESSION_ID", ""):
            payload = coletor_v1.build_request_payload()

        self.assertEqual(payload.get("sid"), "abc123")
        self.assertEqual(payload.get("sessionId"), "abc123")


if __name__ == "__main__":
    unittest.main()
