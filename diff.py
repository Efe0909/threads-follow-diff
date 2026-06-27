#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Threads follow-diff — interactive CLI.

Finds which accounts you follow that don't follow you back, stores everything in
SQLite, and (optionally) tints the live Following list in a Chrome window:
GREEN = follows you back, RED = doesn't, WHITE = new since your last diff.

READ-ONLY. Never follows/unfollows. You log in yourself in the browser window;
the script never handles credentials.

Usage (with the virtualenv activated):
    python diff.py            # interactive
    python diff.py --metrics  # dump metadata as JSON (jq/bat), no UI
    python diff.py --no-theme # interactive, skip the colored window
    python diff.py --clean    # delete the DB and all caches (logs you out)

Selectors verified against live Threads DOM (2026-06-27); see comments inline.
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(PROJECT_DIR, ".chrome-profile")
DB_PATH = os.path.join(PROJECT_DIR, "threads.db")
HOME_URL = "https://www.threads.com/"

# Lazy-load scroll tuning. Slow / human-paced on purpose (ToS).
SCROLL_PAUSE = 1.5
STABLE_ROUNDS = 5
MAX_SCROLLS = 600

# ------------------------------------------------------------------------- i18n
LANG = "en"

STRINGS = {
    "en": {
        "yes_char": "y", "confirm_hint": "[y/N]",
        "no_saved": "\nNo saved login — you'll log in in the browser window.",
        "login_header": "\nLogin — saved session: @{saved}",
        "use_last": "Use last login (@{saved})",
        "new_acc": "Log in to a new account (clears saved session)",
        "login_title": "\n=== LOG IN ===",
        "login_open": "A Chrome window is open — log into Threads there.",
        "login_wait": "The script will NOT touch your password and continues "
                      "automatically once you're in (waiting up to {n} min).",
        "login_ok": "Logged in as @{h} — continuing.",
        "login_timeout": "[!] Login timed out. Aborting.",
        "diff_header": "\nDiff — previous diff for @{handle}: {ts} "
                       "({n} don't follow back)",
        "diff_new": "Run a new diff (scrape Threads now)",
        "diff_prev": "Use the previous diff from the database",
        "collect_followers": "Collecting Followers...",
        "collect_following": "Collecting Following...",
        "summary": "\nFollowing: {g}   Followers: {f}   "
                   "Don't follow back: {nf}",
        "using_prev": "\nUsing previous diff from {ts}: {n} don't follow back.",
        "stored": "Stored in {db} (query with: python diff.py --metrics)",
        "theme_legend": "\nThemed Following: GREEN=follows you back, "
                        "RED=doesn't, WHITE=new since last diff.",
        "theme_help": "Scroll to review; unfollow the RED ones by hand. "
                      "Close the window when done.",
        "theme_fail": "[!] Could not open Following tab for theming.",
        "invalid": "Invalid choice.\n",
        "clean_nothing": "Nothing to clean.",
        "clean_will": "Will delete:",
        "reason_db": "diff history + metadata",
        "reason_profile": "browser session / login — deleting this logs you out",
        "reason_pycache": "python bytecode cache",
        "clean_proceed": "\nProceed? {hint} ",
        "clean_aborted": "Aborted.",
        "clean_done": "Cleaned.",
    },
    "tr": {
        "yes_char": "e", "confirm_hint": "[e/H]",
        "no_saved": "\nKayıtlı giriş yok — tarayıcı penceresinde giriş "
                    "yapacaksın.",
        "login_header": "\nGiriş — kayıtlı oturum: @{saved}",
        "use_last": "Son girişi kullan (@{saved})",
        "new_acc": "Yeni hesapla giriş yap (kayıtlı oturumu siler)",
        "login_title": "\n=== GİRİŞ ===",
        "login_open": "Bir Chrome penceresi açıldı — Threads'e oradan giriş yap.",
        "login_wait": "Parolana dokunulmayacak; giriş yapınca otomatik devam "
                      "eder (en fazla {n} dk beklenir).",
        "login_ok": "@{h} olarak giriş yapıldı — devam ediliyor.",
        "login_timeout": "[!] Giriş zaman aşımına uğradı. İptal ediliyor.",
        "diff_header": "\nDiff — @{handle} için önceki diff: {ts} "
                       "({n} geri takip etmiyor)",
        "diff_new": "Yeni diff çalıştır (Threads'i şimdi tara)",
        "diff_prev": "Veritabanındaki önceki diff'i kullan",
        "collect_followers": "Takipçiler toplanıyor...",
        "collect_following": "Takip edilenler toplanıyor...",
        "summary": "\nTakip edilen: {g}   Takipçi: {f}   "
                   "Geri takip etmeyen: {nf}",
        "using_prev": "\n{ts} tarihli önceki diff kullanılıyor: "
                      "{n} geri takip etmiyor.",
        "stored": "{db} içine kaydedildi (sorgu: python diff.py --metrics)",
        "theme_legend": "\nTakip edilenler renklendi: YEŞİL=seni geri takip "
                        "ediyor, KIRMIZI=etmiyor, BEYAZ=son diff'ten beri yeni.",
        "theme_help": "İncelemek için kaydır; KIRMIZI olanları elle takipten "
                      "çık. Bitince pencereyi kapat.",
        "theme_fail": "[!] Renklendirme için Takip edilenler sekmesi açılamadı.",
        "invalid": "Geçersiz seçim.\n",
        "clean_nothing": "Silinecek bir şey yok.",
        "clean_will": "Silinecekler:",
        "reason_db": "diff geçmişi + meta veriler",
        "reason_profile": "tarayıcı oturumu / giriş — bunu silmek seni çıkış "
                          "yaptırır",
        "reason_pycache": "python bytecode önbelleği",
        "clean_proceed": "\nDevam edilsin mi? {hint} ",
        "clean_aborted": "İptal edildi.",
        "clean_done": "Temizlendi.",
    },
}


def t(key, **kw):
    s = STRINGS.get(LANG, STRINGS["en"]).get(key) or STRINGS["en"][key]
    return s.format(**kw) if kw else s


def ts():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account             TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    followers_count     INTEGER,
    following_count     INTEGER,
    non_followers_count INTEGER,
    mutual_count        INTEGER
);
CREATE TABLE IF NOT EXISTS members (
    run_id       INTEGER NOT NULL,
    handle       TEXT NOT NULL,
    display_name TEXT,
    follows_me   INTEGER NOT NULL DEFAULT 0,
    i_follow     INTEGER NOT NULL DEFAULT 0,
    position     INTEGER,
    PRIMARY KEY (run_id, handle),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def meta_set(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at",
        (key, str(value), ts()),
    )
    conn.commit()


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_all(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def latest_run(conn, account):
    return conn.execute(
        "SELECT * FROM runs WHERE account=? AND finished_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (account,),
    ).fetchone()


def save_run(conn, account, followers, following):
    """Persist one diff run + full member snapshot. followers/following are
    dicts {handle: display_name}, following in app order."""
    cur = conn.execute(
        "INSERT INTO runs(account, started_at) VALUES(?,?)", (account, ts())
    )
    run_id = cur.lastrowid
    order_index = {h: i for i, h in enumerate(following)}
    rows = []
    for h in set(followers) | set(following):
        name = following.get(h) or followers.get(h) or ""
        rows.append((run_id, h, name, int(h in followers),
                     int(h in following), order_index.get(h)))
    conn.executemany(
        "INSERT INTO members(run_id, handle, display_name, follows_me, "
        "i_follow, position) VALUES(?,?,?,?,?,?)",
        rows,
    )
    fc, gc = len(followers), len(following)
    nf = sum(1 for h in following if h not in followers)
    mut = sum(1 for h in following if h in followers)
    conn.execute(
        "UPDATE runs SET finished_at=?, followers_count=?, following_count=?, "
        "non_followers_count=?, mutual_count=? WHERE id=?",
        (ts(), fc, gc, nf, mut, run_id),
    )
    conn.commit()
    return run_id, {"followers": fc, "following": gc,
                    "non_followers": nf, "mutual": mut}


def run_following(conn, run_id):
    """Following list of a stored run, in app order: [(handle, name, follows_me)]."""
    return [(r["handle"], r["display_name"], bool(r["follows_me"]))
            for r in conn.execute(
                "SELECT handle, display_name, follows_me FROM members "
                "WHERE run_id=? AND i_follow=1 ORDER BY position", (run_id,))]


def run_following_handles(conn, run_id):
    return {r["handle"] for r in conn.execute(
        "SELECT handle FROM members WHERE run_id=? AND i_follow=1", (run_id,))}


# --------------------------------------------------------------------- selenium

def _build_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=opts)


def make_driver(tries=3):
    last = None
    for i in range(tries):
        try:
            return _build_driver()
        except WebDriverException as e:
            last = e
            print(f"[!] driver start failed ({i + 1}/{tries}), retrying...")
            time.sleep(2)
    raise last


def own_handle_dom(driver):
    """Own handle from the current page's primary nav (no navigation)."""
    return driver.execute_script(
        r"""const a=Array.from(document.querySelectorAll(
              "[role='navigation'] a[href^='/@'], nav a[href^='/@']"))
            .find(a=>/^\/@[^\/]+$/.test(a.getAttribute('href')));
            return a ? a.getAttribute('href').slice(2) : null;"""
    )


def wait_logged_in(driver, timeout=300):
    """Return own handle once logged in. If logged out, open the window and poll
    until the user logs in (no stdin). Credentials never touched."""
    driver.get(HOME_URL)
    time.sleep(3)
    h = own_handle_dom(driver)
    if h:
        return h
    print(t("login_title"))
    print(t("login_open"))
    print(t("login_wait", n=timeout // 60))
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        url = driver.current_url
        if any(s in url for s in ("/login", "instagram.com", "facebook.com",
                                  "accountscenter")):
            continue
        driver.get(HOME_URL)
        time.sleep(2)
        h = own_handle_dom(driver)
        if h:
            print(t("login_ok", h=h))
            return h
    return None


def find_scroll_container(driver):
    return driver.execute_script(
        """
        const dlg = document.querySelector("div[role='dialog']");
        if (!dlg) return null;
        for (const el of dlg.querySelectorAll('div')) {
            const s = getComputedStyle(el);
            if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                && el.scrollHeight > el.clientHeight + 20) return el;
        }
        return dlg;
        """
    )


def open_followers_modal(driver, tries=3):
    """Native-click the 'N followers' count (synthetic JS click won't open it)."""
    for _ in range(tries):
        if find_scroll_container(driver) is not None:
            return True
        el = driver.execute_script(
            r"""
            const re = /\b(followers?|takip(ç|c)i)\b/i;
            const c = Array.from(document.querySelectorAll('span, div, a'))
                .filter(e => { const t = e.textContent.trim();
                               return re.test(t) && t.length>0 && t.length<30; });
            if (!c.length) return null;
            c.sort((a, b) => a.textContent.trim().length
                             - b.textContent.trim().length);
            return c[0];
            """
        )
        if el is not None:
            try:
                el.click()
            except WebDriverException:
                pass
        time.sleep(2.5)
        if find_scroll_container(driver) is not None:
            return True
    return False


def switch_tab(driver, label):
    """Native-click a modal tab via div[role=button][aria-label] (top-most)."""
    el = driver.execute_script(
        """
        const label = arguments[0];
        const dlg = document.querySelector("div[role='dialog']");
        if (!dlg) return null;
        let c = Array.from(dlg.querySelectorAll(
            "div[role='button'][aria-label='" + label + "']"));
        if (!c.length) return null;
        c.sort((a, b) => a.getBoundingClientRect().top
                         - b.getBoundingClientRect().top);
        return c[0];
        """,
        label,
    )
    if el is None:
        return False
    try:
        el.click()
    except WebDriverException:
        return False
    time.sleep(2.5)
    return True


def scrape_open_list(driver, kind):
    """Scroll the open modal list and return {handle: display_name} in order."""
    container = find_scroll_container(driver)
    if container is None:
        print(f"[!] No modal container for {kind}.")
        return {}
    seen = {}
    stable = scrolls = 0
    while stable < STABLE_ROUNDS and scrolls < MAX_SCROLLS:
        rows = driver.execute_script(
            r"""
            const dlg = document.querySelector("div[role='dialog']");
            if (!dlg) return [];
            const out = [];
            dlg.querySelectorAll("a[href^='/@']").forEach(a => {
                const m = a.getAttribute('href').match(/^\/(@[^\/?#]+)/);
                if (!m) return;
                const handle = m[1];
                let row = a;
                for (let i = 0; i < 8 && row; i++) {
                    row = row.parentElement;
                    if (row && row.innerText && row.innerText.indexOf('\n') >= 0)
                        break;
                }
                let name = '';
                if (row) {
                    const lines = row.innerText.split('\n')
                        .map(s => s.trim()).filter(Boolean);
                    const idx = lines.indexOf(handle.slice(1));
                    if (idx >= 0 && lines[idx + 1]
                        && !['Following','Follow','Follow back','Takip',
                             'Takip et'].includes(lines[idx + 1]))
                        name = lines[idx + 1];
                }
                out.push([handle, name]);
            });
            return out;
            """
        )
        before = len(seen)
        for handle, name in rows:
            if handle not in seen or (not seen[handle] and name):
                seen[handle] = name
        stable = 0 if len(seen) > before else stable + 1
        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollHeight;", container)
        time.sleep(SCROLL_PAUSE)
        scrolls += 1
        print(f"  {kind}: {len(seen)} (scroll {scrolls}, stable {stable})",
              end="\r")
    print()
    return seen


def scrape(driver, handle):
    """Open the profile modal and scrape both lists. Returns (followers, following)."""
    driver.get(f"{HOME_URL}@{handle}")
    time.sleep(3)
    if not open_followers_modal(driver):
        raise RuntimeError("could not open the followers modal")
    switch_tab(driver, "Followers")
    print(t("collect_followers"))
    followers = scrape_open_list(driver, "followers")
    if not switch_tab(driver, "Following"):
        raise RuntimeError("could not open the Following tab")
    print(t("collect_following"))
    following = scrape_open_list(driver, "following")
    if not followers or not following:
        raise RuntimeError("a list came back empty")
    return followers, following


# ------------------------------------------------------------------------ theme

THEME_JS = r"""
const status = new Map(arguments[0]);   // [[handle, follows_me_bool], ...]
const baseline = new Set(arguments[1]); // handles known as of the last diff
const GREEN='#16a34a', RED='#dc2626', WHITE='#ffffff';
function isRowBtn(x){
    return /^(Following|Takip)/i.test(x.innerText.trim())
           && !x.getAttribute('aria-label');   // exclude the tab buttons
}
function btnInRow(a){
    let blk=a;
    for(let i=0;i<10&&blk;i++){
        blk=blk.parentElement; if(!blk) break;
        const b=Array.from(blk.querySelectorAll("div[role='button'],button"))
            .find(isRowBtn);
        if(b) return b;
    }
    return null;
}
function colorize(){
    const dlg=document.querySelector("div[role='dialog']");
    if(!dlg) return;
    dlg.querySelectorAll("a[href^='/@']").forEach(a=>{
        const m=a.getAttribute('href').match(/^\/(@[^\/?#]+)/); if(!m) return;
        const h=m[1], btn=btnInRow(a); if(!btn) return;
        let bg, fg='#fff', bd;
        if(!baseline.has(h)){ bg=WHITE; fg='#111'; bd='#9ca3af'; }  // new
        else if(status.get(h)){ bg=GREEN; bd=GREEN; }               // mutual
        else { bg=RED; bd=RED; }                                    // non-follower
        btn.style.setProperty('background-color', bg, 'important');
        btn.style.setProperty('color', fg, 'important');
        btn.style.setProperty('border-color', bd, 'important');
    });
}
colorize();
const dlg=document.querySelector("div[role='dialog']");
if(dlg) new MutationObserver(colorize).observe(dlg,{childList:true,subtree:true});
if(window.__themeTimer) clearInterval(window.__themeTimer);
window.__themeTimer=setInterval(colorize, 800);
"""


def apply_theme(driver, handle, status_map, baseline):
    """Open Following tab, tint rows, keep window open until the user closes it."""
    driver.get(f"{HOME_URL}@{handle}")
    time.sleep(3)
    if not open_followers_modal(driver) or not switch_tab(driver, "Following"):
        print(t("theme_fail"))
        return
    driver.execute_script(THEME_JS, list(status_map.items()), list(baseline))
    print(t("theme_legend"))
    print(t("theme_help"))
    try:
        while driver.window_handles:
            time.sleep(2)
    except WebDriverException:
        pass


# ------------------------------------------------------------------------- CLI

def ask(prompt, options):
    """options: list of (key, label). Returns chosen key."""
    keys = {k for k, _ in options}
    while True:
        print(prompt)
        for k, label in options:
            print(f"  [{k}] {label}")
        ans = input("> ").strip()
        if ans in keys:
            return ans
        print(t("invalid"))


def cmd_metrics():
    """Dump metadata + latest-run summary as JSON. No browser, no formatting."""
    conn = db_connect()
    out = {"meta": meta_all(conn)}
    acct = meta_get(conn, "last_account")
    run = latest_run(conn, acct) if acct else None
    out["latest_run"] = dict(run) if run else None
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def cmd_clean(assume_yes=False):
    """Delete the DB and all caches: threads.db (diff history/metadata) and
    .chrome-profile (browser session — THIS LOGS YOU OUT). Irreversible."""
    pycache = os.path.join(PROJECT_DIR, "__pycache__")
    targets = [
        (DB_PATH, t("reason_db")),
        (PROFILE_DIR, t("reason_profile")),
        (pycache, t("reason_pycache")),
    ]
    existing = [(p, why) for p, why in targets if os.path.exists(p)]
    if not existing:
        print(t("clean_nothing"))
        return
    print(t("clean_will"))
    for p, why in existing:
        size = _dir_size(p) if os.path.isdir(p) else os.path.getsize(p)
        print(f"  {p}  ({size / 1024:.0f} KB) — {why}")
    if not assume_yes:
        if input(t("clean_proceed", hint=t("confirm_hint"))).strip().lower() \
                != t("yes_char"):
            print(t("clean_aborted"))
            return
    for p, _ in existing:
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError as e:
                print(f"[!] could not remove {p}: {e}")
    print(t("clean_done"))


def interactive(do_theme=True):
    conn = db_connect()

    # 1) Login: reuse the saved session or start a new account.
    saved = meta_get(conn, "last_account")
    has_profile = os.path.isdir(PROFILE_DIR) and bool(saved)
    reuse = True
    if has_profile:
        choice = ask(
            t("login_header", saved=saved),
            [("1", t("use_last", saved=saved)),
             ("2", t("new_acc"))],
        )
        reuse = choice == "1"
    else:
        print(t("no_saved"))

    if not reuse:
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)

    driver = make_driver()
    try:
        handle = wait_logged_in(driver)
        if not handle:
            print(t("login_timeout"))
            return
        meta_set(conn, "last_account", handle)
        meta_set(conn, "last_login_at", ts())

        # 2) Diff: scrape fresh, or reuse the previous diff from the DB.
        prev = latest_run(conn, handle)
        do_scrape = True
        if prev:
            choice = ask(
                t("diff_header", handle=handle, ts=prev["started_at"],
                  n=prev["non_followers_count"]),
                [("1", t("diff_new")), ("2", t("diff_prev"))],
            )
            do_scrape = choice == "1"

        if do_scrape:
            baseline = run_following_handles(conn, prev["id"]) if prev else None
            followers, following = scrape(driver, handle)
            run_id, c = save_run(conn, handle, followers, following)
            for k, v in (("last_diff_at", ts()), ("last_run_id", run_id),
                         ("followers_count", c["followers"]),
                         ("following_count", c["following"]),
                         ("mutual_count", c["mutual"]),
                         ("non_followers_count", c["non_followers"])):
                meta_set(conn, k, v)
            status_map = {h: (h in followers) for h in following}
            # first ever run → nothing is "new"
            if baseline is None:
                baseline = set(following)
            non_followers = [(h, following[h]) for h in following
                             if h not in followers]
            print(t("summary", g=c["following"], f=c["followers"],
                    nf=c["non_followers"]))
        else:
            following_rows = run_following(conn, prev["id"])
            status_map = {h: fm for h, _, fm in following_rows}
            baseline = set(status_map)  # live rows not here → white (new)
            non_followers = [(h, name) for h, name, fm in following_rows
                             if not fm]
            print(t("using_prev", ts=prev["started_at"], n=len(non_followers)))

        print(t("stored", db=DB_PATH))

        if do_theme:
            apply_theme(driver, handle, status_map, baseline)
    finally:
        time.sleep(1)
        try:
            driver.quit()
        except WebDriverException:
            pass


def main():
    p = argparse.ArgumentParser(description="Threads follow-diff (interactive).")
    p.add_argument("--metrics", action="store_true",
                   help="dump metadata as JSON and exit (no browser)")
    p.add_argument("--clean", action="store_true",
                   help="delete the DB and all caches (logs you out), then exit")
    p.add_argument("--yes", "-y", action="store_true",
                   help="skip the --clean confirmation prompt")
    p.add_argument("--no-theme", action="store_true",
                   help="skip the colored review window")
    p.add_argument("--lang", choices=sorted(STRINGS),
                   help="interface language (default: last used, else en); "
                        "the choice is remembered")
    args = p.parse_args()

    # Resolve language: explicit flag wins and is remembered; else last-used.
    global LANG
    conn = db_connect()
    if args.lang:
        LANG = args.lang
        meta_set(conn, "lang", LANG)
    else:
        LANG = meta_get(conn, "lang", "en")
    conn.close()

    if args.clean:
        cmd_clean(assume_yes=args.yes)
        return
    if args.metrics:
        cmd_metrics()
        return
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    interactive(do_theme=not args.no_theme)


if __name__ == "__main__":
    main()
