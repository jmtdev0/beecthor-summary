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

        for field in summary.SHORT_SUMMARY_FIELDS:
            self.assertIn(field, summary.SUMMARY_OUTPUT_SCHEMA["required"])
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

    def test_normalize_summary_payload_cleans_short_fields(self):
        short_summary, thesis = summary.normalize_summary_payload(
            {
                "expected_move": "• que siga <b>bajando</b> hasta 70.000 $.",
                "if_lower": "rebote en 66.700 $.",
                "if_higher": "recupera 81.000 $.",
                "his_plan": "esperar.",
                "long_term": "sigue siendo alcista.",
                "perps_thesis": {"preferred_setup": "wait"},
            },
            "abc123",
        )

        self.assertEqual(short_summary["expected_move"], "que siga bajando hasta 70.000 $.")
        self.assertEqual(thesis["preferred_setup"], "wait")

    def test_normalize_summary_payload_rejects_missing_fields(self):
        with self.assertRaisesRegex(RuntimeError, "missing required summary fields"):
            summary.normalize_summary_payload({"expected_move": "subir."}, "abc123")

    def test_build_message_escapes_llm_text_for_telegram_html(self):
        message = summary.build_message(
            video_id="abc123",
            prices_now={"btc_usd": 63000, "btc_eur": 59000, "sol_usd": 140, "sol_eur": 131},
            prices_yesterday={"btc_usd": 64000, "btc_eur": 60000},
            short_summary={
                "expected_move": "que baje si BTC < 60.000 & haya volatilidad.",
                "if_lower": "rebote en 58.000 $.",
                "if_higher": "recupera 65.000 $.",
                "his_plan": "esperar.",
                "long_term": "alcista.",
            },
        )

        self.assertIn("👉 <b>Qué espera:</b> que baje si BTC &lt; 60.000 &amp; haya volatilidad.", message)
        self.assertIn("BTC ahora: <b>63.000 $</b> (-1,6 % desde ayer)", message)
        self.assertIn("🧭 <b>A largo plazo:</b> alcista.", message)
        self.assertNotIn("Análisis completo", message)

    def test_compact_telegram_message_keeps_visible_summary(self):
        message = (
            "🎯 <b>Beecthor — Último vídeo</b>\n\n"
            "📌 <b>Resumen</b>\nResumen visible.\n\n"
            "🔍 <b>Análisis completo</b> <i>(toca para ver)</i>\n"
            f"<tg-spoiler>{'Detalle largo. ' * 500}</tg-spoiler>"
        )

        compact = summary.compact_telegram_message(message, max_chars=500)

        self.assertLessEqual(len(compact), 500)
        self.assertIn("Resumen visible.", compact)
        self.assertIn("Resumen completo disponible en la aplicación Flask.", compact)


if __name__ == "__main__":
    unittest.main()
