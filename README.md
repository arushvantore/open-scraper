# open-scraper

Two small, read-only web scrapers that work on **any public website**.

| Tool | What it does |
|---|---|
| **`page_scraper.py`** | Scrape one or many pages **right now** into clean Markdown. |
| **`daemon.py`** | A background daemon that **keeps watching** those pages and saves a new file every time the content changes. |

No accounts. No API keys. No personal data. Nothing in this repo can log
you in anywhere — the tools only ever send plain `GET` requests.

**Created by [@arushvantore](https://github.com/arushvantore)** · MIT licensed · use it, fork it, ship it.

---

## 📖 Prefer a printable guide?

**[GUIDE.pdf](GUIDE.pdf)** — a 10-page, step-by-step walkthrough with real
commands and real terminal output: install, scrape one page, grab a section
with a selector, scrape a list, run the daemon, keep it running after you
close the terminal, and full troubleshooting.

- Read it straight from the repo, or download it.
- Source lives in [`GUIDE.html`](GUIDE.html) — open it in any browser.
- Rebuild the PDF yourself with `.venv/bin/python make_guide.py`.

If you like reading in your terminal instead, this README is the complete
reference and covers exactly the same ground.

---

## Safety promise (read this once)

These tools are built to be boring and safe:

- **Read-only.** They fetch pages. They never submit a form, never post,
  never like, never follow, never upload anything.
- **No logins.** There is no cookie, password, or session support at all —
  by design, not by accident. If a page is behind a login, this tool
  cannot and will not open it.
- **robots.txt respected by default.** If a site's `robots.txt` says
  "don't fetch this", the tool skips it and prints `SKIP`.
  Override only on sites you own with `--no-robots`.
- **Polite by default.** One page at a time with a sleep between them
  (2 seconds). No parallel hammering.
- **Your output never leaves your machine.** The `output/` folder is
  gitignored, so scraped content can never be pushed to GitHub by accident.

You are responsible for what you scrape. Only scrape pages you're allowed
to scrape, and follow each site's Terms of Service.

---

## Install (3 commands, once)

Requires **Python 3.10+**.

```sh
git clone https://github.com/YOUR-USERNAME/open-scraper.git
cd open-scraper

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

Windows (PowerShell) uses `.venv\Scripts\python` instead of `.venv/bin/python`.

**Check it works:**

```sh
.venv/bin/python page_scraper.py https://example.com
```

You should see `SAVE output/example-com.md (… words, hash …)`.

---

## 1 — `page_scraper.py` : scrape pages right now

### The basics

```sh
# one page
.venv/bin/python page_scraper.py https://example.com

# several pages in one go
.venv/bin/python page_scraper.py https://a.com https://b.com https://c.com

# a list from a file (one URL per line, # for comments)
.venv/bin/python page_scraper.py --targets targets.txt
```

Each page becomes a Markdown file in `output/` with a header:

```markdown
---
url: https://example.com/
title: Example Domain
fetched: 2026-10-27T18:31:34Z
selector: (whole page)
word_count: 133
content_hash: a4ccdd75cf70ea93
---

# Example Domain

This domain is for use in documentation examples …
```

Headings, links, lists, code blocks, quotes and images all survive the
conversion. Scripts, styles and navigation junk are dropped.

### Useful flags

| Flag | What it does |
|---|---|
| `--targets FILE` | Read URLs from a file instead of the command line. |
| `--selector "css"` | Grab **only one element** — an article, a table, a div. |
| `--links` | Append every link found on the page to the output file. |
| `--screenshot` | Also save a full-page `.png` next to the `.md`. |
| `--json FILE` | Write a machine-readable summary of what was scraped. |
| `--out DIR` | Choose the output folder (default: `output`). |
| `--timeout N` | Seconds to wait for the page (default: `30`). |
| `--wait MS` | Extra time for JavaScript to finish (default: `1500`). |
| `--pause N` | Seconds to sleep between URLs (default: `2`). |
| `--headful` | Show the browser window instead of running hidden. |
| `--no-robots` | Ignore `robots.txt`. **Only use on sites you own.** |

### Real examples

```sh
# only the <article> element of a blog post
.venv/bin/python page_scraper.py https://some.site/post/1 --selector "article"

# a pricing table plus every link, also as JSON
.venv/bin/python page_scraper.py https://example.com/pricing \
    --selector "table.pricing" --links --json summary.json

# a JS-heavy single-page app — give it more time to render
.venv/bin/python page_scraper.py https://example.com/app --wait 5000

# watch the page render, for debugging a selector
.venv/bin/python page_scraper.py https://example.com --headful
```

> **Tip for finding a selector:** open the page in your browser, right-click
> the bit you want → *Inspect* → right-click the highlighted HTML →
> *Copy* → *Copy selector*.

---

## 2 — `daemon.py` : keep watching pages in the background

Give it a list of URLs and an interval. Every cycle it re-fetches each one:

```
output/live/<name>.md              current state, always rewritten
output/archive/<timestamp>_<name>.md   written ONLY when the content changed
daemon.log                         timeline of every cycle
```

### Run it

```sh
# one cycle, then exit (good for cron / launchd / Task Scheduler)
.venv/bin/python daemon.py --targets targets.txt --once

# run forever, checking every 5 minutes
.venv/bin/python daemon.py --targets targets.txt --interval 300

# check every hour, and only write archive files when something changed
.venv/bin/python daemon.py --targets targets.txt --interval 3600 --diff-only
```

Press **Ctrl-C** to stop. It finishes the page it's on, writes its state
file, prints `daemon stopped`, and exits cleanly.

### Example output

```
2026-10-27T18:39:11Z daemon start: 4 target(s), interval 300s, out=output
  NEW   https://example.com -> 20261027_183911_example-com.md
2026-10-27T18:39:11Z CHANGED https://example.com (133 words)
  same  https://news.ycombinator.com
2026-10-27T18:39:35Z cycle done: 4 seen, 4 changed, 0 failed
```

Second run, nothing moved:

```
  same  https://example.com
  same  https://www.python.org
2026-10-27T18:40:02Z cycle done: 4 seen, 0 changed, 0 failed
```

### Daemon flags

| Flag | What it does |
|---|---|
| `--targets FILE` | **Required.** Your URL list. |
| `--interval N` | Seconds between cycles (default: `300`). |
| `--once` | Run a single cycle and exit. |
| `--diff-only` | Don't write archive files, just log the changes. |
| `--out DIR` | Output folder (default: `output`). |
| `--log FILE` | Log file (default: `daemon.log`). |
| `--state FILE` | Where change-hashes live (default: `output/.state.json`). |
| `--selector "css"` | Watch only one element instead of the whole page. |
| `--pause N` | Seconds between URLs inside a cycle (default: `2`). |
| `--no-robots` | Ignore `robots.txt` (only on sites you own). |

### Keep it running after you close the terminal

The daemon only lives while its terminal window is open. To survive
reboots, let your OS scheduler start it.

**macOS — `launchd`:**

```sh
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.example.scraper.plist <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.example.scraper</string>
  <key>ProgramArguments</key><array>
    <string>/ABSOLUTE/PATH/open-scraper/.venv/bin/python</string>
    <string>/ABSOLUTE/PATH/open-scraper/daemon.py</string>
    <string>--targets</string><string>/ABSOLUTE/PATH/open-scraper/targets.txt</string>
    <string>--interval</string><string>300</string>
  </array>
  <key>WorkingDirectory</key><string>/ABSOLUTE/PATH/open-scraper</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
XML
launchctl load ~/Library/LaunchAgents/com.example.scraper.plist
launchctl unload ~/Library/LaunchAgents/com.example.scraper.plist   # stop
```

**Linux — cron** (every 10 minutes, log to a file):

```cron
*/10 * * * * cd /path/open-scraper && .venv/bin/python daemon.py --targets targets.txt --once >> daemon.log 2>&1
```

**Windows — Task Scheduler:** point it at
`.\.venv\Scripts\python.exe daemon.py --targets targets.txt --once` with
*"Run whether user is logged on or not"*.

---

## Your URL list: `targets.txt`

```
# One URL per line. Lines starting with # are ignored.
# Only public pages here - this tool cannot log in anywhere.

https://example.com
https://www.python.org
https://en.wikipedia.org/wiki/Web_scraping
https://news.ycombinator.com
```

Both tools read it the same way: `#` starts a comment, blank lines are
skipped, everything else must start with `http://` or `https://`.

---

## What gets saved (and what never does)

**Saved** — in `output/`, on your machine only:

```
output/
├── live/      current state of each watched page
├── archive/   one file per real change (daemon)
├── *.md       one-shot scrapes
└── .state.json  hashes the daemon uses to detect change
```

**Never saved anywhere in this repo:**

- credentials, cookies, tokens, passwords — the tools have no concept of them
- browser profiles — not created, not read
- scraped page content — `output/` is in `.gitignore`
- log files — also gitignored

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Playwright is not installed` | `pip install -r requirements.txt` |
| Browser errors / missing executable | `.venv/bin/playwright install chromium` |
| `SKIP … (robots.txt disallows)` | Expected — the site asked not to be scraped. Use `--no-robots` only if you own it. |
| `FAIL … Timeout 30000ms exceeded` | Slow site. Raise it: `--timeout 60`. |
| Output is empty | The page renders with JavaScript. Raise `--wait 5000`, or add `--selector`. |
| `Selector … matched nothing` | Check the CSS selector in your browser's DevTools. |
| `these are not http(s) URLs` | A line in `targets.txt` is missing `https://`. |
| Daemon stops when I close the terminal | That's normal — use `launchd` / cron / Task Scheduler (above). |

---

## Files in this repo

```
page_scraper.py     one-shot + batch scraper
daemon.py           change-watching background daemon
GUIDE.pdf           printable 10-page user guide
GUIDE.html          editable source of that guide
make_guide.py       rebuilds GUIDE.pdf from GUIDE.html
targets.txt         example URL list
requirements.txt    pinned dependencies (playwright only)
LICENSE             MIT
README.md           this file
output/README.md    explains the (gitignored) output folder
.gitignore          keeps output, logs and any future secrets out of git
```

---

## License

MIT — see [LICENSE](LICENSE). Free to use, modify and redistribute.
