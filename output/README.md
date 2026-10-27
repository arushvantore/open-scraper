# output/

Scraped files land here. **This folder is gitignored on purpose** — your
scraped pages stay on your machine and never get pushed to GitHub.

- `live/<name>.md` — current state of each watched page (daemon)
- `archive/<timestamp>_<name>.md` — one file every time a page changed (daemon)
- `<name>.md` — one-shot scrapes (`page_scraper.py`)
- `.state.json` — hashes the daemon uses to detect change
