#!/usr/bin/env python3
"""
page_scraper.py -- scrape any PUBLIC web page into clean Markdown.

SAFETY (this is the whole point of the tool):
  * read-only. GET requests only.
  * no logins, no cookies, no passwords, no account support.
  * never submits a form, never posts, never uploads, never likes/follows.
  * honours robots.txt by default (--no-robots to override).
  * one page at a time, with a polite pause between pages.

USAGE
  python page_scraper.py https://example.com
  python page_scraper.py https://a.com https://b.com https://c.com
  python page_scraper.py --targets targets.txt
  python page_scraper.py https://example.com --selector "article"
  python page_scraper.py https://example.com --links
  python page_scraper.py https://example.com --screenshot
  python page_scraper.py --targets targets.txt --out mydir --pause 3

Run `python page_scraper.py --help` for every flag.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

try:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(
        "Playwright is not installed.\n"
        "Run:\n"
        "  pip install -r requirements.txt\n"
        "  playwright install chromium"
    )

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 open-scraper/1.0"
)

# Tags whose contents are never human-readable text.
SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "iframe", "template"}


# --------------------------------------------------------------------------
# HTML -> Markdown (stdlib only, no extra dependencies)
# --------------------------------------------------------------------------

class Markdownify(HTMLParser):
    """Turns a blob of HTML into readable Markdown."""

    def __init__(self, base_url=""):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.chunks = []
        self.skip_depth = 0
        self.href = None
        self.link_text = []
        self.in_pre = False
        self.list_depth = 0
        self.title = ""

    # -- start tags ---------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        a = dict(attrs)

        if re.fullmatch(r"h[1-6]", tag):
            self.chunks.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.chunks.append("\n\n")
        elif tag == "br":
            self.chunks.append("\n")
        elif tag == "li":
            self.chunks.append("\n" + "  " * self.list_depth + "- ")
        elif tag in ("ul", "ol"):
            self.list_depth += 1
            self.chunks.append("\n")
        elif tag == "a":
            self.href = a.get("href") or ""
            self.link_text = []
        elif tag == "img":
            alt, src = a.get("alt", ""), a.get("src", "")
            if alt or src:
                self.chunks.append("\n![%s](%s)\n" % (alt, self._abs(src)))
        elif tag == "pre":
            self.in_pre = True
            self.chunks.append("\n\n```\n")
        elif tag == "code" and not self.in_pre:
            self.chunks.append("`")
        elif tag in ("strong", "b"):
            self.chunks.append("**")
        elif tag in ("em", "i"):
            self.chunks.append("*")
        elif tag == "blockquote":
            self.chunks.append("\n\n> ")
        elif tag in ("table", "tr"):
            self.chunks.append("\n")
        elif tag in ("td", "th"):
            self.chunks.append(" | ")

    # -- end tags -----------------------------------------------------------
    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return

        if re.fullmatch(r"h[1-6]", tag):
            self.chunks.append("\n")
        elif tag == "p":
            self.chunks.append("\n")
        elif tag in ("ul", "ol"):
            self.list_depth = max(0, self.list_depth - 1)
            self.chunks.append("\n")
        elif tag == "a":
            text = " ".join("".join(self.link_text).split())
            href = self._abs(self.href)
            if text and href.startswith("http"):
                self.chunks.append("[%s](%s)" % (text, href))
            elif text:
                self.chunks.append(text)
            self.href = None
            self.link_text = []
        elif tag == "pre":
            self.in_pre = False
            self.chunks.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.chunks.append("`")
        elif tag in ("strong", "b"):
            self.chunks.append("**")
        elif tag in ("em", "i"):
            self.chunks.append("*")
        elif tag == "blockquote":
            self.chunks.append("\n")

    # -- text ---------------------------------------------------------------
    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.href is not None:          # inside <a> ... </a>
            self.link_text.append(data)
            return
        if not self.in_pre:
            data = " ".join(data.split())
            if not data:
                return
        self.chunks.append(data)

    # -- output -------------------------------------------------------------
    def markdown(self):
        text = "".join(self.chunks)
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text.strip() + "\n" if text.strip() else ""

    def _abs(self, url):
        if not url:
            return ""
        return urljoin(self.base_url, url)


def extract_links(html, base_url):
    """Return a sorted, de-duplicated list of absolute http(s) links."""
    found = set()

    class Grab(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag != "a":
                return
            href = dict(attrs).get("href") or ""
            if href.startswith("#") or href.lower().startswith(
                    ("mailto:", "javascript:", "tel:")):
                return
            full = urljoin(base_url, href)
            if full.startswith("http"):
                found.add(full.split("#")[0])

    p = Grab(convert_charrefs=True)
    p.feed(html)
    return sorted(found)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def robots_allows(url, user_agent, timeout=10):
    """True when robots.txt permits this user-agent to fetch `url`.

    robots.txt is fetched with the SAME user-agent we scrape with, so a site
    that blocks Python's default UA does not get mistaken for "disallow all".
    """
    parts = urlparse(url)
    robots_url = "%s://%s/robots.txt" % (parts.scheme, parts.netloc)
    req = Request(robots_url, headers={"User-Agent": user_agent})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except HTTPError as err:
        if err.code in (401, 403):
            return False       # RFC 9309: site refuses -> treat as disallow all
        return True            # 404 / 5xx -> no usable rules, allow
    except Exception:
        return True            # unreachable -> don't block the user silently

    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp.can_fetch(user_agent, url) or rp.can_fetch("*", url)


def slugify(url, max_len=80):
    """https://site.com/a/b?x=1  ->  site.com-a-b"""
    p = urlparse(url)
    raw = p.netloc + p.path
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return (raw or "page")[:max_len].strip("-") or "page"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_page(out_dir, url, title, body_md, links=None, selector=None):
    """Write one Markdown file with a YAML-ish header. Returns the path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (slugify(url) + ".md")

    words = len(body_md.split())
    digest = hashlib.sha256(body_md.encode("utf-8")).hexdigest()[:16]

    header = [
        "---",
        "url: %s" % url,
        "title: %s" % (title.replace("\n", " ") if title else "(no title)"),
        "fetched: %s" % now_iso(),
        "selector: %s" % (selector or "(whole page)"),
        "word_count: %d" % words,
        "content_hash: %s" % digest,
        "---",
        "",
    ]

    parts = header
    if title:
        parts += ["# %s" % title, ""]
    parts.append(body_md)

    if links is not None:
        parts += ["", "## Links (%d)" % len(links), ""]
        parts += ["- [%s](%s)" % (lnk, lnk) for lnk in links]

    path.write_text("\n".join(parts), encoding="utf-8")
    return path, digest, words


# --------------------------------------------------------------------------
# The scraper
# --------------------------------------------------------------------------

def scrape(url, timeout_ms, wait_ms, selector=None, headful=False):
    """Fetch one URL. Returns (title, body_markdown, links, final_url)."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headful)
        ctx = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PWTimeout:
                pass                       # fine; many pages never go idle

            final_url = page.url
            title = page.title() or ""
            html = page.content()

            if selector:
                try:
                    html = page.locator(selector).first.inner_html()
                except Exception as exc:
                    raise SystemExit(
                        "Selector %r matched nothing on %s\n(%s)"
                        % (selector, url, exc)
                    )

            parser = Markdownify(final_url)
            parser.feed(html)
            body = parser.markdown()
            links = extract_links(html, final_url)
            return title, body, links, final_url
        finally:
            browser.close()


def scrape_or_die(url, args):
    """Scrape one URL honouring robots.txt. Returns a result dict or None."""
    if not args.no_robots and not robots_allows(url, USER_AGENT):
        print("  SKIP  %s  (robots.txt disallows)" % url)
        return None

    print("  GET   %s" % url)
    try:
        title, body, links, final_url = scrape(
            url,
            timeout_ms=args.timeout * 1000,
            wait_ms=args.wait,
            selector=args.selector,
            headful=args.headful,
        )
    except SystemExit:
        raise
    except Exception as exc:
        print("  FAIL  %s  (%s)" % (url, exc))
        return None

    if not body.strip():
        print("  EMPTY %s  (no text extracted)" % url)
        return None

    path, digest, words = write_page(
        args.out, final_url or url, title, body,
        links=links if args.links else None,
        selector=args.selector,
    )
    print("  SAVE  %s  (%d words, hash %s)" % (path, words, digest))

    if args.screenshot:
        shot = Path(args.out) / (slugify(url) + ".png")
        try:
            with sync_playwright() as pw:
                b = pw.chromium.launch(headless=not args.headful)
                p = b.new_page(user_agent=USER_AGENT)
                p.goto(final_url or url, timeout=args.timeout * 1000)
                p.wait_for_timeout(max(args.wait, 800))
                p.screenshot(path=str(shot), full_page=True)
                b.close()
            print("  SHOT  %s" % shot)
        except Exception as exc:
            print("  SHOT  failed (%s)" % exc)

    return {
        "url": url,
        "title": title,
        "path": str(path),
        "words": words,
        "hash": digest,
        "links": len(links),
        "fetched": now_iso(),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_targets(path):
    urls = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="page_scraper.py",
        description="Scrape public web pages into Markdown. Read-only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("USAGE", 1)[-1],
    )
    ap.add_argument("urls", nargs="*", help="one or more http(s) URLs")
    ap.add_argument("--targets", metavar="FILE",
                    help="file with one URL per line (# = comment)")
    ap.add_argument("--out", default="output", help="output dir (default: output)")
    ap.add_argument("--selector", metavar="CSS",
                    help="extract only this element, not the whole page")
    ap.add_argument("--links", action="store_true",
                    help="also append every link found on the page")
    ap.add_argument("--screenshot", action="store_true",
                    help="also save a full-page PNG next to the .md")
    ap.add_argument("--timeout", type=int, default=30,
                    help="seconds to wait for the page (default: 30)")
    ap.add_argument("--wait", type=int, default=1500,
                    help="extra ms to wait for JavaScript (default: 1500)")
    ap.add_argument("--pause", type=float, default=2.0,
                    help="seconds to sleep between URLs (default: 2)")
    ap.add_argument("--no-robots", action="store_true",
                    help="ignore robots.txt (use only on your own sites)")
    ap.add_argument("--headful", action="store_true",
                    help="show the browser window instead of running hidden")
    ap.add_argument("--json", metavar="FILE",
                    help="also write a JSON summary of what was scraped")
    args = ap.parse_args(argv)

    urls = list(args.urls)
    if args.targets:
        urls += load_targets(args.targets)
    if not urls:
        ap.error("no URLs given. Pass them as arguments or use --targets FILE")

    bad = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
    if bad:
        ap.error("these are not http(s) URLs: %s" % ", ".join(bad))

    print("open-scraper :: %d page(s) -> %s/" % (len(urls), args.out))
    results = []
    for i, url in enumerate(urls):
        res = scrape_or_die(url, args)
        if res:
            results.append(res)
        if i < len(urls) - 1:
            time.sleep(args.pause)

    print("\nDone. %d ok, %d skipped/failed."
          % (len(results), len(urls) - len(results)))

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2), encoding="utf-8")
        print("Summary written to %s" % args.json)

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
