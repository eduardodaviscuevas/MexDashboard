"""
Serve the dashboard locally and save a full-page screenshot to verify/dashboard.png.

    pip install playwright && python -m playwright install chromium
    python verify/screenshot.py
"""

from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "verify" / "dashboard.png"


def main() -> int:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(url)
        page.wait_for_selector("body[data-ready='1']", timeout=60000)
        page.wait_for_timeout(1500)  # let Plotly finish layout
        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
    httpd.shutdown()
    print(f"saved {OUT}")
    for e in errors:
        print("browser error:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
