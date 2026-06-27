# threads-follow-diff

**English** · [Türkçe](#türkçe)

Find which accounts you follow on [Threads](https://www.threads.com) that **don't
follow you back**, store the results in SQLite, and (optionally) tint the live
Following list in a Chrome window so you can review and unfollow by hand.

**Read-only.** It never follows or unfollows anyone. You log into Threads
yourself in the browser window — the script never sees or handles your password.

## Setup

Requires Python 3.9+ and Google Chrome.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(Windows cmd.exe: use `.venv\Scripts\activate.bat` instead of the PowerShell line.)

Or, if you have [uv](https://docs.astral.sh/uv/) on any platform:

```bash
uv venv .venv
uv pip install -r requirements.txt
```

## Usage

With the virtualenv activated:

```bash
python diff.py            # interactive
python diff.py --no-theme # interactive, no colored window (DB only)
python diff.py --metrics  # dump metadata as JSON (pipe to jq/bat)
python diff.py --clean    # delete the DB + browser cache (logs you out)
python diff.py --lang tr  # Turkish interface (remembered; en is default)
```

The interface language (`en` or `tr`) is remembered between runs once set with
`--lang`. Metrics output stays English JSON for piping.

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

---

# Türkçe

[Threads](https://www.threads.com)'te **takip ettiğin ama seni geri takip
etmeyen** hesapları bulur, sonuçları SQLite'a kaydeder ve (istersen) bir Chrome
penceresinde canlı Takip listesini renklendirir; böylece inceleyip elle takipten
çıkabilirsin.

**Salt-okunur.** Kimseyi takip etmez veya takipten çıkarmaz. Threads'e tarayıcı
penceresinde sen giriş yaparsın — script parolanı görmez ve ona dokunmaz.

## Kurulum

Python 3.9+ ve Google Chrome gerekir.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(Windows cmd.exe: PowerShell satırı yerine `.venv\Scripts\activate.bat` kullan.)

Ya da [uv](https://docs.astral.sh/uv/) varsa (her platformda):

```bash
uv venv .venv
uv pip install -r requirements.txt
```

## Kullanım

Sanal ortam etkinken:

```bash
python diff.py            # etkileşimli
python diff.py --no-theme # etkileşimli, renkli pencere yok (sadece DB)
python diff.py --metrics  # meta verileri JSON olarak yaz (jq/bat'e aktar)
python diff.py --clean    # DB + tarayıcı önbelleğini sil (çıkış yaptırır)
python diff.py --lang tr  # Türkçe arayüz (hatırlanır; varsayılan en)
```

Arayüz dili (`en` veya `tr`) `--lang` ile bir kez ayarlanınca sonraki
çalıştırmalarda hatırlanır. Metrics çıktısı, aktarım için İngilizce JSON kalır.

Etkileşimli akış iki şey sorar, sonra çalışır:

1. **Giriş** — kayıtlı oturumu kullan veya yeni hesapla giriş yap.
2. **Diff** — Threads'i şimdi tara veya veritabanındaki önceki diff'i kullan.

İlk çalıştırmada bir Chrome penceresi açılır; giriş yap, gerisi otomatik devam
eder. Oturum kalıcıdır, sonraki çalıştırmalar elle müdahale gerektirmez.

### Renkli inceleme penceresi

Diff'ten sonra Takip listesi yerinde renklenir:

- 🟢 **yeşil** — seni geri takip ediyor (karşılıklı)
- 🔴 **kırmızı** — seni geri takip etmiyor
- ⚪ **beyaz** — son diff'ten beri yeni

İncelemek için kaydır, kırmızıları elle takipten çık, sonra pencereyi kapat.
(Beyaz yalnızca ikinci diff'ten sonra görünür — ilk çalıştırma temeldir.)

## Veri

Her şey proje dizinindeki iki yerde tutulur:

- **`threads.db`** (SQLite) — diff geçmişi ve meta veriler. Tablolar:
  - `meta` — anahtar/değer: son hesap; takipçi/takip/karşılıklı/geri-takip-etmeyen
    sayıları; son giriş + son diff zamanları.
  - `runs` — her diff için bir satır (sayılar + zaman damgaları).
  - `members` — her çalıştırmanın tam anlık görüntüsü: kullanıcı adı, görünen ad,
    `follows_me`, `i_follow`, `position` (uygulamanın Takip sırasını korur).
- **`.chrome-profile/`** — giriş oturumunu tutan Chrome profili. Giriş burada
  saklanır, veritabanında değil; DB hiçbir kimlik bilgisi tutmaz.

Metrikleri `--metrics | jq` ile incele. Geçmişi sıfırlayıp giriş kalsın istersen
yalnızca `threads.db`'yi sil; tam sıfırlama (çıkış dahil) `--clean`.

## Notlar

Threads'i kazımak Meta'nın Kullanım Koşulları'na aykırıdır. Kendi listelerini
salt-okunur ve mütevazı ölçekte okumak düşük risklidir ama sıfır değildir —
çalıştırmalar bilerek yavaş/insan hızındadır. Art arda hızlıca çalıştırma.
