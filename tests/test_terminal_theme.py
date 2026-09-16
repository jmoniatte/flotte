import io
import os
import pty
import threading
import unittest

from flotte.terminal_theme import (
    light_background,
    parse_replies,
    query_terminal,
    report_from_terminal,
    scheme_from_terminal,
)
from flotte.theme import contrast_ratio, hex_color, palette_from_scheme

BG, FG = (0x28, 0x2C, 0x34), (0xAB, 0xB2, 0xBF)
ANSI = {
    1: (0xE0, 0x6C, 0x75),
    2: (0x98, 0xC3, 0x79),
    3: (0xE5, 0xC0, 0x7B),
    4: (0x61, 0xAF, 0xEF),
    5: (0xC6, 0x78, 0xDD),
    6: (0x56, 0xB6, 0xC2),
    8: (0x54, 0x58, 0x62),
    15: (0xC8, 0xCC, 0xD4),
}
# Catppuccin latte as a terminal preset: a light ramp, with base16's own
# base01 #e6e9ef and base02 #ccd0da as the surfaces to land near.
LATTE_BG, LATTE_FG = (0xEF, 0xF1, 0xF5), (0x4C, 0x4F, 0x69)
LATTE_ANSI = {
    1: (0xD2, 0x0F, 0x39),
    2: (0x40, 0xA0, 0x2B),
    3: (0xDF, 0x8E, 0x1D),
    4: (0x1E, 0x66, 0xF5),
    5: (0xEA, 0x76, 0xCB),
    6: (0x17, 0x92, 0x99),
    8: (0x6C, 0x6F, 0x85),
    15: (0xBC, 0xC0, 0xCC),
}


def _reply(code: str, rgb: tuple[int, int, int], end: bytes = b"\x07") -> bytes:
    body = "/".join(f"{channel:02x}{channel:02x}" for channel in rgb)
    return f"\x1b]{code};rgb:{body}".encode() + end


def _onedark_replies() -> bytes:
    return (
        _reply("11", BG)
        + _reply("10", FG)
        + b"".join(_reply(f"4;{index}", rgb) for index, rgb in ANSI.items())
    )


class ParseRepliesTests(unittest.TestCase):
    def test_reads_every_reply_shape_a_terminal_sends(self) -> None:
        data = (
            _reply("11", BG)
            + _reply("10", FG, end=b"\x1b\\")
            + b"\x1b]4;1;rgb:e0/6c/75\x07"
            + b"\x1b]4;2;rgb:9/c/7\x07"
            + b"\x1b[?62;c"
        )

        colors = parse_replies(data)

        self.assertEqual(colors["bg"], BG)
        self.assertEqual(colors["fg"], FG)
        self.assertEqual(colors[1], (0xE0, 0x6C, 0x75))
        self.assertEqual(colors[2], (0x99, 0xCC, 0x77))
        self.assertEqual(parse_replies(b"\x1b[?62;c"), {})


class SchemeFromTerminalTests(unittest.TestCase):
    def _colors(self, extra: dict | None = None) -> dict:
        return {"bg": BG, "fg": FG, **ANSI, **(extra or {})}

    def test_maps_ansi_colors_and_derives_the_slots_ansi_lacks(self) -> None:
        scheme = scheme_from_terminal(
            self._colors({16: (0, 0, 0), 17: (0, 0, 95), 18: (0, 0, 135)})
        )

        self.assertEqual(scheme["base00"], BG)
        self.assertEqual(scheme["base05"], FG)
        self.assertEqual(scheme["base08"], ANSI[1])
        self.assertEqual(scheme["base0D"], ANSI[4])
        self.assertEqual(scheme["base03"], ANSI[8])
        self.assertEqual(scheme["base07"], ANSI[15])
        self.assertEqual(len(scheme), 16)
        # Untouched cube entries carry no scheme, so the orange sits between
        # red and yellow rather than being black.
        self.assertNotEqual(scheme["base09"], (0, 0, 0))
        for channel in range(3):
            low, high = sorted((ANSI[1][channel], ANSI[3][channel]))
            self.assertTrue(low <= scheme["base09"][channel] <= high)
        self.assertLess(scheme["base01"], scheme["base02"])
        self.assertLess(scheme["base02"], scheme["base03"])

    def test_uses_base16_shell_entries_when_the_terminal_set_them(self) -> None:
        orange, raised = (0xD1, 0x9A, 0x66), (0x35, 0x3B, 0x45)

        scheme = scheme_from_terminal(self._colors({16: orange, 18: raised}))

        self.assertEqual(scheme["base09"], orange)
        self.assertEqual(scheme["base01"], raised)

    def test_replaces_a_bright_black_that_is_plain_black(self) -> None:
        scheme = scheme_from_terminal(self._colors({8: (0, 0, 0)}))

        self.assertNotEqual(scheme["base03"], (0, 0, 0))
        self.assertTrue(all(BG[i] < scheme["base03"][i] < FG[i] for i in range(3)))

    def test_surfaces_stand_off_the_background_the_same_amount_in_light_and_dark(self) -> None:
        for name, colors in (
            ("dark", self._colors()),
            ("light", {"bg": LATTE_BG, "fg": LATTE_FG, **LATTE_ANSI}),
        ):
            with self.subTest(name):
                scheme = scheme_from_terminal(colors)
                bg = hex_color(scheme["base00"])
                raised = contrast_ratio(hex_color(scheme["base01"]), bg)
                selection = contrast_ratio(hex_color(scheme["base02"]), bg)
                self.assertAlmostEqual(raised, 1.15, delta=0.03)
                self.assertAlmostEqual(selection, 1.35, delta=0.03)
                palette = palette_from_scheme(scheme)
                self.assertGreater(contrast_ratio(palette["fg"], palette["bg-light"]), 4.5)
        light = scheme_from_terminal({"bg": LATTE_BG, "fg": LATTE_FG, **LATTE_ANSI})
        for slot, authored in (("base01", (0xE6, 0xE9, 0xEF)), ("base02", (0xCC, 0xD0, 0xDA))):
            gap = max(abs(a - b) for a, b in zip(light[slot], authored))
            self.assertLessEqual(gap, 8, f"{slot} {light[slot]} is far from base16's {authored}")

    def test_reports_which_way_the_background_leans_even_when_rejected(self) -> None:
        solarized_light = {"bg": (0xFD, 0xF6, 0xE3), "fg": (0x65, 0x7B, 0x83), **LATTE_ANSI}
        rejected = report_from_terminal(solarized_light)
        self.assertIsNone(rejected.scheme)
        self.assertTrue(rejected.light_background)
        self.assertFalse(report_from_terminal(self._colors()).light_background)
        self.assertIsNone(light_background({}))
        self.assertTrue(light_background({"bg": (0xFF, 0xFF, 0xFF)}))

    def test_rejects_a_silent_or_unreadable_terminal(self) -> None:
        missing = self._colors()
        del missing[3]

        self.assertIsNone(scheme_from_terminal({}))
        self.assertIsNone(scheme_from_terminal(missing))
        self.assertIsNone(scheme_from_terminal(self._colors({"fg": (0x30, 0x34, 0x3C)})))


class QueryTerminalSchemeTests(unittest.TestCase):
    def _query_through_pty(self, replies: bytes | None, timeout: float):
        master, slave = pty.openpty()

        def terminal() -> None:
            seen = b""
            while b"\x1b[c" not in seen:
                seen += os.read(master, 4096)
            if replies is not None:
                os.write(master, replies)

        thread = threading.Thread(target=terminal, daemon=True)
        thread.start()
        stdin = os.fdopen(slave, "rb", buffering=0)
        stdout = os.fdopen(os.dup(slave), "w")
        try:
            return query_terminal(timeout=timeout, stdin=stdin, stdout=stdout)
        finally:
            stdout.close()
            stdin.close()
            thread.join(1)
            os.close(master)

    def test_reads_the_scheme_off_a_pty_that_answers(self) -> None:
        report = self._query_through_pty(_onedark_replies() + b"\x1b[?62;c", timeout=2.0)

        self.assertEqual(report.scheme["base00"], BG)
        self.assertEqual(report.scheme["base08"], ANSI[1])
        self.assertFalse(report.light_background)

    def test_gives_up_on_a_pty_that_stays_silent(self) -> None:
        self.assertEqual(self._query_through_pty(None, timeout=0.05).scheme, None)

    def test_skips_anything_that_is_not_a_terminal(self) -> None:
        report = query_terminal(stdin=io.StringIO(), stdout=io.StringIO())
        self.assertEqual((report.scheme, report.light_background), (None, None))


if __name__ == "__main__":
    unittest.main()
