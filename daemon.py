#!/usr/bin/env python3
"""
daemon.py -- background web-scraping daemon.

Keeps a list of public URLs under watch. Every cycle it re-fetches each one:

  output/live/<name>.md          always rewritten - the current state
  output/archive/<ts>_<name>.md  only written when the content CHANGED
  daemon.log                     timeline of every cycle

Read-only, same promise as page_scraper.py:
  GET requests only, no logins, no forms, no uploads.
  honours robots.txt unless --no-robots.

USAGE
  python daemon.py --targets targets.txt
  python daemon.py --targets targets.txt --interval 60
  python daemon.py --targets targets.txt --interval 3600 --diff-only
  python daemon.py --targets targets.txt --out mydir --log my.log
  python daemon.py --targets targets.txt --once

Press Ctrl-C to stop. Nothing keeps running after you close the terminal
unless you start it from a scheduler (see README.md).
"""

import argparse
import hashlib
import json
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from page_scraper import (
    USER_AGENT,
    load_targets,
    robots_allows,
    scrape,
    slugify,
    write_page,
)

STOP = False


def _handle_stop(signum, frame):
    global STOP
    STOP = True
    print("\nStopping after this page... (Ctrl-C again to hard quit)")


def log(path, msg):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = "%s %s" % (stamp, msg)
    print(line, flush=True)
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def read_hashes(state_path):
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_hashes(state_path, data):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def fetch_one(url, args):
    """Fetch one URL. Returns (body_md, title, links) or None."""
    if not args.no_robots and not robots_allows(url, USER_AGENT):
        log(args.log, "SKIP %s (robots.txt disallows)" % url)
        return None
    try:
        title, body, links, final_url = scrape(
            url,
            timeout_ms=args.timeout * 1000,
            wait_ms=args.wait,
            selector=args.selector,
            headful=False,
        )
        if not body.strip():
            log(args.log, "EMPTY %s" % url)
            return None
        return final_url or url, title, body, links
    except Exception as exc:
        log(args.log, "FAIL %s (%s)" % (url, exc))
        return None


def cycle(urls, args, state, state_path):
    live_dir = Path(args.out) / "live"
    archive_dir = Path(args.out) / "archive"
    live_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    changed = 0
    seen = 0
    failed = 0

    for url in urls:
        if STOP:
            break
        got = fetch_one(url, args)
        if not got:
            failed += 1
            continue

        final_url, title, body, links = got
        seen += 1
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        name = slugify(url)

        live_path, _, words = write_page(
            live_dir, final_url, title, body,
            links=links if args.links else None,
            selector=args.selector,
        )

        previous = state.get(url)
        if previous != digest:
            changed += 1
            state[url] = digest
            if not args.diff_only:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                write_page(
                    archive_dir, final_url, title, body,
                    links=links if args.links else None,
                    selector=args.selector,
                )
                # re-stamp the archive filename with the cycle time
                archived = archive_dir / (slugify(final_url) + ".md")
                stamped = archive_dir / ("%s_%s.md" % (stamp, name))
                if archived.exists() and not stamped.exists():
                    archived.rename(stamped)
                    print("  NEW   %s -> %s" % (url, stamped.name))
            else:
                print("  NEW   %s (%d words)" % (url, words))
            log(args.log, "CHANGED %s (%d words)" % (url, words))
        else:
            print("  same  %s" % url)
            log(args.log, "same   %s (%d words)" % (url, words))

        if not STOP and args.pause:
            time.sleep(args.pause)

    save_hashes(state_path, state)
    log(args.log, "cycle done: %d seen, %d changed, %d failed"
        % (seen, changed, failed))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="daemon.py",
        description="Background daemon that watches public URLs for changes.",
    )
    ap.add_argument("--targets", required=True, metavar="FILE",
                    help="file with one URL per line (# = comment)")
    ap.add_argument("--interval", type=int, default=300,
                    help="seconds between cycles (default: 300 = 5 min)")
    ap.add_argument("--out", default="output", help="output dir (default: output)")
    ap.add_argument("--log", default="daemon.log", help="log file")
    ap.add_argument("--state", default=None,
                    help="state file (default: <out>/.state.json)")
    ap.add_argument("--selector", metavar="CSS",
                    help="extract only this element, not the whole page")
    ap.add_argument("--links", action="store_true",
                    help="also append every link found")
    ap.add_argument("--timeout", type=int, default=30,
                    help="seconds per page (default: 30)")
    ap.add_argument("--wait", type=int, default=1500,
                    help="extra ms to wait for JavaScript (default: 1500)")
    ap.add_argument("--pause", type=float, default=2.0,
                    help="seconds between URLs inside a cycle (default: 2)")
    ap.add_argument("--once", action="store_true",
                    help="run a single cycle and exit (no daemon loop)")
    ap.add_argument("--no-robots", action="store_true",
                    help="ignore robots.txt (use only on your own sites)")
    ap.add_argument("--diff-only", action="store_true",
                    help="do not write archive files, only mark changes")
    args = ap.parse_args(argv)

    urls = load_targets(args.targets)
    if not urls:
        ap.error("no URLs found in %s" % args.targets)

    bad = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
    if bad:
        ap.error("these are not http(s) URLs: %s" % ", ".join(bad))

    state_path = Path(args.state) if args.state else Path(args.out) / ".state.json"
    state = read_hashes(state_path)

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    log(args.log, "daemon start: %d target(s), interval %ds, out=%s"
        % (len(urls), args.interval, args.out))

    if args.once:
        cycle(urls, args, state, state_path)
        log(args.log, "daemon exit (--once)")
        return 0

    while not STOP:
        cycle(urls, args, state, state_path)
        for _ in range(args.interval):
            if STOP:
                break
            time.sleep(1)

    log(args.log, "daemon stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
