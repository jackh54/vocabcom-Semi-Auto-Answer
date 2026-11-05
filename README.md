# Vocabulary.com Automation

Answers Vocabulary.com assignment questions in Chrome using an answer cache first and OpenAI second. Runs one or several browser sessions at once.

## Features

- **Multiple sessions**: each session gets its own Chrome window and profile, so you can run several assignments or accounts side by side
- **Shared answer cache** (SQLite): an answer learned in one session is reused by all of them, and by later runs
- **Saved accounts**: each account is its own Chrome profile in `data/profiles/<name>`, so you sign in once and pick accounts from a list at start
- Handles multiple-choice, sentence-context, image and spelling questions, countdown blockers, achievements and round screens
- Reloads the page when a question gets stuck
- Live terminal dashboard with per-session and all-time stats

## Download (no Python needed)

Grab the zip for your computer from the [latest release](https://github.com/jackh54/vocabcom-Semi-Auto-Answer/releases/latest), unzip it, and run `vocabbot`:

| Computer | File |
|---|---|
| Windows | `vocabbot-windows-x64.zip` → double-click `vocabbot.exe` |
| Mac with Apple Silicon (M1 and later) | `vocabbot-macos-arm64.zip` |
| Intel Mac | `vocabbot-macos-x64.zip` |

You need Google Chrome installed. On first run it asks for your OpenAI API key and saves it.

It shows the same account menu and dashboard as the source version, and takes the same flags (`vocabbot -a alice`, `vocabbot.exe -n 2`).

The builds aren't code-signed, so the OS warns the first time:
- **Windows:** SmartScreen says "Windows protected your PC" → **More info** → **Run anyway**.
- **Mac:** double-click shows "cannot be verified". Open **System Settings → Privacy & Security** and click **Open Anyway**, or run `xattr -d com.apple.quarantine vocabbot` in Terminal from the unzipped folder, then `./vocabbot`.

The packaged app keeps its config, saved accounts and logs in your user folder, so updating is just replacing the file:
- Mac: `~/Library/Application Support/vocabbot`
- Windows: `%LOCALAPPDATA%\vocabbot`

## Run from source

### Requirements

- Python 3.10+
- Google Chrome
- An OpenAI API key

### Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
```

Put your key in `config.json` (or leave it blank and set `OPENAI_API_KEY`). `config.json` is gitignored.

### Usage

```bash
python main.py                   # choose accounts from a list (or add new ones)
python main.py -a alice -a bob   # run these accounts without the list
python main.py -n 3              # three sessions named session-1..3
```

With no flags you get the account picker:

```
  #   Account   Last used
  1   alice     2026-11-05 10:47
  2   bob       2026-11-04 18:20
Accounts (1): 1, carol
```

Type numbers or names, separated by commas, or `all`. A name that isn't in the list becomes a new account. Each account you pick gets its own session and window.

1. A Chrome window opens per account.
2. Sign in the first time you use an account; after that it opens already signed in. Then open an assignment. A session starts answering as soon as a question is on screen; no need to press anything.
3. When an assignment finishes, open another one in that window and it carries on.
4. Ctrl+C stops every session and closes only the bot's Chrome windows.

Closing a window ends just that session. Logs go to `logs/vocabbot.log`.

An account is just a folder: rename `data/profiles/<old>` to change its name, delete the folder to forget it (and its login). An account can only run in one place at a time; if another `main.py` is using it, the picker marks it "running elsewhere".

### Configuration (`config.json`)

| Key | Default | What it does |
|---|---|---|
| `openai_api_key` | | OpenAI key (falls back to `OPENAI_API_KEY`) |
| `model` | `gpt-4o-mini` | OpenAI model used when the cache has no answer |
| `chrome_options` | | Extra Chrome flags: `"disable_gpu": true` becomes `--disable-gpu`, `"window_size": "1280,900"` becomes `--window-size=1280,900` |
| `min_wait_time` / `max_wait_time` | 3 / 5 | Seconds between answers: each answer is submitted a random min to max seconds after the previous one (retries after a wrong pick too). Also the wait after a page reload |
| `log_level` | `INFO` | Log file level |

## Data

| Path | Contents |
|---|---|
| `data/vocabbot.db` | Answer cache and all-time counters (SQLite) |
| `data/profiles/<name>/` | Chrome profile per account (holds its login) |
| `logs/vocabbot.log` | Rotating log |

On first run, an existing `question_cache.json` and `statistics.json` are imported into the database once.

## Development

```bash
python -m pytest
```

When running from source, data lives in the repo folder (`config.json`, `data/`, `logs/`). Set `VOCABBOT_HOME` to use another folder.

### Releases

`.github/workflows/release.yml` builds Windows, Apple Silicon and Intel Mac executables with PyInstaller, smoke-tests each one, and attaches the zips to a GitHub Release.

1. Bump `__version__` in `vocabbot/__init__.py`.
2. Commit, then tag and push: `git tag v2.0.1 && git push origin v2.0.1`.

The build fails if the tag doesn't match `__version__`. Builds use the exact versions in `constraints.txt`. Running the workflow by hand from the Actions tab builds without publishing.

Local build: `pip install -r requirements.txt pyinstaller -c constraints.txt && pyinstaller --onefile --name vocabbot main.py` (output in `dist/`).

## Notes

1. This tool is for educational purposes only.
2. Make sure you are allowed to use automation on Vocabulary.com.
3. Keep your OpenAI API key out of git.

## License

MIT. See LICENSE.
