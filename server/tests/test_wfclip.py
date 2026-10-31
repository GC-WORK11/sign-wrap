#!/usr/bin/env python3
"""Regression test for QA-3: an image sent to a text editor typed the
laptop's temp path ("/tmp/wf-img-raw-....png") into the document, because
the clipboard owner (wfclip.py) offered the path as text next to the image.

Needs a real X display, xclip and python3-xlib; skipped otherwise.
Run: DISPLAY=:0 python3 -m unittest tests.test_wfclip -v   (from server/)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WFCLIP = os.path.join(HERE, "wfclip.py")
PNG = os.path.join(os.path.dirname(HERE), "web", "icon-16.png")


def _xlib_ok():
    r = subprocess.run([sys.executable, "-c", "import runpy,sys; sys.argv=['x','/dev/null']; "
                        "exec(open(%r).read().split('path = sys.argv')[0])" % WFCLIP],
                       capture_output=True)
    return r.returncode == 0


@unittest.skipUnless(os.environ.get("DISPLAY") and shutil.which("xclip") and _xlib_ok(),
                     "needs an X display, xclip and python3-xlib")
class ClipboardTargets(unittest.TestCase):
    def own(self, path, mime):
        p = subprocess.Popen([sys.executable, WFCLIP, path, mime],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.assertEqual(p.stdout.readline().strip(), b"ready")
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def get(self, target):
        r = subprocess.run(["xclip", "-selection", "clipboard", "-t", target, "-o"],
                           capture_output=True, timeout=10)
        return r.returncode, r.stdout

    def test_image_is_offered_as_image_and_file_not_as_text(self):
        d = tempfile.mkdtemp(prefix="wf-img-test-")
        img = os.path.join(d, "shot.png")
        shutil.copy(PNG, img)
        self.own(img, "image/png")
        rc, targets = self.get("TARGETS")
        names = targets.decode().split()
        self.assertIn("image/png", names)
        self.assertIn("text/uri-list", names)
        for t in ("UTF8_STRING", "STRING", "text/plain"):
            self.assertNotIn(t, names)
        # an app that asks for text anyway gets nothing, not the temp path
        for t in ("UTF8_STRING", "STRING"):
            rc, out = self.get(t)
            self.assertNotIn(img.encode(), out)
        rc, out = self.get("image/png")
        self.assertEqual(rc, 0)
        self.assertEqual(out, open(PNG, "rb").read())

    def test_other_files_still_paste_their_path(self):
        d = tempfile.mkdtemp(prefix="wf-file-test-")
        f = os.path.join(d, "notes.txt")
        open(f, "w").write("x")
        self.own(f, "text/plain")
        rc, out = self.get("UTF8_STRING")
        self.assertEqual(out.decode(), f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
