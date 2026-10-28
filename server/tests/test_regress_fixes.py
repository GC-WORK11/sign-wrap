"""Regression tests for the Oct 28 verify pass.

  1. Linux clipboard set returns promptly (xclip's resident owner used to
     hold the captured pipe open, so every paste waited out the timeout).
  2. /send, /send-image and /send-file answer 409 "window gone" when the
     picked window no longer exists, and nothing is typed anywhere.
  3. `wrap start` on a busy port prints "port N busy - using :M" (operator
     precedence once made it raise TypeError instead).
  4. act_platform._run returns stdout on success, stderr first on failure.

Run:  cd server && python3 -m unittest tests.test_regress_fixes
"""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile
import time, unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
WFD = os.path.join(BASE, "wfd.py")
CLI = os.path.join(BASE, "wrap_cli.py")

import act_platform  # noqa: E402

LINUX_X = (sys.platform.startswith("linux") and os.environ.get("DISPLAY")
           and shutil.which("xclip"))


def slurp(path):
    with open(path) as f:
        return f.read()


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


class TestRunReturn(unittest.TestCase):
    def test_success_returns_stdout(self):
        ok, out = act_platform._run(["sh", "-c", "echo out; echo warn >&2"])
        self.assertTrue(ok)
        self.assertEqual(out, "out")

    def test_failure_prefers_stderr(self):
        ok, out = act_platform._run(["sh", "-c", "echo out; echo bad >&2; exit 3"])
        self.assertFalse(ok)
        self.assertEqual(out, "bad")

    def test_failure_without_stderr_falls_back_to_stdout(self):
        ok, out = act_platform._run(["sh", "-c", "echo only; exit 1"])
        self.assertFalse(ok)
        self.assertEqual(out, "only")

    def test_missing_binary(self):
        ok, out = act_platform._run(["/nonexistent/wf-nope"])
        self.assertFalse(ok)
        self.assertIn("not found", out)


@unittest.skipUnless(LINUX_X, "needs Linux X11 + xclip")
class TestClipboardNoHang(unittest.TestCase):
    def test_clip_set_text_returns_fast_and_sticks(self):
        t0 = time.monotonic()
        ok, detail = act_platform.clip_set_text("wf-regress-1\n")
        took = time.monotonic() - t0
        self.assertTrue(ok, detail)
        self.assertLess(took, 2.0, "clip_set_text blocked %.1fs" % took)
        got = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                             capture_output=True, text=True, timeout=5).stdout
        self.assertEqual(got, "wf-regress-1\n")

    def test_clip_get_keeps_trailing_newline(self):
        act_platform.clip_set_text("line\n")
        self.assertEqual(act_platform.clip_get(), "line\n")


class _Daemon(unittest.TestCase):
    display = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wf-regress-")
        cls.port = free_port()
        cfg = os.path.join(cls.tmp, ".config", "wf"); os.makedirs(cfg)
        env = dict(os.environ, HOME=cls.tmp, WF_PORT=str(cls.port),
                   WF_NO_LOG_TEXT="1")
        if cls.display:
            env["DISPLAY"] = cls.display
        else:
            env.pop("DISPLAY", None)
        cls.proc = subprocess.Popen([sys.executable, WFD], env=env,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                if cls.raw("GET", "/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            cls.proc.kill(); raise RuntimeError("wfd did not start")
        cls.key = slurp(os.path.join(cfg, "key")).strip()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def raw(cls, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=15)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse(); data = r.read(); c.close()
        return r.status, dict(r.getheaders()), data

    def h(self, extra=None):
        d = {"X-WF-Key": self.key}
        d.update(extra or {})
        return d


GONE = "4294967290"     # a decimal X id no server hands out


class TestWindowGoneContract(_Daemon):
    def test_send_409(self):
        st, _, b = self.raw("POST", "/send", json.dumps(
            {"text": "nope", "window": GONE}).encode(),
            self.h({"Content-Type": "application/json"}))
        self.assertEqual(st, 409)
        self.assertEqual(json.loads(b)["error"], "window gone")

    def test_send_image_409(self):
        st, _, b = self.raw("POST", "/send-image", b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                            self.h({"X-WF-Window": GONE,
                                    "Content-Type": "image/png"}))
        self.assertEqual(st, 409)
        self.assertEqual(json.loads(b)["error"], "window gone")

    def test_send_file_409_and_nothing_stored(self):
        st, _, b = self.raw("POST", "/send-file", b"x" * 1024,
                            self.h({"X-WF-Window": GONE,
                                    "X-File-Name": "gone.bin"}))
        self.assertEqual(st, 409)
        self.assertEqual(json.loads(b)["error"], "window gone")
        up = os.path.join(self.tmp, "wf-uploads")
        self.assertFalse(os.path.exists(os.path.join(up, "gone.bin")))

    def test_no_window_still_200(self):
        st, _, _ = self.raw("POST", "/send", json.dumps({"text": ""}).encode(),
                            self.h({"Content-Type": "application/json"}))
        self.assertEqual(st, 200)


@unittest.skipUnless(LINUX_X and shutil.which("xterm") and shutil.which("xdotool"),
                     "needs X11 + xterm + xdotool")
class TestWindowGoneTypesNothing(_Daemon):
    """Real X: a focused xterm records keystrokes; a send at a gone window
    must leave it empty, while a send at the live window lands."""
    display = os.environ.get("DISPLAY")

    def setUp(self):
        self.sink = os.path.join(self.tmp, "sink.txt")
        open(self.sink, "w").close()
        title = "wf-regress-sink-%d" % os.getpid()
        self.xt = subprocess.Popen(
            ["xterm", "-T", title, "-e", "sh", "-c",
             "stty -icanon -echo; exec cat > '%s'" % self.sink],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wid = None
        for _ in range(50):
            r = subprocess.run(["xdotool", "search", "--name", title],
                               capture_output=True, text=True)
            if r.stdout.strip():
                self.wid = r.stdout.split()[0]; break
            time.sleep(0.1)
        if not self.wid:
            self.xt.kill(); self.skipTest("xterm did not map")
        subprocess.run(["xdotool", "windowactivate", "--sync", self.wid],
                       capture_output=True, timeout=5)
        time.sleep(0.5)

    def tearDown(self):
        self.xt.kill(); self.xt.wait(5)

    def _send(self, win, text):
        return self.raw("POST", "/send", json.dumps(
            {"text": text, "window": win}).encode(),
            self.h({"Content-Type": "application/json"}))[0]

    def test_gone_types_nothing_live_types(self):
        self.assertEqual(self._send(GONE, "LEAKED"), 409)
        time.sleep(1.0)
        self.assertEqual(slurp(self.sink), "")
        self.assertEqual(self._send(self.wid, "landed"), 200)
        for _ in range(30):
            if "landed" in slurp(self.sink):
                break
            time.sleep(0.1)
        self.assertEqual(slurp(self.sink), "landed")


class TestPortBusyMessage(unittest.TestCase):
    def test_busy_port_message(self):
        tmp = tempfile.mkdtemp(prefix="wf-busy-")
        hold = socket.socket()
        hold.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        hold.bind(("0.0.0.0", 0)); hold.listen(1)
        port = hold.getsockname()[1]
        env = dict(os.environ, HOME=tmp, WF_PORT=str(port),
                   WF_STATE_DIR=os.path.join(tmp, "state"),
                   PATH="/usr/bin:/bin", PYTHONIOENCODING="utf-8")
        env.pop("DISPLAY", None)
        try:
            r = subprocess.run([sys.executable, CLI, "start"], env=env,
                               capture_output=True, text=True, timeout=40)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback", out)
            self.assertRegex(out, r"port %d busy [—-] using :\d+" % port)
        finally:
            subprocess.run([sys.executable, CLI, "stop"], env=env,
                           capture_output=True, timeout=20)
            hold.close()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
