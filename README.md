# English Learner (web)
1. Get a key at console.anthropic.com. Set a monthly spend limit under Settings > Limits.
2. Run `python server.py`, open http://127.0.0.1:8000
3. Click **Settings**, paste your key, Save. (Stored in `.env`, git-ignored. Never share it.)
4. Optional: put a YouTube Data API v3 key in Settings to search YouTube in YouTube & music (🎵 List button on the music bar) (Google Cloud Console > enable "YouTube Data API v3" > Credentials > API key).

Switch provider in Settings: for Groq/Gemini/OpenRouter pick "OpenAI-compatible", then enter their /chat/completions URL and model name.
Privacy: do not type personal info; Anthropic keeps API data ~30 days.
Test: `python test_server.py`

## Progress and cloud
- Progress (words, grammar path, activity, course, story, habits) is saved on the server in `data/<user>.json` and cached in the browser. The server copy wins when the page loads. A copy of each file is kept every day for 7 days.
- `data/shared-dictionary.json` keeps every word meaning the AI has written (no personal data), so repeat lookups cost nothing.

## Running it online (production)
Set these environment variables on the host:

| Variable | What it does |
|---|---|
| `HOST=0.0.0.0`, `PORT` | Listen on the public address (`PORT` if the host gives one). |
| `APP_USERS=daisy:pass1,minh:pass2` | One password per person (recommended). The login name picks the progress file. |
| `APP_PASSWORD` | Instead of `APP_USERS`: one shared password, any login name. Anyone with it can open any name's progress. |
| `ADMIN_USER=daisy` | Only this login may change Settings (API key, model, budget). Without it, nobody can change Settings online. |
| `AI_DAILY_LIMIT=500` | Max AI requests per person per day (default 500). |

- The app refuses to start on a public address without `APP_USERS` or `APP_PASSWORD`.
- Use HTTPS (the host usually provides it): the login is sent with every request.
- Keep `data/`, `.env`, `.ytkey`, `config.json` and `usage.json` on a persistent disk.
- Auto-restart on code changes only runs on your own computer (`127.0.0.1`).
- Not done yet for many users: separate API keys or budgets per person, and a database instead of files.
