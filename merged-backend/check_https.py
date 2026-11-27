#!/usr/bin/env python3
"""Verify ircodmshop.com serves HTTPS and forces the redirect.

Run:  python check_https.py
Exit 0 = HTTPS enforced. Exit 1 = still serving plain http.

Checks:
  1. https://ircodmshop.com/ returns 200 with a valid certificate
  2. http://ircodmshop.com/ redirects (301/302/308) to https
  3. https://www.ircodmshop.com/ redirects to the apex
  4. the live page carries an https canonical URL
  5. no real http:// subresource requests in the HTML
"""

from __future__ import annotations

import re
import ssl
import socket
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

APEX = "ircodmshop.com"
WWW = "www.ircodmshop.com"
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILED.append(label)


def fetch(url: str, follow: bool = False, timeout: int = 25, retries: int = 3):
    """Return (status, headers, body_bytes, final_url). No exception on HTTP errors.

    Retries on transport failures (DNS blip, connection reset) so a transient
    network hiccup does not masquerade as "the site is down". HTTP status codes
    are returned as-is and never retried — a 200 or a 301 is a real answer.
    """
    ctx = ssl.create_default_context()
    last = (None, {}, b"", "no attempt")
    for attempt in range(retries):
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPRedirectHandler() if follow else _NoRedirect(),
        )
        req = urllib.request.Request(url, headers={"User-Agent": "cpshop-https-check/1.0"})
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), b"", url
        except Exception as e:
            last = (None, {}, b"", f"{type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return last


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx instead of following it."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cert_info(host: str) -> tuple[bool, str]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                c = ss.getpeercert()
        subject = dict(x[0] for x in c.get("subject", ())).get("commonName", "?")
        not_after = datetime.strptime(c["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc)
        days = (not_after - datetime.now(timezone.utc)).days
        return True, f"CN={subject}, expires in {days}d"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    print("=" * 64)
    print(f"HTTPS check for {APEX}")
    print("=" * 64)

    # 1. certificate
    ok, info = cert_info(APEX)
    check("valid TLS certificate", ok, info)

    # 2. https serves the page
    status, headers, body, last_error = fetch(f"https://{APEX}/")
    check("https:// returns 200", status == 200, f"status={status}")
    check("page has content", len(body) > 10_000, f"{len(body)} bytes")
    check("served by GitHub Pages", "github" in str(headers).lower(),
          headers.get("Server", "?"))

    # 3. http must redirect
    status, headers, _, _ = fetch(f"http://{APEX}/")
    location = headers.get("Location", "")
    redirects = status in (301, 302, 307, 308) and location.startswith("https://")
    check("http:// redirects to https", redirects,
          f"status={status} location={location or '(none)'}")

    # 4. www redirects to apex
    status, headers, _, _ = fetch(f"https://{WWW}/")
    loc = headers.get("Location", "")
    check("www redirects to apex", status in (301, 302, 308) and APEX in loc,
          f"status={status} location={loc or '(none)'}")

    # 5. canonical is https
    html = body.decode("utf-8", "replace")
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', html)
    canonical = m.group(1) if m else ""
    check("canonical URL is https", canonical.startswith("https://"),
          canonical or "(missing)")

    # 6. no real http subresources (SVG namespace is not a request)
    http_refs = [
        u for u in re.findall(r'http://[^\s"\'<>)]+', html)
        if "www.w3.org" not in u  # SVG/XML namespace, never fetched
    ]
    check("no http:// subresources", not http_refs,
          ", ".join(http_refs[:3]) if http_refs else "none")

    # 7. HSTS (informational — GitHub Pages cannot set it)
    hsts = headers.get("Strict-Transport-Security")
    print(f"  INFO  HSTS header: {hsts or 'absent (GitHub Pages cannot set it)'}")

    print()
    if FAILED:
        print(f"RESULT: {len(FAILED)} CHECK(S) FAILED")
        for f in FAILED:
            print(f"  - {f}")

        # Distinguish "the site is unreachable" from "HTTPS is not enforced" —
        # they need completely different actions.
        if "https:// returns 200" in FAILED or "page has content" in FAILED:
            print("\nThe site did not respond. This is a network/outage problem,")
            print("not an HTTPS-enforcement problem. Check connectivity and re-run.")
            print(f"  last transport error: {last_error}")
        elif "http:// redirects to https" in FAILED:
            print("\nHTTP is served without redirecting. Enable:")
            print("  github.com/parhamhz8814-maker/merge-sites1/settings/pages -> Enforce HTTPS")
        return 1
    print("RESULT: HTTPS ENFORCED — all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
