# Vocabulary.com Automation

Answers Vocabulary.com assignment questions in Chrome using an answer cache first and OpenAI second. Runs one or several browser sessions at once.

## Features

- **Multiple sessions**: each session gets its own Chrome window and profile, so you can run several assignments or accounts side by side
- **Shared answer cache** (SQLite): an answer learned in one session is reused by all of them, and by later runs
- **Persistent logins**: each session's Chrome profile lives in `data/profiles/<name>`, so you sign in once
- Handles multiple-choice, sentence-context, image and spelling questions, countdown blockers, achievements and round screens
- Reloads the page when a question gets stuck
- Live terminal dashboard with per-session and all-time stats

## Requirements

- Python 3.10+
- Google Chrome
- An OpenAI API key

## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
```

Put your key in `config.json` (or leave it blank and set `OPENAI_API_KEY`). `config.json` is gitignored.

## Usage

```bash
python main.py            # one session
python main.py -n 3       # three sessions: session-1, session-2, session-3
python main.py -p alice -p bob   # named sessions, e.g. one per account
```

1. A Chrome window opens per session.
2. In each window, sign in and open an assignment. A session starts answering as soon as a question is on screen; no need to press anything.
3. When an assignment finishes, open another one in that window and it carries on.
4. Ctrl+C stops every session and closes only the bot's Chrome windows.

Closing a window ends just that session. Logs go to `logs/vocabbot.log`.

## Configuration (`config.json`)

| Key | Default | What it does |
|---|---|---|
| `openai_api_key` | | OpenAI key (falls back to `OPENAI_API_KEY`) |
| `model` | `gpt-4o-mini` | OpenAI model used when the cache has no answer |
| `chrome_options` | | Extra Chrome flags: `"disable_gpu": true` becomes `--disable-gpu`, `"window_size": "1280,900"` becomes `--window-size=1280,900` |
| `min_wait_time` / `max_wait_time` | 2 / 5 | Delay range in seconds. Before each click: half of min to min. After a wrong answer or reload: min to max |
| `log_level` | `INFO` | Log file level |

## Data

| Path | Contents |
|---|---|
| `data/vocabbot.db` | Answer cache and all-time counters (SQLite) |
| `data/profiles/<name>/` | Chrome profile per session (holds your login) |
| `logs/vocabbot.log` | Rotating log |

On first run, an existing `question_cache.json` and `statistics.json` are imported into the database once.

## Development

```bash
python -m pytest
```

## Notes

1. This tool is for educational purposes only.
2. Make sure you are allowed to use automation on Vocabulary.com.
3. Keep your OpenAI API key out of git.

## License

MIT. See LICENSE.
