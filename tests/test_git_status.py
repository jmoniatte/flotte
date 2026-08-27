import unittest

from flotte.models import GitStatus
from flotte.services.git_status import parse_porcelain


class GitStatusTests(unittest.TestCase):
    def test_parse_porcelain_counts_every_changed_state(self) -> None:
        output = "\n".join(
            (
                "M  staged.py",
                " M modified.py",
                " D deleted.py",
                "R  renamed.py -> moved.py",
                " T type-changed.py",
                "UU conflicted.py",
                "?? untracked.py",
                "!! ignored.py",
            )
        )

        self.assertEqual(
            parse_porcelain(output),
            GitStatus(staged=3, unstaged=4, untracked=1),
        )

    def test_has_changes_ignores_upstream_divergence(self) -> None:
        clean = GitStatus(ahead=2, behind=1)
        changed = GitStatus(unstaged=1, ahead=2)

        self.assertFalse(clean.has_changes)
        self.assertTrue(changed.has_changes)
