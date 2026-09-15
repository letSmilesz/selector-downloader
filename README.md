# Selector Downloader

A manga & light-novel downloader: chapters are saved as **CBZ** archives or image folders,
light novels as **EPUB** (text + illustrations). It drives a real Google Chrome browser
(Playwright) with your persistent profile: cookies, site settings and random 3–8 s delays
between chapters — just like a regular reader.

All site specifics live in JSON presets (`presets/`) — the engine knows nothing
about particular sites.

## Features

- Two interfaces: GUI (Flet) and CLI.
- Manga: `web` (scroll feed) and `page` (paged) reading modes; light novels → EPUB.
- Chapter/volume ranges, "N chapters starting from…", single chapter by URL (`--single`).
- Soft **Stop** with no loss of already downloaded data.
- Chapter/page progress, "slow download" notifications, log.
- Shared browser profile: log in once, cookies work for every run.

Primary platform: Windows.

## Requirements

- Python 3.10+
- Pinned Chrome for Testing (installed once via `scripts/setup_chrome.py`)
- Dependencies: `pip install playwright flet` (Flet 0.80+)

## Running

```
# First setup (one-time)
python scripts/setup_chrome.py

# GUI (Windows double-click)
run_gui.vbs   # silent mode, no console window
run_gui.bat   # console mode, errors visible

# GUI (manual)
python frontend/main_window.py

# CLI
python main.py "<title or chapter URL>" --mode web
```

## First run

1. Click **🔑 Log in** — a browser with the shared profile opens.
   Log in to the sites you need, then click **⏹ Finish login**. Cookies are saved.
2. Paste the title (or chapter) URL, pick a mode, press **Start**.
3. The preset is selected automatically by the URL domain.

## Ideal workflow for a new site / custom preset

1. If you built the preset yourself, first verify it works: download one chapter
   in the chosen mode.
2. Do test runs: a couple of chapters in one mode, then a couple of **different**
   chapters in the other mode. Different on purpose: the browser caches pages,
   so re-running the same chapters finishes instantly and tells you nothing.
3. Pick the best mode. The same site may fail in paged mode but work great in web —
   or crawl in web and fly in paged mode.
4. VPN, your network and the site's server all affect speed. Experiment with a couple
   of chapters first, then run the full range.

## Using the GUI

- **URL** — title page (table of contents) or a specific chapter.
- **Mode** — `web` / `page`. Ignored for light novels.
- **Chapters: start/end** — empty end = exactly one chapter; `-1` = "to the end".
- **Volumes** — optional.
- **Chapter count** — how many to download from the start chapter; overrides the range.
- **Chapter by link** — the URL points straight to a chapter; no TOC lookup needed.
- **Output folder + "Create subfolder"** — each run goes into `title1`, `title2`, …
  so different titles don't overwrite each other.
- **Save as CBZ** — off = chapters as image folders.
- **Clean temps of failed chapters** — off keeps `.tmp` folders for inspection.
- **Show browser window** — headed mode for diagnostics.
- **Debug mode** — verbose output, file log and HTML dumps.
- **Show log** — log window instead of the results table.

Delays between chapters are fixed: 3–8 s.

## Stop

**Stop** is a soft shutdown: a flag file + a signal to the process. Everything downloaded
before the stop is kept: manga is packed into CBZ chapter by chapter as it goes;
light novels are assembled into an EPUB from the accumulated buffer.
The chapter in progress is interrupted.

**Kill now** is a deliberate hard kill: the current chapter and the light-novel buffer are lost.

If the process crashed, the next run may say "Profile is busy" — delete
`chrome_profile/.downloader.lock` manually.

## Presets

A preset is a JSON file: site selectors, chapter/volume regexes,
popup texts, rate-limit banner markers. The engine knows nothing
about particular sites — all behaviour comes from the preset.

### Where to get ready-made presets

Presets for supported sites are published in the Telegram channel:
**https://t.me/manga_selector_downloader**

Download the `.json` files you need and drop them into the `presets/` folder
next to `main.py`. The preset is chosen automatically by the link domain;
override with the **⚙ Presets** button in the GUI or `--preset <name>` in the CLI.

### Building your own preset

1. Grab selectors from the site's DevTools (see `HOWTO_cleanup.txt`).
2. Feed them to an LLM together with the prompt `llm_prompts/full.md` →
   you get a JSON + a "CHECK IN CONSOLE" block.
3. Verify selectors in the browser console (F12 → Console).
4. Save the JSON to `presets/<site_name>.json` and open it in the GUI editor
   to check the fields.

**Lifehack:** the `hidden_chapters_btn` role ("expand hidden chapters") can be used
more cleverly. Point it at a "Sort from first chapter" button instead of "Show hidden" —
the TOC opens at the first page and no scrolling is needed.
A "Read from the beginning" button works too: downloading starts at chapter 1 anyway.

## Limitations

- Tabs opened by the site (ads, chapter in a new tab) are closed:
  all currently supported sites navigate within a single tab.
- After a crash the lock file must be removed manually (see "Stop").

## Troubleshooting

1. Enable **Debug mode** and **Show log**, run again.
2. Enable **Show browser window** — you can see where the script gets stuck.
3. `debug_*.html` dumps appear in the project root — snapshots of the page at failure time.
4. Typical symptoms:
   - "Could not extract chapter number" → preset regexes;
   - chapter downloaded empty → `image_selector`;
   - placeholders instead of pages → `banned_paths`; for sites with referer-protected
      images start from the title URL, not "chapter by link".
      Some sites return 404 on direct navigation — the downloader automatically retries
      via referer fallback (visible in debug log as `goto: статус 404...` + `_goto_cross_site...`).

## Advanced: where things live

| Path | Purpose |
|---|---|
| `main.py` | CLI entry point |
| `frontend/main_window.py` | GUI (Flet) |
| `frontend/preset_window.py`, `frontend/config.py` | preset editor, GUI settings |
| `browser/driver.py` | browser launch: persistent profile, lock, anti-detect |
| `browser/interceptor.py` | intercepts images from the browser cache + fetch fallback |
| `engine/toc_walker.py` | TOC: target chapter search, link click |
| `engine/reader.py` | chapter download (web / page / light novel), modes, popups |
| `engine/worker.py` | chapter loop via the "next" button, stop flag |
| `core/` | log + events, preset manager, file naming, delays, defaults |
| `output/archiver.py`, `output/epub.py` | CBZ and EPUB building |
| `scripts/gui_auth.py` | login browser |
| `scripts/setup_chrome.py` | installs pinned Chrome for Testing 152|
| `scripts/pw_test.py`| developer mode: browser under Playwright for preset debugging |
| `run_gui.bat` / `run_gui.vbs` | Windows GUI launchers (console / silent) |
| `presets/*.json` | site presets |
| `downloads/` | output (default) |
| `chrome_profile/` | persistent browser profile. **Contains your cookies — never publish.** |
| `.stop_download` | soft-stop flag file |
| `debug_*.html` | page dumps (debug mode only) |

## CLI

```
python main.py "<title URL>"   --mode web --count 3                # 3 chapters from start
python main.py "<title URL>"   --mode web --chapters 5-10          # range
python main.py "<title URL>"   --mode web --chapters 3--1          # from 3 to the end
python main.py "<chapter URL>" --mode web --single                 # exactly one chapter
python main.py --setup "<URL>"                                     # manual profile setup
```

Useful flags: `--headed` (visible browser), `--debug`, `--no-cbz` (folders instead of CBZ),
`--volumes 1-3`, `--output <dir>`, `--preset <name>`, `--keep-failed-temps`.

## License

MIT.