import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from server import copilot_chat as dashboard  # noqa: E402


class MobileSummaryJobTests(unittest.TestCase):
    def test_video_id_starting_with_dash_is_passed_as_option_value(self):
        cmd = dashboard.build_beecthor_summary_cmd(
            "-43_OhftDxk",
            Path("transcripts/-43_OhftDxk_2026-07-26.txt"),
        )

        self.assertIn("--video-id=-43_OhftDxk", cmd)
        self.assertNotIn("--video-id", cmd)


if __name__ == "__main__":
    unittest.main()
