import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from server import copilot_chat as dashboard  # noqa: E402


class DashboardPerpsTipTests(unittest.TestCase):
    def test_extracts_perps_tip_without_following_sections(self):
        message = (
            "⚡ <b>Perps Tip</b>\n"
            "Si BTC recupera 65.000, buscar long hacia 67.000.\n\n"
            "🧭 <b>Visión macro</b>\nSesgo neutral."
        )

        self.assertEqual(
            dashboard.extract_perps_tip_html(message),
            "Si BTC recupera 65.000, buscar long hacia 67.000.",
        )

    def test_latest_summary_renders_perps_tip_before_summary(self):
        latest = dashboard.load_summary_entries()[0]
        self.assertTrue(latest["perps_tip_html"])

        response = dashboard.app.test_client().get(f"/videos/{latest['video_id']}")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(latest["perps_tip_html"], page)
        self.assertLess(page.index("Perps Tip"), page.index("Resumen visible"))

    def test_public_api_exposes_perps_tip(self):
        response = dashboard.app.test_client().get("/api/public/summaries")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload[0]["perps_tip_html"])


if __name__ == "__main__":
    unittest.main()
