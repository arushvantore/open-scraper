#!/usr/bin/env python3
"""
make_guide.py -- turn GUIDE.html into GUIDE.pdf.

Uses the Chromium that Playwright already installed, so there is nothing
extra to install.

    .venv/bin/python make_guide.py
"""

import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright is missing. Run: pip install -r requirements.txt")

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "GUIDE.html"
OUTPUT = HERE / "GUIDE.pdf"


def main():
    if not SOURCE.is_file():
        sys.exit("GUIDE.html not found next to this script.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(SOURCE.as_uri())
        page.wait_for_load_state("networkidle")
        page.pdf(
            path=str(OUTPUT),
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()

    size = OUTPUT.stat().st_size
    print("Wrote %s (%.1f KB)" % (OUTPUT.name, size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
