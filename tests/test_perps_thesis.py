import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from scripts import summarize_beecthor as summary  # noqa: E402


class PerpsThesisTests(unittest.TestCase):
    def test_normalizes_valid_short_thesis(self):
        thesis = summary.normalize_perps_thesis(
            {
                "schema_version": 1,
                "symbol": "BTCUSDC",
                "video_id": "abc123",
                "generated_at": "2026-05-31T10:00:00Z",
                "valid_until": "2026-06-01T10:00:00Z",
                "macro_bias": "bearish",
                "preferred_setup": "short_resistance_bearish_regime",
                "confidence": 0.82,
                "short_zones": [
                    {
                        "low": 78000,
                        "high": 79000,
                        "stop_loss": 80100,
                        "targets": [75500, 73000],
                        "label": "VAH rejection",
                    }
                ],
                "long_zones": [],
                "invalidation_levels": [80100],
                "no_trade_conditions": [],
                "notes": "Wait for rejection.",
            },
            "abc123",
        )

        self.assertEqual(thesis["preferred_setup"], "short_resistance_bearish_regime")
        self.assertEqual(thesis["symbol"], "BTCUSDC")
        self.assertEqual(thesis["short_zones"][0]["targets"], [75500.0, 73000.0])
        self.assertEqual(thesis["long_zones"], [])

    def test_summary_schema_is_strict_for_perps_thesis(self):
        perps_schema = summary.SUMMARY_OUTPUT_SCHEMA["properties"]["perps_thesis"]

        self.assertIn("perps_tip", summary.SUMMARY_OUTPUT_SCHEMA["required"])
        self.assertEqual(perps_schema["additionalProperties"], False)
        self.assertEqual(perps_schema["properties"]["symbol"]["enum"], ["BTCUSDC"])
        self.assertEqual(
            perps_schema["properties"]["long_zones"]["items"]["additionalProperties"],
            False,
        )

    def test_falls_back_to_wait_when_setup_has_no_valid_zone(self):
        thesis = summary.normalize_perps_thesis(
            {
                "preferred_setup": "long_support_sweep_reclaim",
                "confidence": 0.9,
                "long_zones": [
                    {"low": 73000, "high": 73500, "stop_loss": 74000, "targets": [76000]},
                ],
            },
            "abc123",
        )

        self.assertEqual(thesis["preferred_setup"], "wait")
        self.assertEqual(thesis["long_zones"], [])
        self.assertTrue(thesis["no_trade_conditions"])

    def test_save_perps_thesis_writes_history_and_latest(self):
        original_dir = summary.PERPS_THESES_DIR
        original_latest = summary.LATEST_PERPS_THESIS_FILE
        with tempfile.TemporaryDirectory() as tmpdir:
            summary.PERPS_THESES_DIR = Path(tmpdir)
            summary.LATEST_PERPS_THESIS_FILE = Path(tmpdir) / "latest.json"
            try:
                history_path = summary.save_perps_thesis("abc123", {"preferred_setup": "wait"})
                self.assertTrue(history_path.exists())
                self.assertTrue(summary.LATEST_PERPS_THESIS_FILE.exists())
                latest = json.loads(summary.LATEST_PERPS_THESIS_FILE.read_text(encoding="utf-8"))
                self.assertEqual(latest["video_id"], "abc123")
                self.assertEqual(latest["preferred_setup"], "wait")
            finally:
                summary.PERPS_THESES_DIR = original_dir
                summary.LATEST_PERPS_THESIS_FILE = original_latest

    def test_summary_style_accepts_structured_spoiler(self):
        full_analysis = (
            "📊 <b>Situación actual</b>\nBTC está en zona de decisión.\n\n"
            "🎯 <b>Escenario principal</b>\nEsperar rechazo en resistencia.\n\n"
            "⚠️ <b>Niveles clave</b>\nSoporte 61.000; resistencia 65.000."
        )

        self.assertEqual(summary.count_summary_section_headings(full_analysis), 3)
        summary.validate_summary_style(full_analysis)

    def test_summary_style_rejects_unstructured_paragraph(self):
        full_analysis = (
            "El análisis plantea que BTC sigue dentro de una estructura correctiva bajista mayor, "
            "con zonas relevantes en <b>65.000</b> y <b>67.800</b>, pero sin separar los apartados."
        )

        with self.assertRaisesRegex(RuntimeError, "section format"):
            summary.validate_summary_style(full_analysis)


if __name__ == "__main__":
    unittest.main()
