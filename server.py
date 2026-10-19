"""English Learner web v1. Stdlib only. Run: python server.py -> http://127.0.0.1:8000
Provider "anthropic", or "openai" (any OpenAI-compatible: Gemini, Groq, OpenRouter)."""
import json, os, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
CFG_FILE, ENV_FILE = os.path.join(DIR, "config.json"), os.path.join(DIR, ".env")
KEYS = ("provider", "model", "base_url", "history_turns", "max_tokens")
SYSTEM = ("You are a friendly English tutor for a first-year Business English student. "
          "Reply in English only, short and simple. If the student's message has mistakes, "
          "first give the corrected sentence, then explain each mistake in one simple line. "
          "If it is correct, say so, then reply naturally and ask one short follow-up question.")

def load_cfg(): return json.load(open(CFG_FILE))
def get_key():
    return open(ENV_FILE).read().strip() if os.path.exists(ENV_FILE) else os.environ.get("LLM_API_KEY", "")

def trim(history, turns): return history[-2 * turns:]  # one turn = user + assistant

def ask(messages, system=SYSTEM, max_tokens=None):
    c, key = load_cfg(), get_key()
    if not key: raise ValueError("No API key yet. Open Settings and save your key.")
    anth = c["provider"] == "anthropic"
    messages = trim(messages, int(c["history_turns"]))
    body = {"model": c["model"], "max_tokens": int(max_tokens or c["max_tokens"]), "messages": messages}
    hdr = {"content-type": "application/json"}
    if anth:
        body["system"] = system
        hdr.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        body["messages"] = [{"role": "system", "content": system}] + messages
        hdr["authorization"] = "Bearer " + key
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(c["base_url"], json.dumps(body).encode(), hdr), timeout=60))
    except urllib.error.HTTPError as e:
        raise ValueError(f"API error {e.code}: {e.read().decode()[:200]}")
    return r["content"][0]["text"] if anth else r["choices"][0]["message"]["content"]

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
JSON_SYS = "You write English-learning material for a Vietnamese Business English student. Reply with ONLY valid JSON, no markdown."

def parse_json(t, o, c):
    try: return json.loads(t[t.index(o):t.rindex(c) + 1])
    except ValueError: raise ValueError("The AI reply was not valid. Please try again.")

def run_task(task, d):
    lv = d.get("level", "A1")
    if lv not in LEVELS: raise ValueError("Bad level")
    g = lambda k: str(d.get(k, ""))[:2000]  # cap input size (cost + abuse)
    if task == "cards":
        p = (f"CEFR level {lv}. Give 5 useful English words (prefer work/business/study words). "
             f"Do not use: {g('avoid')}. Return a JSON array of "
             '{"word":"","ipa":"/IPA/","vi":"short Vietnamese meaning","example":"one short English sentence"}.')
        return parse_json(ask([{"role": "user", "content": p}], JSON_SYS, 800), "[", "]")
    if task == "grammar":
        p = (f"CEFR level {lv}. Topic: {g('topic') or 'your choice, common for this level'}. Return JSON "
             '{"title":"","lesson":"max 100 words, simple, 2 examples","exercises":["5 short fill-in-the-blank or correct-the-sentence items"]}.')
        return parse_json(ask([{"role": "user", "content": p}], JSON_SYS, 900), "{", "}")
    p = {"sentence": f"Level {lv}. The student must use the word '{g('word')}'. Their sentence: {g('sentence')}\n"
                     "Say if the word is used correctly. Give a corrected sentence and a one-line reason. Max 3 lines.",
         "grade": f"Grammar lesson: {g('title')}\nExercises and student answers:\n{g('qa')}\n"
                  "For each: tick or cross, the correct answer, a one-line reason. End with the score, like 3/5.",
         "test": f"Level {lv}. Student paragraph: {g('text')}\nWords/grammar they should use: {g('words')}\n"
                 "Give: score out of 10; corrected paragraph; top 3 mistakes in simple words; which target words were used well."}[task]
    return ask([{"role": "user", "content": p}], max_tokens=600)

def save_settings(d):
    c = load_cfg()
    for k in KEYS:
        if k in d and str(d[k]).strip(): c[k] = d[k]
    c["history_turns"], c["max_tokens"] = max(1, int(c["history_turns"])), max(50, int(c["max_tokens"]))
    json.dump(c, open(CFG_FILE, "w"), indent=2)
    if d.get("api_key", "").strip(): open(ENV_FILE, "w").write(d["api_key"].strip())

class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/settings": self.send(200, {**load_cfg(), "key_set": bool(get_key())})
        else: self.send(200, open(os.path.join(DIR, "index.html"), "rb").read(), "text/html; charset=utf-8")
    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if self.path == "/chat": self.send(200, {"reply": ask(d["messages"])})
            elif self.path == "/ai": self.send(200, {"result": run_task(d["task"], d)})
            elif self.path == "/settings": save_settings(d); self.send(200, {"ok": True})
            else: self.send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:  # shown to the user in the page
            self.send(400, {"error": str(e)})
    def log_message(self, *a): pass  # keep the console free of request details

if __name__ == "__main__":
    print("Open http://127.0.0.1:8000  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()  # localhost only
