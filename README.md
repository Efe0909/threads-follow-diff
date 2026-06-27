# threads-follow-diff

Find which accounts you follow on [Threads](https://www.threads.com) that **don't
follow you back**, store the results in SQLite, and (optionally) tint the live
Following list in a Chrome window so you can review and unfollow by hand.

**Read-only.** It never follows or unfollows anyone. You log into Threads
yourself in the browser window — the script never sees or handles your password.

## Setup

Requires Python 3.9+ and Google Chrome.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

(Or, if you have [uv](https://docs.astral.sh/uv/): `uv venv .venv && uv pip
install -r requirements.txt`.)

## Usage

```bash
.venv/bin/python diff.py            # interactive
.venv/bin/python diff.py --no-theme # interactive, no colored window (DB only)
.venv/bin/python diff.py --metrics  # dump metadata as JSON (pipe to jq/bat)
.venv/bin/python diff.py --clean    # delete the DB + browser cache (logs you out)
```

Interactive flow asks two things, then acts:

1. **Login** — reuse the saved session, or log into a new account.
2. **Diff** — scrape Threads now, or reuse the previous diff from the database.

On the first run a Chrome window opens; log in and it continues automatically.
The session persists, so later runs are hands-off.

### The colored review window

After a diff, the Following list is tinted in place:

- 🟢 **green** — follows you back (mutual)
- 🔴 **red** — doesn't follow you back
- ⚪ **white** — new since your last diff

Scroll to review, unfollow the red ones manually, then close the window.
(White only appears from the second diff onward — the first run is the baseline.)

## Data

Everything lives in two places in the project directory:

- **`threads.db`** (SQLite) — diff history and metadata. Tables:
  - `meta` — key/value: last account, follower/following/mutual/non-follower
    counts, last login + last diff timestamps.
  - `runs` — one row per diff (counts + timestamps).
  - `members` — full snapshot per run: handle, display name, `follows_me`,
    `i_follow`, and `position` (preserves the app's Following order).
- **`.chrome-profile/`** — the Chrome profile holding your login session. This,
  not the database, is where the login is cached; the DB stores no credentials.

Inspect metrics with `--metrics | jq`. Reset history but stay logged in by
deleting `threads.db` only; full reset (incl. logout) is `--clean`.

## Notes

Scraping Threads is against Meta's ToS. Reading your own lists, read-only and at
modest scale, is low risk but not zero — runs are deliberately slow/human-paced.
Don't run it in rapid succession.
```
