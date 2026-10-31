#!/usr/bin/env python3
"""Regression test for QA-4: paste, file and video sends into xterm inserted
a literal Ctrl-V (0x16). The daemon sent ctrl+shift+v to every terminal, but
stock xterm has no such binding. Terminals now get the text, or the file's
path, typed.

Run: python3 -m unittest tests.test_terminal_paste -v   (from server/)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wfd  # noqa: E402


class TerminalPaste(unittest.TestCase):
    def setUp(self):
        self.saved = (wfd._host, wfd.active_window_class, wfd._inject_keystrokes,
                      wfd._inject_chord, wfd._wfclip_own, wfd.act_platform)
        self.typed, self.chords = [], []
        wfd._host = lambda: "linux"
        wfd._inject_keystrokes = lambda text: (self.typed.append(text), (True, ""))[1]
        wfd._inject_chord = lambda keys: (self.chords.append(keys), (True, ""))[1]
        wfd._wfclip_own = lambda path, mime: True
        wfd.act_platform = None
        while not wfd._INJECT_Q.empty():
            wfd._INJECT_Q.get_nowait()

    def tearDown(self):
        (wfd._host, wfd.active_window_class, wfd._inject_keystrokes,
         wfd._inject_chord, wfd._wfclip_own, wfd.act_platform) = self.saved

    def run_jobs(self):
        while not wfd._INJECT_Q.empty():
            wfd._INJECT_Q.get_nowait()()

    def test_file_into_xterm_types_the_quoted_path(self):
        wfd.paste_file("/home/me/wf-uploads/1_my clip.mp4", "video/mp4", "xterm")
        self.run_jobs()
        self.assertEqual(self.typed, ["'/home/me/wf-uploads/1_my clip.mp4'"])
        self.assertEqual(self.chords, [])

    def test_paste_mode_text_into_xterm_is_typed(self):
        wfd.active_window_class = lambda: "xterm"
        wfd.type_paste("ls -la")
        self.run_jobs()
        self.assertEqual(self.typed, ["ls -la"])
        self.assertEqual(self.chords, [])

    def test_other_terminals_are_terminals(self):
        for c in ("xfce4-terminal", "gnome-terminal-server", "konsole",
                  "kitty", "alacritty", "st-256color", "org.wezfurlong.wezterm"):
            self.assertTrue(wfd._is_terminal(c), c)

    def test_apps_with_st_in_the_name_still_paste(self):
        self.assertFalse(wfd._is_terminal("postman"))
        wfd.paste_file("/tmp/x.png", "image/png", "postman")
        self.run_jobs()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.chords, ["ctrl+v"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
