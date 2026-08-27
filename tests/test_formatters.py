import unittest

from flotte.formatters import display_web_url, format_git_status, format_web_url
from flotte.models import GitStatus
from flotte.theme import DEFAULT_COLORS


class FormatterTests(unittest.TestCase):
    def test_format_web_url_strips_scheme_and_preserves_empty_marker(self) -> None:
        self.assertEqual(
            format_web_url("http://localhost:3000").plain, "localhost:3000"
        )
        self.assertEqual(display_web_url("https://localhost:3000"), "localhost:3000")
        self.assertEqual(format_web_url(None, empty="-").plain, "-")

    def test_format_git_status_supports_list_and_detail_forms(self) -> None:
        changed = GitStatus(staged=1, unstaged=2)
        clean = GitStatus()

        self.assertEqual(format_git_status(changed, DEFAULT_COLORS).plain, "+1 ~2 ")
        self.assertEqual(
            format_git_status(clean, DEFAULT_COLORS, prefix="· ").plain,
            "· clean",
        )
