# English Learner (web)
1. Get a key at console.anthropic.com. Set a monthly spend limit under Settings > Limits.
2. Run `python server.py`, open http://127.0.0.1:8000
3. Click **Settings**, paste your key, Save. (Stored in `.env`, git-ignored. Never share it.)
4. Optional: put a YouTube Data API v3 key in Settings to search YouTube in YouTube & music (🎵 List button on the music bar) (Google Cloud Console > enable "YouTube Data API v3" > Credentials > API key).

Switch provider in Settings: for Groq/Gemini/OpenRouter pick "OpenAI-compatible", then enter their /chat/completions URL and model name.
Privacy: do not type personal info; Anthropic keeps API data ~30 days.
Test: `python test_server.py`

## Progress and cloud
- Progress (words, grammar path, activity, course) is saved on the server in `data/<user>.json` and also cached in the browser. The server copy wins when the page loads.
- Run on a cloud host: set `HOST=0.0.0.0`, `PORT` (if the host gives one) and `APP_PASSWORD`. The app refuses to start on a public address without a password. The browser then asks for a login: any user name, that password. The user name picks the progress file.
- Keep `data/`, `.env` and `.ytkey` on a persistent disk. Use HTTPS (the host usually provides it).
- Not done yet for many users: separate passwords per user, separate API keys/limits per user, and a database instead of files.
