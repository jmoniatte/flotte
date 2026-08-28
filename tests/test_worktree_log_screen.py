from datetime import timedelta, timezone
import unittest

from flotte.screens.worktree_log import _format_local_timestamp


class WorktreeLogScreenTests(unittest.TestCase):
    def test_formats_utc_timestamp_in_requested_timezone(self) -> None:
        pacific_daylight_time = timezone(timedelta(hours=-7), "PDT")

        self.assertEqual(
            _format_local_timestamp("2026-08-27T12:34:56Z", pacific_daylight_time),
            "2026-08-27 05:34:56",
        )

    def test_rejects_invalid_or_timezone_less_timestamps(self) -> None:
        self.assertIsNone(_format_local_timestamp("invalid"))
        self.assertIsNone(_format_local_timestamp("2026-08-27T12:34:56"))
