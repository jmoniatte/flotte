import os
import unittest

from flotte.services.process_identity import capture_process_identity, matches_process_identity


class ProcessIdentityTests(unittest.TestCase):
    def test_current_process_identity_is_stable_and_rejects_a_changed_start_time(self) -> None:
        identity = capture_process_identity(os.getpid())

        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertTrue(matches_process_identity(identity))

        identity["started_at"] = "different"
        self.assertFalse(matches_process_identity(identity))
