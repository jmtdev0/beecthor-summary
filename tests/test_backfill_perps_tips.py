import json
import tempfile
import unittest
from pathlib import Path

from scripts import backfill_perps_tips as backfill


def historical_message(levels: str = "65.000 y 63.000") -> str:
    return (
        "🎯 <b>Beecthor — Último vídeo</b>\n\n"
        f"📌 <b>Resumen</b>\nNiveles relevantes: {levels}.\n\n"
        "🧭 <b>Visión macro</b>\nSesgo bajista.\n\n"
        "🔍 <b>Análisis completo</b>\n"
        "<tg-spoiler>Esperar rechazo antes de operar.</tg-spoiler>"
    )


class BackfillPerpsTipTests(unittest.TestCase):
    def test_selects_only_target_months_without_tip(self):
        entries = [
            {"timestamp": "2026-04-01T10:00:00Z", "message": historical_message()},
            {
                "timestamp": "2026-05-01T10:00:00Z",
                "message": f"{backfill.TIP_MARKER}\nManos quietas.\n\n{historical_message()}",
            },
            {"timestamp": "2026-07-01T10:00:00Z", "message": historical_message()},
        ]

        targets = backfill.missing_tip_entries(entries, backfill.DEFAULT_MONTHS)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["timestamp"][:10], "2026-04-01")

    def test_validates_levels_with_equivalent_notation(self):
        source = "BTC puede rechazar 65.000 y buscar después 63k."
        tip = "Si BTC rechaza 65k, el setup sería buscar short hacia 63.000."

        self.assertEqual(backfill.validate_tip(tip, source), [])
        self.assertEqual(backfill.extract_price_levels(source), {65000, 63000})

    def test_rejects_invented_levels_html_and_hindsight(self):
        source = "BTC vigila 65.000 y 63.000."

        invented = backfill.validate_tip(
            "Si BTC rechaza 65.000, buscar short hacia 58.000.",
            source,
        )
        html_errors = backfill.validate_tip(
            "Si BTC rechaza <b>65.000</b>, buscar short hacia 63.000.",
            source,
        )
        hindsight = backfill.validate_tip(
            "Como ya sabemos, finalmente bajó; manos quietas.",
            source,
        )

        self.assertTrue(any("absent" in error for error in invented))
        self.assertIn("tip contains HTML", html_errors)
        self.assertIn("tip contains hindsight language", hindsight)

    def test_accepts_explicit_wait_instruction(self):
        tip = "Ahora mismo no hay una apertura clara de long o short; manos quietas."

        self.assertEqual(backfill.validate_tip(tip, "Tesis ambigua sin niveles."), [])

    def test_orders_partial_manifest_without_requiring_future_entries(self):
        targets = [{"video_id": "first"}, {"video_id": "second"}]
        first = {"video_id": "first", "status": "valid"}

        ordered = backfill.ordered_manifest_entries(targets, {"first": first})

        self.assertEqual(ordered, [first])

    def test_insertion_preserves_original_message_bytes(self):
        message = historical_message()
        tip = "Si BTC rechaza 65.000, buscar short hacia 63.000."

        updated, inserted = backfill.insert_perps_tip(message, tip)
        inserted_block = f"{backfill.TIP_MARKER}\n{tip}\n\n"

        self.assertTrue(inserted)
        self.assertEqual(updated.replace(inserted_block, "", 1), message)
        self.assertLess(updated.index(backfill.TIP_MARKER), updated.index(backfill.MACRO_MARKER))
        self.assertEqual(backfill.insert_perps_tip(updated, tip), (updated, False))

    def test_apply_is_atomic_and_idempotent(self):
        video_id = "fixture-video"
        tip = "Si BTC rechaza 65.000, buscar short hacia 63.000."
        original_entry = {
            "timestamp": "2026-04-01T10:00:00Z",
            "video_id": video_id,
            "message": historical_message(),
        }
        existing_entry = {
            "timestamp": "2026-06-15T10:00:00Z",
            "video_id": "already-done",
            "message": f"{backfill.TIP_MARKER}\nTip existente.\n\n{historical_message()}",
        }
        manifest = {
            "schema_version": 1,
            "months": list(backfill.DEFAULT_MONTHS),
            "entries": [
                {
                    "video_id": video_id,
                    "date": "2026-04-01",
                    "source_kind": "summary_only",
                    "status": "valid",
                    "perps_tip": tip,
                    "attempts": 1,
                    "validation_errors": [],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = root / "analyses_log.json"
            manifest_path = root / "manifest.json"
            transcripts_dir = root / "transcripts"
            transcripts_dir.mkdir()
            backfill.atomic_write_json(log_path, [original_entry, existing_entry])
            backfill.atomic_write_json(manifest_path, manifest)

            changed = backfill.apply_manifest(
                log_path,
                transcripts_dir,
                manifest_path,
                backfill.DEFAULT_MONTHS,
                expected_count=1,
            )
            first_result = log_path.read_bytes()
            second_changed = backfill.apply_manifest(
                log_path,
                transcripts_dir,
                manifest_path,
                backfill.DEFAULT_MONTHS,
                expected_count=1,
            )

            applied_entries = json.loads(first_result.decode("utf-8"))
            self.assertEqual(changed, 1)
            self.assertEqual(second_changed, 0)
            self.assertEqual(log_path.read_bytes(), first_result)
            self.assertIn(tip, applied_entries[0]["message"])
            self.assertEqual(applied_entries[1], existing_entry)


if __name__ == "__main__":
    unittest.main()
