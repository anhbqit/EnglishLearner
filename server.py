"""English Learner web. Stdlib only. Run: python server.py -> http://127.0.0.1:8000
Provider "anthropic", or "openai" (any OpenAI-compatible: Gemini, Groq, OpenRouter)."""
import base64, hmac, html, json, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
CFG_FILE, ENV_FILE, YT_FILE = (os.path.join(DIR, f) for f in ("config.json", ".env", ".ytkey"))
DATA = os.path.join(DIR, "data")  # one progress file per user, git-ignored
PROGRESS = ("cards", "log", "journal", "plan", "course", "lv", "plist", "gdone", "profile", "lessons", "missed", "testmark", "sessions", "_t")  # _t: when the browser last changed something
HOST, PORT = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 8000))
AUTH = os.environ.get("APP_PASSWORD", "")  # cloud: set it. The browser then asks for a login; the login name picks the progress file
LOCK = threading.Lock()
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

WORD_TYPES = "topic word, phrasal verb, prepositional phrase, word formation (a word made from another), word pattern (word + preposition)"

def ex_spec(n, write=True):
    """The exercise part of a JSON prompt: n typed items, at least 5 kinds."""
    return (f'"exercises":[{n} items, at least 5 different types' + (', the last one a "write" item' if write else '') + '. Check every answer key twice: each item must have exactly ONE correct answer, and match items must have clearly different meanings. Types: '
            '{"type":"choice","q":"sentence with ___","options":["a","b","c"],"answer":"b"} (2 options = circle the correct word; or True/False), '
            '{"type":"gap","q":"sentence with ___ and the base word in (brackets), or a CAPITAL word to change","answer":["answer","other accepted answer"]}, '
            '{"type":"order","answer":"the full correct sentence, 4-8 words"}, '
            '{"type":"match","pairs":[["item","its match"],["item","its match"],["item","its match"]]}, '
            '{"type":"error","q":"a sentence with one mistake","answer":["the corrected sentence"]}'
            + (', {"type":"write","q":"ask for one short sentence using something from the lesson"}' if write else '') + ']')

def clean_ex(x):
    """Validate one AI-made exercise (the AI output is untrusted); return a trimmed dict or None."""
    try:
        t, s = x["type"], lambda v: str(v)[:300]
        if t == "choice":
            o, a = [s(i) for i in x["options"]][:5], s(x["answer"])
            return {"type": t, "q": s(x["q"]), "options": o, "answer": a} if len(o) > 1 and a in o else None
        if t in ("gap", "error"):
            a = [s(i) for i in (x["answer"] if isinstance(x["answer"], list) else [x["answer"]])][:4]
            return {"type": t, "q": s(x["q"]), "answer": a} if a and all(a) else None
        if t == "order":
            return {"type": t, "answer": s(x["answer"])} if len(s(x["answer"]).split()) >= 3 else None
        if t == "match":
            p = [[s(i[0]), s(i[1])] for i in x["pairs"]][:5]
            return {"type": t, "pairs": p} if len(p) > 1 and len({i[1] for i in p}) == len(p) else None  # pairs must be unambiguous
        if t == "write": return {"type": t, "q": s(x["q"])}
    except (KeyError, TypeError, IndexError, AttributeError): pass
    return None

def clean_word(w):
    try: out = {k: str(w.get(k, ""))[:200] for k in ("word", "type", "ipa", "pos", "vi", "meaning", "example", "note")}
    except AttributeError: return None
    return out if out["word"].strip() and out["vi"].strip() else None

SKILLS = ("grammar", "vocab")
INCOMPLETE = "The AI reply was incomplete. Please try again."

def clean_lesson(r, need):
    ex = r.get("exercises")
    r["exercises"] = [e for e in map(clean_ex, ex if isinstance(ex, list) else []) if e]
    if not r["exercises"] or any(not r.get(k) for k in need): raise ValueError(INCOMPLETE)
    return r

def clean_exam(r):
    r = clean_lesson(r, ())
    ex, p = [e for e in r["exercises"] if e["type"] != "write"], r.get("paragraph")
    if len(ex) < 5 or not isinstance(p, dict) or not str(p.get("prompt", "")).strip(): raise ValueError(INCOMPLETE)
    use = p.get("use") if isinstance(p.get("use"), list) else []
    return {"title": str(r.get("title", ""))[:100], "exercises": ex, "paragraph": {"prompt": str(p["prompt"])[:300], "use": [str(w)[:40] for w in use][:8]}}

def clean_placement(r):
    out = []
    for x in r.get("items") if isinstance(r.get("items"), list) else []:
        e = clean_ex(x)
        if e and e["type"] in ("choice", "gap", "error") and x.get("level") in LEVELS and x.get("skill") in SKILLS:
            out.append({**e, "level": x["level"], "skill": x["skill"]})
    if len(out) < 6: raise ValueError(INCOMPLETE)
    return {"items": sorted(out, key=lambda e: LEVELS.index(e["level"]))}  # stable: keeps the AI's order inside a level

def clean_course(r):
    s = lambda v, n: str(v)[:n]
    lst = lambda k: [s(i, 100) for i in r[k]][:4] if isinstance(r.get(k), list) else []
    units = [{"practice": s(u["practice"], 150)} for u in (r.get("units") if isinstance(r.get("units"), list) else [])
             if isinstance(u, dict) and str(u.get("practice", "")).strip()]
    if len(units) < 3: raise ValueError(INCOMPLETE)
    return {"summary": s(r.get("summary", ""), 400), "strengths": lst("strengths"), "weak": lst("weak"), "units": units[:12]}

# ---- AI tasks
def run_task(task, d):
    lv = d.get("level", "A1")
    if lv not in LEVELS: raise ValueError("Bad level")
    g = lambda k: str(d.get(k, ""))[:2000]  # cap input size (cost + abuse)
    def js(p, n, o, c): return parse_json(ask([{"role": "user", "content": p}], JSON_SYS, n), o, c)
    if task == "vocab":
        try: n = max(3, min(12, int(d.get("count") or 8)))  # words in this lesson
        except (TypeError, ValueError): n = 8
        r = js(f"CEFR level {lv}. Topic: {g('topic') or 'useful work and study words'}. "
               f"Teach {n} useful English words for this topic, mixing these kinds: {WORD_TYPES}. Do not use: {g('avoid')}. Return JSON "
               '{"title":"","words":[{"word":"","type":"one of the kinds","ipa":"/IPA/","pos":"noun/verb/phrase",'
               '"vi":"short Vietnamese meaning","meaning":"simple English meaning","example":"one short sentence that contains the word exactly as written",'
               '"note":"short tip: collocation or common mistake"}],' + ex_spec(8) + "}.", 2200, "{", "}")
        r["words"] = [w for w in map(clean_word, r.get("words") if isinstance(r.get("words"), list) else []) if w]
        return clean_lesson(r, ("title", "words"))
    if task == "grammar":
        return clean_lesson(js(f"CEFR level {lv}. Topic: {g('topic') or 'common for this level'}. "
               "Teach ONE grammar point simply. Return JSON "
               '{"title":"","what":"what it is, 1-2 simple sentences","use":["2-3 short points: when to use it"],'
               '"structure":["1-3 patterns, like Subject + have/has + past participle"],"hints":["signal words or phrases that often go with it"],'
               '"examples":["3 short example sentences"],"watch":["2 common mistakes or tips"],"business":"one example sentence from a work situation",'
               + ex_spec(8) + "}.", 1800, "{", "}"), ("title",))
    if task == "exercises":
        if d.get("kind") not in SKILLS: raise ValueError("Bad request")
        what = f"the grammar point '{g('topic')}'" if d["kind"] == "grammar" else f"the topic '{g('topic')}' and these words: {g('words')}"
        r = js(f"CEFR level {lv}. Make 8 NEW exercises for a student studying {what}. "
               f"The student got these wrong before, so practise them again in new sentences: {g('missed')}. Return JSON {{" + ex_spec(8) + "}.", 1500, "{", "}")
        return {"exercises": clean_lesson(r, ())["exercises"]}
    if task == "exam":
        return clean_exam(js(f"CEFR level {lv}. Make a progress test for a Vietnamese Business English student. Test ONLY what they studied. "
               f"Vocabulary studied: {g('words')}. Grammar studied: {g('grammar')}. Mistakes they made before (test these again): {g('missed')}. Return JSON "
               '{"title":"",' + ex_spec(10, False) + ',"paragraph":{"prompt":"one short writing task that needs 4-6 sentences, about work or study",'
               '"use":["4-6 of the studied words"]}}.', 2400, "{", "}"))
    if task == "placement":
        return clean_placement(js("Make a placement test for a Vietnamese learner of English. 12 items: exactly 2 for each CEFR level A1, A2, B1, B2, C1, C2, "
            "in that order, each clearly at its level; mix grammar and vocabulary (work contexts are fine from B1). Return JSON "
            '{"items":[{"level":"A1","skill":"grammar or vocab","type":"choice","q":"sentence with ___","options":["a","b","c"],"answer":"b"},'
            '{"level":"B1","skill":"grammar","type":"gap","q":"sentence with ___ and the base word in (brackets)","answer":["x"]},'
            '{"level":"B2","skill":"vocab","type":"error","q":"sentence with one mistake","answer":["the corrected sentence"]}]} '
            "Use only these three types.", 1800, "{", "}"))
    if task == "course":
        return clean_course(js(f"A placement test says the student's level is {lv}. Scores: {g('scores')}. Missed items: {g('missed')}. "
            f"Writing sample (may be empty): {g('text')}\n"
            "Make a personal practice plan of 8 daily speaking/writing ideas for this student (role-plays and business emails). "
            "Start at their level, aim at their weak areas, end slightly harder. Return JSON "
            '{"summary":"2 simple sentences about the student, in English","strengths":["2 short items"],"weak":["2-3 short items"],'
            '"units":[{"practice":"one short role-play or email idea"}]}.', 1200, "{", "}"))
    p = {"sentence": f"Level {lv}. The student must use the word '{g('word')}'. Their sentence: {g('sentence')}\n"
                     "Say if the word is used correctly. Give a corrected sentence and a one-line reason. Max 3 lines.",
         "grade": f"Lesson: {g('title')}\nExercises and student answers:\n{g('qa')}\n"
                  "For each: tick or cross, the correct answer, a one-line reason (for a writing item, give a corrected version). "
                  "End with the score, like 3/5.",
         "verify": f"Level {lv}. Exercise: {g('q')}\nAnswer key: {g('key')}\nStudent answered: {g('yours')}\n"
                   "The answer key was made by an AI and may be wrong. Decide if the student's answer is correct English for this exercise. "
                   "Start your reply with RIGHT or WRONG, then one short simple reason (max 2 lines).",
         "test": f"Level {lv}. Student paragraph: {g('text')}\nVocabulary to use: {g('words')}\nGrammar studied: {g('grammar')}\n"
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

def progress_file(uid): return os.path.join(DATA, re.sub(r"\W", "_", uid)[:40] + ".json")

def load_progress(uid):
    try: return json.load(open(progress_file(uid), encoding="utf-8"))
    except (OSError, ValueError): return {}

def save_progress(uid, d):
    """shortcut: one JSON file per user, last write wins; move to a database (same two functions) when many users or devices."""
    data = d.get("data")
    if (not isinstance(data, dict) or not all(k in PROGRESS and isinstance(v, str) for k, v in data.items())
            or sum(map(len, data.values())) > 5_000_000): raise ValueError("Bad progress data.")
    with LOCK:
        os.makedirs(DATA, exist_ok=True)
        tmp = progress_file(uid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump({**load_progress(uid), **data}, f)
        os.replace(tmp, progress_file(uid))  # atomic: a crash never leaves a half-written file
    return {"ok": True}

POST = {"/chat": lambda d: {"reply": chat(d)}, "/ai": lambda d: {"result": run_task(d["task"], d)},
        "/settings": lambda d: save_settings(d) or {"ok": True}}

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
        if n > 6_000_000: raise ValueError("Request too big.")
        return json.loads(self.rfile.read(n))
    def user(self):
        """Who is asking: 'local' without a password; with APP_PASSWORD, the login name (None = not allowed)."""
        if not AUTH: return "local"
        try: u, _, p = base64.b64decode(self.headers.get("authorization", "")[6:]).decode().partition(":")
        except ValueError: return None
        return re.sub(r"\W", "_", u)[:40] if u and hmac.compare_digest(p.encode(), AUTH.encode()) else None
    def deny(self):
        self.send_response(401); self.send_header("www-authenticate", 'Basic realm="English Learner"')
        self.send_header("content-length", "0"); self.end_headers()
    def do_GET(self):
        uid = self.user()
        if not uid: return self.deny()
        u = urllib.parse.urlparse(self.path)
        if u.path == "/settings": self.reply(lambda: {**load_cfg(), "key_set": bool(get_key()), "yt_set": bool(get_ytkey())})
        elif u.path == "/search": self.reply(lambda: {"results": search(urllib.parse.parse_qs(u.query).get("q", [""])[0])})
        else:  # the saved progress is put into the page, so it is there before the page code runs ("<" escaped: no </script> tricks)
            page = open(os.path.join(DIR, "index.html"), encoding="utf-8").read()
            self.send(200, page.replace("__PROGRESS__", json.dumps(load_progress(uid)).replace("<", "\\u003c")).encode(), "text/html; charset=utf-8")
    def do_POST(self):
        uid = self.user()
        if not uid: return self.deny()
        if self.path == "/progress": return self.reply(lambda: save_progress(uid, self.body()))
        fn = POST.get(self.path)
        if fn: self.reply(lambda: fn(self.body()))
        else: self.send(404, {"error": "not found"})
    def log_message(self, *a): pass  # keep the console free of request details

def watch():
    """Dev convenience: exit with code 3 when server.py changes, so start.bat restarts it. index.html needs no restart."""
    f = os.path.join(DIR, "server.py"); t = os.path.getmtime(f)
    while True:
        time.sleep(1)
        if os.path.getmtime(f) != t: os._exit(3)

if __name__ == "__main__":
    if HOST not in ("127.0.0.1", "localhost") and not AUTH:
        raise SystemExit("Set APP_PASSWORD before exposing the app: anyone could change your API key and spend your money.")
    threading.Thread(target=watch, daemon=True).start()
    print(f"Open http://{HOST}:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
