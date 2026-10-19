# English Learner (web)
1. Get a key at console.anthropic.com. Set a monthly spend limit under Settings > Limits.
2. Run `python server.py`, open http://127.0.0.1:8000
3. Click **Settings**, paste your key, Save. (Stored in `.env`, git-ignored. Never share it.)
4. Optional: put a YouTube Data API v3 key in Settings to search YouTube inside the YouTube tab (Google Cloud Console > enable "YouTube Data API v3" > Credentials > API key).

Switch provider in Settings: for Groq/Gemini/OpenRouter pick "OpenAI-compatible", then enter their /chat/completions URL and model name.
Privacy: do not type personal info; Anthropic keeps API data ~30 days.
Test: `python test_server.py`
