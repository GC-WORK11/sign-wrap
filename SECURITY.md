# Security Policy

## Supported versions

This project is pre-1.0. Only the latest commit on the default branch
receives security fixes; there are no supported release lines yet.

## Reporting a vulnerability

Please report vulnerabilities privately through **GitHub Security
Advisories**: open the repository's *Security* tab and choose
"Report a vulnerability."

If that is unavailable, open a regular GitHub issue describing the impact
and affected component **without** reproduction details, and we will move
the discussion to a private channel.

Include where possible: the endpoint or component involved, the attack
surface (LAN attacker, paired-device attacker, tunnel exposure), and
whether you have a working reproduction. We aim to acknowledge reports
within 7 days.

## Deployment notes — the daemon binds 0.0.0.0

`wfd.py` binds `0.0.0.0:8741` by default so a phone on the same network
can reach it. That means every device on your LAN can *connect* to the
daemon. What they can do is gated:

- All control and data endpoints (`/send`, `/send-image`, `/send-file`,
  `/live/*`, `/teach/*`, `/bank`, `/act/*`, `/status`) require the
  `X-WF-Key` header — a per-install key stored at `~/.config/wf/key`
  (mode 600), compared in constant time.
- `/pair-info` (which returns the key) answers on loopback only,
  rejects proxied requests, and requires an IP-literal or `localhost`
  Host header, so it cannot leak through a tunnel or a DNS-rebinding
  page. Cross-origin browser reads are denied outright: the daemon only
  reflects an `Origin` that exactly matches its own `Host`, so a foreign
  web page cannot read the key or drive the API from a laptop-side
  browser.
- `/pair` accepts an 8-character session code and is rate-limited to
  1 try/second/IP. It blunts code-guessing; it is not proof against a
  determined attacker on the same LAN.
- Live/teach/bank endpoints additionally refuse requests arriving through
  a tunnel.

LAN traffic is authenticated but **cleartext HTTP**. On an untrusted LAN:

- Prefer USB mode (`wrap bridge`) — it uses `adb reverse`, needs no LAN
  at all, and gives the phone a secure-context `localhost` origin.
- Or restrict the port with a firewall, e.g.
  `sudo ufw allow from <phone-ip> to any port 8741`.
- Or use `wrap tunnel` for TLS transport via cloudflared (the URL then
  traverses Cloudflare's edge — for reachability only; inference stays on
  the laptop).
- Rotate the key after pairing on a hostile network: delete
  `~/.config/wf/key` and run `wrap restart`.

## Other protections worth knowing

- Actions spawn as argv vectors — no shell is invoked — and risk tier ≥ 2
  actions hold for a laptop-side confirm that a hostile composer cannot
  bypass.
- Upload bodies are capped before reading (`WF_MAX_UPLOAD`,
  `WF_MAX_IMAGE`), streamed to disk in bounded chunks, and filenames are
  sanitized. Partial uploads are deleted.
- The sign bank (`~/.config/wf/signbank.json`, mode 600) is
  biometric-adjacent data — treat it like a credential.
- Set `WF_NO_LOG_TEXT=1` to keep dictated text out of `wfd.log`.
