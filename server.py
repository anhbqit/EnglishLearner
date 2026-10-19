"""English Learner web. Stdlib only. Run: python server.py -> http://127.0.0.1:8000
Provider "anthropic", or "openai" (any OpenAI-compatible: Gemini, Groq, OpenRouter)."""
import html, json, os, re, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
CFG_FILE, ENV_FILE, YT_FILE = (os.path.join(DIR, f) for f in ("config.json", ".env", ".ytkey"))
BOOKS = os.path.join(DIR, "books")  # extracted book text, git-ignored (copyright)
KEYS = ("provider", "model", "base_url", "history_turns", "max_tokens")
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
SYSTEM = ("You are a friendly English tutor for a first-year Business English student. "
          "Reply in English only, short and simple. If the student's message has mistakes, "
          "first give the corrected sentence, then explain each mistake in one simple line. "
          "If it is correct, say so, then reply naturally and ask one short follow-up question.")
JSON_SYS = "You write English-learning material for a Vietnamese Business English student. Reply with ONLY valid JSON, no markdown."
SCEN = {"interview": "an interviewer in a job interview for an office job", "meeting": "a colleague in a team meeting",
        "customer": "an unhappy customer calling support", "supplier": "a supplier negotiating price and delivery",
        "smalltalk": "a new coworker making small talk"}
EMAIL = ("You are a friendly Business English email coach. Reply in English only, short and simple. If the student says "
         "'Please start', give one short realistic work-email task (2-3 lines: who to write to and why). Otherwise the student "
         "wrote an email: show an improved version, then 3 short tips (tone, grammar, format).")
ROLE = ("You are {who} in a role-play with a Business English student. Stay in character. Reply in English only, in 1-3 short "
        "simple sentences, and end with one question. If the student says 'Please start', open the scene. After your reply, "
        "if the student's last message had mistakes, add a new line starting 'Tip:' with the corrected sentence and a one-line reason.")

def load_cfg(): return json.load(open(CFG_FILE))
def read_key(path, env): return open(path).read().strip() if os.path.exists(path) else os.environ.get(env, "")
def get_key(): return read_key(ENV_FILE, "LLM_API_KEY")
def get_ytkey(): return read_key(YT_FILE, "YT_API_KEY")

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

def parse_json(t, o, c):
    try: return json.loads(t[t.index(o):t.rindex(c) + 1])
    except ValueError: raise ValueError("The AI reply was not valid. Please try again.")

# ---- books: PDF text is extracted in the browser and stored here as a list of page strings
def book_path(name): return os.path.join(BOOKS, re.sub(r"[^\w .&-]", "_", name.strip())[:60] + ".json")

def list_books():
    os.makedirs(BOOKS, exist_ok=True)
    return {"books": [{"name": f[:-5], "pages": len(json.load(open(os.path.join(BOOKS, f), encoding="utf-8")))}
                      for f in sorted(os.listdir(BOOKS)) if f.endswith(".json")]}

def save_book(d):
    name, pages = str(d.get("name", "")).strip(), d.get("pages")
    if not name or not isinstance(pages, list) or not 0 < len(pages) < 3000 or not all(isinstance(p, str) for p in pages):
        raise ValueError("Bad book data.")
    os.makedirs(BOOKS, exist_ok=True)
    json.dump(pages, open(book_path(name), "w", encoding="utf-8"))
    return os.path.basename(book_path(name))[:-5]  # the stored (sanitized) name

def num(v, default):
    try: return int(v or default)
    except (TypeError, ValueError): raise ValueError("Bad page numbers.")

def source(d):
    """Prompt text about the student's book; includes a page excerpt when the book was uploaded."""
    name = str(d.get("book", "")).strip()[:80]
    if not name: return ""
    out = f"The student studies from the book '{name}'. Match its level and style. "
    p = book_path(name)
    if os.path.exists(p) and d.get("from"):
        pages, a = json.load(open(p, encoding="utf-8")), max(1, num(d.get("from"), 1))
        b = max(a, num(d.get("to"), a))
        out += f"Base this on the following text from the book (pages {a}-{b}):\n<<<\n{' '.join(pages[a - 1:b])[:3000]}\n>>>\n"
    return out

# ---- AI tasks
def run_task(task, d):
    lv = d.get("level", "A1")
    if lv not in LEVELS: raise ValueError("Bad level")
    g = lambda k: str(d.get(k, ""))[:2000]  # cap input size (cost + abuse)
    def js(p, n, o, c): return parse_json(ask([{"role": "user", "content": p}], JSON_SYS, n), o, c)
    if task == "vocab":
        return js(f"CEFR level {lv}. {source(d)}Topic: {g('topic') or 'chosen from the text, or useful work/study words'}. "
                  f"Teach 6 useful English words. Do not use: {g('avoid')}. Return JSON "
                  '{"title":"","intro":"1-2 simple sentences about the topic","words":[{"word":"","ipa":"/IPA/","pos":"noun/verb/...",'
                  '"vi":"short Vietnamese meaning","meaning":"simple English meaning","example":"one short sentence",'
                  '"note":"short tip: collocation or common mistake"}],"exercises":["4 fill-in-the-blank sentences using the words, '
                  'then 1 item asking the student to write a sentence with one given word"]}.', 1500, "{", "}")
    if task == "grammar":
        return js(f"CEFR level {lv}. {source(d)}Topic: {g('topic') or 'chosen from the text, or common for this level'}. "
                  "Teach ONE grammar point simply. Return JSON "
                  '{"title":"","what":"what it is, 1-2 simple sentences","use":["2-3 short points: when to use it"],'
                  '"structure":["1-3 patterns, like Subject + have/has + past participle"],"examples":["3 short example sentences"],'
                  '"watch":["2 common mistakes or tips"],"business":"one example sentence from a work situation",'
                  '"exercises":["5 short fill-in-the-blank or correct-the-sentence items"]}.', 1500, "{", "}")
    if task == "plan":
        return js(f"CEFR level {lv}. {source(d)}Plan today's English study for a Business English student. "
                  f"Recent topics to avoid: {g('avoid')}. Return JSON "
                  '{"vocab_topic":"2-4 words","grammar_topic":"2-4 words, one grammar point","practice":"one short role-play '
                  'or business email idea","writing":"one short paragraph prompt"}.', 300, "{", "}")
    p = {"sentence": f"Level {lv}. The student must use the word '{g('word')}'. Their sentence: {g('sentence')}\n"
                     "Say if the word is used correctly. Give a corrected sentence and a one-line reason. Max 3 lines.",
         "grade": f"Lesson: {g('title')}\nExercises and student answers:\n{g('qa')}\n"
                  "For each: tick or cross, the correct answer, a one-line reason (for a writing item, give a corrected version). "
                  "End with the score, like 3/5.",
         "test": f"Level {lv}. Student paragraph: {g('text')}\nVocabulary to use: {g('words')}\nGrammar to use: {g('grammar')}\n"
                 "Give: score out of 10; corrected paragraph; top 3 mistakes in simple words; which target words were used well."}[task]
    return ask([{"role": "user", "content": p}], max_tokens=600)

def chat(d):
    lv, mode = d.get("level", "A1"), d.get("mode", "chat")
    if lv not in LEVELS or mode not in ("chat", "email", "roleplay"): raise ValueError("Bad request")
    if mode == "roleplay" and d.get("scenario") not in SCEN: raise ValueError("Pick a scene first.")
    sysmsg = {"chat": SYSTEM, "email": EMAIL, "roleplay": ROLE.format(who=SCEN.get(d.get("scenario")))}[mode]
    return ask(d["messages"], f"{sysmsg} The student's level is {lv}.", 500 if mode == "email" else None)

def search(q):
    """YouTube Data API v3 (needs the student's own free API key). Embeddable videos only."""
    q, key = q.strip()[:100], get_ytkey()
    if not q: raise ValueError("Type something to search.")
    if not key: raise ValueError("Add your YouTube API key in Settings to search.")
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(
        {"part": "snippet", "type": "video", "videoEmbeddable": "true", "maxResults": 8, "q": q, "key": key})
    try: items = json.load(urllib.request.urlopen(url, timeout=20))["items"]
    except urllib.error.HTTPError as e: raise ValueError(f"YouTube error {e.code}. Check your YouTube API key or quota.")
    return [{"id": i["id"]["videoId"], "title": html.unescape(i["snippet"]["title"]), "channel": html.unescape(i["snippet"]["channelTitle"])}
            for i in items if re.fullmatch(r"[\w-]{11}", i["id"].get("videoId", ""))]

def save_settings(d):
    c = load_cfg()
    for k in KEYS:
        if k in d and str(d[k]).strip(): c[k] = d[k]
    c["history_turns"], c["max_tokens"] = max(1, int(c["history_turns"])), max(50, int(c["max_tokens"]))
    json.dump(c, open(CFG_FILE, "w"), indent=2)
    for field, path in (("api_key", ENV_FILE), ("yt_key", YT_FILE)):
        if str(d.get(field, "")).strip(): open(path, "w").write(d[field].strip())

POST = {"/chat": lambda d: {"reply": chat(d)}, "/ai": lambda d: {"result": run_task(d["task"], d)},
        "/settings": lambda d: save_settings(d) or {"ok": True}, "/book": lambda d: {"name": save_book(d)}}

class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def reply(self, fn):
        try: self.send(200, fn())
        except (ValueError, KeyError) as e:  # shown to the user in the page
            self.send(400, {"error": str(e)})
        except OSError:
            self.send(502, {"error": "Network problem. Check your internet."})
    def body(self):
        n = int(self.headers["content-length"])
        if n > 40_000_000: raise ValueError("File too big.")
        return json.loads(self.rfile.read(n))
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/settings": self.reply(lambda: {**load_cfg(), "key_set": bool(get_key()), "yt_set": bool(get_ytkey())})
        elif u.path == "/books": self.reply(list_books)
        elif u.path == "/search": self.reply(lambda: {"results": search(urllib.parse.parse_qs(u.query).get("q", [""])[0])})
        else: self.send(200, open(os.path.join(DIR, "index.html"), "rb").read(), "text/html; charset=utf-8")
    def do_POST(self):
        fn = POST.get(self.path)
        if fn: self.reply(lambda: fn(self.body()))
        else: self.send(404, {"error": "not found"})
    def log_message(self, *a): pass  # keep the console free of request details

if __name__ == "__main__":
    print("Open http://127.0.0.1:8000  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()  # localhost only
