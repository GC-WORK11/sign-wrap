# LIMITATIONS

Current, known limits of this build.
`bin/wrap doctor` catches the environment ones before they bite.

## platform

- **Linux/X11 only.** On a Wayland session `xdotool`/`xclip` cannot inject into
  apps — previously a *silent* failure. `wrap doctor` now detects the session via
  `XDG_SESSION_TYPE` and warns (added 2026-10-25). Fix today: log into an X11
  session ("GNOME on Xorg" or equivalent). A Wayland/portal backend does not
  exist yet.
- **macOS / Windows: not supported.** The daemon is portable stdlib Python, but
  the injection layer is a port of `xdotool`, not a rebuild — planned, not
  promised.
- **Headless/SSH:** the daemon serves and pairs fine headless; nothing can be
  *typed* without a display. Doctor flags it.

## live signs

- **Camera needs a secure context.** Phone browsers refuse `getUserMedia` on
  `http://<lan-ip>`. Live mode over LAN will not open the camera — use USB
  (`wrap bridge` → `http://localhost:8741`, which browsers trust) or
  `wrap tunnel` (https). Text/media sending is unaffected.
- **Phone-camera ergonomics.** A held phone sees one hand — one-handed vocab
  only, or put the phone on a stand. Two-handed signing is a laptop-webcam
  path that does not ship in this build; that's why the phone path exists.
- **Phone keypoints are hands-only.** ~21 points per hand at ~15–30 fps, no
  body channel. Recognition accuracy on real cameras has not been formally
  benchmarked yet; hold each sign for about a second, in good light.
- **One user per bank.** `~/.config/wf/signbank.json` is per-user, per-machine.
  No multi-user switching, no sync, no cloud backup — export = copy the file.

## models

- **No pretrained sign model ships.** Every sign is taught by its user and
  matched with DTW on the laptop. The only model file in the repo is the
  MediaPipe hand landmarker (Apache-2.0).

## transport & security

- **LAN is authenticated cleartext HTTP.** The 40-hex pairing key travels once in
  the `?k=` URL — it can sit in phone browser history. `wrap tunnel` encrypts;
  delete `~/.config/wf/key` + `wrap restart` rotates the key.
- **`wrap tunnel` traverses Cloudflare's edge** for reachability only. No
  inference, storage, or key minting happens there — but the URL does leave your
  LAN. USB mode is zero-network.
- **`/pair` is rate-limited, not airtight** (1 try/sec/IP): it blunts 8-char code
  guessing; it isn't proof against a determined LAN attacker. Rotate the key if
  you pair on a hostile network.

## known bugs in `server/wfd.py` 

- request body is read unbounded — `Content-Length` is trusted
- rapid sends can interleave `xdotool` keystrokes (fire-and-forget `Popen`)
- `X-File-Name` is never URL-decoded
- clipboard restore mangles non-text clipboards
- fixed `/tmp/wf-img*` paths race on concurrent image sends
- `wfclip.py` advertises the `MULTIPLE` target then refuses it

## licenses

- **MediaPipe** (Live camera path): the hand-landmark WASM and model are
  vendored, not CDN-loaded; Apache-2.0 (see `THIRD_PARTY_NOTICES`).
- `server/qrcodegen.py` is vendored (Nayuki, MIT).
- This repo is MIT; see `LICENSE`.
