"""English Learner web. Stdlib only. Run: python server.py -> http://127.0.0.1:8000
Provider "anthropic", or "openai" (any OpenAI-compatible: Gemini, Groq, OpenRouter)."""
import base64, hmac, html, json, os, re, shutil, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
CFG_FILE, ENV_FILE, YT_FILE = (os.path.join(DIR, f) for f in ("config.json", ".env", ".ytkey"))
DATA = os.path.join(DIR, "data")  # one progress file per user, git-ignored
PROGRESS = ("cards", "log", "journal", "plan", "course", "lv", "plist", "gdone", "profile", "lessons", "missed", "testmark", "sessions", "phrases", "habits", "story", "_t")  # _t: when the browser last changed something
HOST, PORT = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 8000))
AUTH = os.environ.get("APP_PASSWORD", "")  # cloud: one shared password; the login name picks the progress file
USERS = dict(x.strip().split(":", 1) for x in os.environ.get("APP_USERS", "").split(",") if ":" in x)  # cloud, better: "daisy:pass1,minh:pass2" = one password per person
ADMIN = os.environ.get("ADMIN_USER", "local")  # who may change Settings (API key, model, budget). Without a login everyone is "local"
AI_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", 500))  # AI requests per person per day: a guard against runaway costs
LOCK = threading.Lock()
KEYS = ("provider", "model", "base_url", "history_turns", "max_tokens")
NUM_KEYS = ("budget", "price_in", "price_out")  # budget in $ per month; prices in $ per million tokens (you can change them: providers change prices)
DEFAULTS = {"budget": 5.0, "price_in": 1.0, "price_out": 5.0}
USAGE_FILE = os.path.join(DIR, "usage.json")  # token counts per month, git-ignored
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
SYSTEM = ("You are a friendly English tutor for a Vietnamese learner of English. "
          "Reply in English only, short and simple. If the student's message has mistakes, "
          "first give the corrected sentence, then explain each mistake in one simple line. "
          "If it is correct, say so, then reply naturally and ask one short follow-up question.")
JSON_SYS = "You write English-learning material for a Vietnamese learner of English. Reply with ONLY valid JSON, no markdown."
FOCUS = {"general": "everyday life", "work": "work and business", "study": "university study and exams", "travel": "travel and daily life abroad"}
SCEN = {"interview": "an interviewer in a job interview for an office job", "meeting": "a colleague in a team meeting",
        "customer": "an unhappy customer calling support", "supplier": "a supplier negotiating price and delivery",
        "smalltalk": "a new coworker making small talk", "friend": "a new friend chatting at a cafe", "shop": "a shop assistant helping a customer",
        "hotel": "a hotel receptionist at check-in", "doctor": "a doctor talking to a patient", "lecturer": "a university lecturer in office hours"}
EMAIL = ("You are a friendly English email coach. Reply in English only, short and simple. If the student says "
         "'Please start', give one short realistic email task that fits the student's interests (2-3 lines: who to write to and why). Otherwise the student "
         "wrote an email: show an improved version, then 3 short tips (tone, grammar, format).")
ROLE = ("You are {who} in a role-play with a learner of English. Stay in character. Reply in English only, in 1-3 short "
        "simple sentences, and end with one question. If the student says 'Please start', open the scene. After your reply, "
        "if the student's last message had mistakes, add a new line starting 'Tip:' with the corrected sentence and a one-line reason.")

def load_cfg(): return json.load(open(CFG_FILE))
def read_key(path, env): return open(path).read().strip() if os.path.exists(path) else os.environ.get(env, "")
def get_key(): return read_key(ENV_FILE, "LLM_API_KEY")
def get_ytkey(): return read_key(YT_FILE, "YT_API_KEY")

def trim(history, turns):
    h = history[-2 * turns:]  # one turn = user + assistant
    while h and h[0].get("role") != "user": h = h[1:]  # the provider needs the user's message first
    return h

def focus_text(d):
    f = [FOCUS[x] for x in (d.get("focus") if isinstance(d.get("focus"), list) else []) if isinstance(x, str) and x in FOCUS]
    return ", ".join(dict.fromkeys(f)) or FOCUS["general"]

_calls = {}
def count_call(uid):
    day = time.strftime("%Y-%m-%d")
    with LOCK:
        for old in [k for k in _calls if k[1] != day]: del _calls[old]
        _calls[uid, day] = _calls.get((uid, day), 0) + 1
        if _calls[uid, day] > AI_LIMIT: raise ValueError("Daily AI limit reached. Please try again tomorrow.")

def month(): return time.strftime("%Y-%m")

def load_usage():
    try: return json.load(open(USAGE_FILE, encoding="utf-8"))
    except (OSError, ValueError): return {}

def record_usage(tin, tout):
    """Count the tokens the provider says it used, per month (the cost meter reads this)."""
    try: tin, tout = int(tin or 0), int(tout or 0)
    except (TypeError, ValueError): return
    try:
        with LOCK:
            u = load_usage(); m = u.setdefault(month(), {"in": 0, "out": 0, "calls": 0})
            m["in"] += tin; m["out"] += tout; m["calls"] += 1
            with open(USAGE_FILE + ".tmp", "w", encoding="utf-8") as f: json.dump(u, f)
            os.replace(USAGE_FILE + ".tmp", USAGE_FILE)
    except OSError: pass  # the meter must never break a lesson

def usage_summary():
    c = {**DEFAULTS, **load_cfg()}; m = load_usage().get(month(), {"in": 0, "out": 0, "calls": 0})
    cost = m["in"] / 1e6 * float(c["price_in"]) + m["out"] / 1e6 * float(c["price_out"]); budget = float(c["budget"])
    return {**m, "month": month(), "cost": round(cost, 4), "budget": budget, "pct": round(100 * cost / budget) if budget > 0 else 0}

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
        r = json.load(urllib.request.urlopen(urllib.request.Request(c["base_url"], json.dumps(body).encode(), hdr), timeout=120))
    except urllib.error.HTTPError as e:
        raise ValueError(f"API error {e.code}: {e.read().decode()[:200]}")
    u = r.get("usage") or {}
    record_usage(u.get("input_tokens", u.get("prompt_tokens")), u.get("output_tokens", u.get("completion_tokens")))
    return r["content"][0]["text"] if anth else r["choices"][0]["message"]["content"]

def parse_json(t, o, c):
    try: return json.loads(t[t.index(o):t.rindex(c) + 1])
    except ValueError: raise ValueError("The AI reply was not valid. Please try again.")

GROUPS = ("topic word", "phrasal verb", "prepositional phrase", "word formation", "word pattern")
GROUP_HELP = ("topic words (useful nouns, verbs, adjectives for the topic); phrasal verbs; prepositional phrases (like 'in charge of'); "
              "word formation (a derived word, such as a noun made from a verb; say the base word in the meaning); "
              "word patterns (a word + the preposition or form that follows it, like 'depend on')")

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
    t = out["type"].lower()  # the AI may write "phrasal verbs" or something odd: map it to one of the five groups
    out["type"] = next((g for g in GROUPS if g in t or g.rstrip("s") in t), None) or next(
        (g for g, key in zip(GROUPS, ("topic", "phrasal", "prepos", "formation", "pattern")) if key in t), "topic word")
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

def clean_reading(r):
    text = str(r.get("text", "")).strip()
    ex = [e for e in map(clean_ex, r.get("exercises") if isinstance(r.get("exercises"), list) else []) if e and e["type"] in ("choice", "write")]
    if not 200 <= len(text) <= 3500 or sum(e["type"] == "choice" for e in ex) < 3: raise ValueError(INCOMPLETE)
    return {"title": str(r.get("title", ""))[:100], "text": text, "exercises": ex}

def clean_define(r):
    out = {k: str(r.get(k, ""))[:200] for k in ("word", "ipa", "pos", "vi", "meaning", "example", "note")} if isinstance(r, dict) else {}
    if not out.get("word", "").strip() or not out.get("vi", "").strip(): raise ValueError(INCOMPLETE)
    out["type"] = "topic word"
    return out

def clean_phrases(r):
    items = [{"phrase": str(i["phrase"]).strip()[:200], "use": str(i.get("use", ""))[:80]} for i in (r.get("items") if isinstance(r.get("items"), list) else [])
             if isinstance(i, dict) and len(str(i.get("phrase", "")).strip()) >= 5]
    if len(items) < 3: raise ValueError(INCOMPLETE)
    return {"items": items[:10]}

def clean_mock(r):
    ex = [e for e in map(clean_ex, r.get("exercises") if isinstance(r.get("exercises"), list) else []) if e and e["type"] in ("choice", "gap", "error")]
    if len(ex) < 10: raise ValueError(INCOMPLETE)
    return {"exercises": ex[:20]}

def clean_tone(r):
    out = {k: str(r.get(k, "")).strip()[:400] for k in ("casual", "neutral", "formal", "tip")}
    if not all(out[k] for k in ("casual", "neutral", "formal")): raise ValueError(INCOMPLETE)
    return out

def clean_story(r):
    s = lambda v, n: str(v or "")[:n]
    text = s(r.get("text"), 1500).strip()
    if len(text) < 20 or not s(r.get("from"), 80).strip(): raise ValueError(INCOMPLETE)
    ms = [{"wrong": s(m.get("wrong"), 200), "right": s(m.get("right"), 200), "why": s(m.get("why"), 150)} for m in (r.get("mistakes") if isinstance(r.get("mistakes"), list) else [])
          if isinstance(m, dict) and str(m.get("wrong", "")).strip() and str(m.get("right", "")).strip()][:8]
    kind = s(r.get("kind"), 30).lower()
    return {"text": text, "from": s(r.get("from"), 80), "kind": next((k for k in ("email", "conversation") if k in kind), "message"),
            "summary": s(r.get("summary"), 800), "mistakes": ms, "praise": s(r.get("praise"), 300)}

HABITS = ("plural -s", "articles (a, an, the)", "verb tense", "subject-verb agreement", "prepositions", "word order",
          "word form (noun, verb, adjective)", "spelling", "missing words", "word choice")

def clean_habits(r):
    hs = []
    for h in r.get("habits") if isinstance(r.get("habits"), list) else []:
        if not isinstance(h, dict) or h.get("name") not in HABITS: continue
        try: n = max(1, min(99, int(h.get("count") or 1)))
        except (TypeError, ValueError): n = 1
        hs.append({"name": h["name"], "count": n, "example": str(h.get("example", ""))[:300], "tip": str(h.get("tip", ""))[:300]})
    ex = [e for e in map(clean_ex, r.get("exercises") if isinstance(r.get("exercises"), list) else []) if e and e["type"] in ("choice", "gap", "error")]
    if not hs or len(ex) < 3: raise ValueError(INCOMPLETE)
    return {"habits": hs[:3], "exercises": ex[:8]}

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

# ---- shared dictionary: every meaning the AI writes is kept on the server, so the next lookup of that word needs no AI call.
# Only dictionary facts are stored (word, IPA, meanings, example): nothing about the user.
DICT_MAX = 20000
DICT_FIELDS = ("word", "ipa", "pos", "vi", "meaning", "example", "note")
_dict = {"path": None, "words": {}}

def dict_file(): return os.path.join(DATA, "shared-dictionary.json")  # a "-" can never come from progress_file(), so no user can overwrite it

def dict_key(w):
    w = re.sub(r"\s+", " ", str(w).lower().replace("\u2019", "'")).strip(" .,;:!?\"()")
    return w[3:] if w.startswith("to ") else w

def dict_words():
    if _dict["path"] != dict_file():  # loaded once, then kept in memory
        try: words = json.load(open(dict_file(), encoding="utf-8"))
        except (OSError, ValueError): words = {}
        _dict.update(path=dict_file(), words=words if isinstance(words, dict) else {})
    return _dict["words"]

def dict_get(w):
    e = dict_words().get(dict_key(w))
    return {k: e.get(k, "") for k in DICT_FIELDS} if isinstance(e, dict) else None

def dict_put(entries, also=()):
    """Save word entries; `also` = extra spellings that point to the first entry (e.g. "meetings" -> "meeting")."""
    try:
        with LOCK:
            words, now = dict_words(), time.time()
            for i, e in enumerate(entries):
                if not isinstance(e, dict) or not str(e.get("word", "")).strip() or not str(e.get("vi", "")).strip(): continue
                item = {**{k: str(e.get(k, ""))[:200] for k in DICT_FIELDS}, "t": now}
                for k in {dict_key(e["word"]), *(map(dict_key, also) if i == 0 else ())}:
                    if 0 < len(k) <= 60: words[k] = item
            if len(words) > DICT_MAX:  # drop the oldest
                for k in sorted(words, key=lambda k: words[k].get("t", 0))[:len(words) - DICT_MAX]: del words[k]
            os.makedirs(DATA, exist_ok=True)
            # shortcut: rewrites the whole file on each new word (fine up to ~20k words); use a database when this is on the cloud with many users
            with open(dict_file() + ".tmp", "w", encoding="utf-8") as f: json.dump(words, f, ensure_ascii=False)
            os.replace(dict_file() + ".tmp", dict_file())
    except OSError: pass  # the dictionary is a speed-up: a failed save must never break a lesson

# ---- AI tasks
def run_task(task, d):
    lv = d.get("level", "A1")
    if lv not in LEVELS: raise ValueError("Bad level")
    g = lambda k: str(d.get(k, ""))[:2000]  # cap input size (cost + abuse)
    sysj = f"{JSON_SYS} The student's interests: {focus_text(d)}. Use them for examples and situations where it fits."
    def js(p, n, o, c): return parse_json(ask([{"role": "user", "content": p}], sysj, n), o, c)
    if task == "vocab":
        try: per = max(2, min(8, int(d.get("per") or 6)))  # words in each of the 5 groups
        except (TypeError, ValueError): per = 6
        r = js(f"CEFR level {lv}. Topic: {g('topic') or 'useful work and study words'}. "
               f"Teach {5 * per} useful English words for this topic in 5 groups of exactly {per} words each, in this order: {GROUP_HELP}. "
               f"Do not use any of these words (the student knows them already): {str(d.get('avoid', ''))[:8000]}. Return JSON "
               '{"title":"","words":[{"word":"","type":"exactly one of: topic word, phrasal verb, prepositional phrase, word formation, word pattern","ipa":"/IPA/","pos":"noun/verb/phrase",'
               '"vi":"short Vietnamese meaning","meaning":"simple English meaning","example":"one short sentence that contains the word exactly as written",'
               '"note":"short tip: collocation or common mistake"}],' + ex_spec(10) + "}.", 4000, "{", "}")
        r["words"] = [w for w in map(clean_word, r.get("words") if isinstance(r.get("words"), list) else []) if w]
        r = clean_lesson(r, ("title", "words"))
        dict_put(r["words"])
        return r
    if task == "grammar":
        return clean_lesson(js(f"CEFR level {lv}. Topic: {g('topic') or 'common for this level'}. "
               "Teach ONE grammar point simply. Return JSON "
               '{"title":"","what":"what it is, 1-2 simple sentences","use":["2-3 short points: when to use it"],'
               '"structure":["1-3 patterns, like Subject + have/has + past participle"],"hints":["signal words or phrases that often go with it"],'
               '"examples":["3 short example sentences"],"watch":["2 common mistakes or tips"],"business":"one example sentence from a real-life situation that fits the student interests",'
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
    if task == "reading":
        return clean_reading(js(f"CEFR level {lv}. Write a short text for a Vietnamese learner of English about: {g('topic') or 'something that matches their interests'}. "
               "It must be 140-200 words, at this level, in a realistic form that fits the topic (an email, a news article, a blog post, a short story, a dialogue or a report). "
               f"If it fits naturally, use some of these words the student has learned: {g('words')}. Return JSON "
               '{"title":"","text":"the text; separate paragraphs with a blank line","exercises":[5 comprehension questions of type '
               '{"type":"choice","q":"a question about the text","options":["a","b","c"],"answer":"b"} (each has exactly ONE correct answer; check twice), '
               'then 1 item {"type":"write","q":"Summarise the text in one sentence."}]}.', 1800, "{", "}"))
    if task == "define":
        word = g("word")[:40]
        if not word.strip(): raise ValueError("Bad request")
        hit = None if d.get("fresh") else dict_get(word)  # fresh = "ask the AI for this sentence" (a word can mean different things)
        if hit: return {**hit, "type": "topic word", "cached": True}
        r = clean_define(js(f"CEFR level {lv}. Explain the English word '{g('word')[:40]}' as it is used in this sentence: {g('sentence')[:300]}. Return JSON "
               '{"word":"the base form of the word","ipa":"/IPA/","pos":"noun/verb/adjective/...","vi":"short Vietnamese meaning in this context",'
               '"meaning":"simple English meaning","example":"a new short example sentence with the word","note":"short tip: collocation or common mistake"}.', 400, "{", "}"))
        dict_put([r], also=[word])
        return r
    if task == "phrases":
        return clean_phrases(js(f"CEFR level {lv}. Give 8 useful English phrases for this situation: {g('situation')[:100]}. "
               "Natural and polite, each short enough to say or write (use [name] or [date] only where needed). Return JSON "
               '{"items":[{"phrase":"","use":"when to use it, 8 words at most"}]}.', 900, "{", "}"))
    if task == "mock":
        return clean_mock(js(f"CEFR level {lv}. Make a timed Use of English style mock test of 15 items for a Vietnamese learner of English. "
               "Every item must have exactly ONE correct answer (check twice). Use: 5 items of type choice (a sentence with ___ and 3 or 4 options, including word patterns and phrasal verbs), "
               "4 items of type gap for word formation (a sentence with ___ and a CAPITAL base word in (brackets); the answer is the derived word), "
               "3 items of type gap testing a preposition or word pattern (the answer is the missing word; add a second accepted answer if one exists), "
               "2 items of type error (a sentence with one mistake; the answer is the corrected sentence) and 1 more choice item on a collocation. Return JSON "
               '{"exercises":[{"type":"choice","q":"sentence with ___","options":["a","b","c"],"answer":"b"},{"type":"gap","q":"sentence with ___ (BASE)","answer":["x"]},'
               '{"type":"error","q":"a sentence with one mistake","answer":["the corrected sentence"]}]}.', 3200, "{", "}"))
    if task == "tone":
        if not g("text").strip(): raise ValueError("Write a sentence first.")
        return clean_tone(js(f"CEFR level {lv}. Rewrite this sentence in three tones and keep the meaning. Fix any mistakes. Sentence: {g('text')[:300]}. Return JSON "
               '{"casual":"to a friend","neutral":"polite everyday English","formal":"for a teacher, a manager or an official email","tip":"one short line: what changes between the tones"}.', 500, "{", "}"))
    if task == "translate":
        items = [str(x)[:300] for x in d["items"]][:10] if isinstance(d.get("items"), list) else []
        if not items: raise ValueError("Bad request")
        r = js('Translate each English sentence into natural Vietnamese. Return JSON {"vi":[one Vietnamese sentence for each, in the same order]}. Sentences: '
               + json.dumps(items, ensure_ascii=False), 1500, "{", "}")
        vi = r.get("vi") if isinstance(r.get("vi"), list) else []
        if len(vi) != len(items) or not all(str(v).strip() for v in vi): raise ValueError(INCOMPLETE)
        return {"vi": [str(v)[:400] for v in vi]}
    if task == "story":
        return clean_story(js(f"CEFR level {lv}. You run a never-ending interactive story so a Vietnamese learner can practise English. The world: {g('world')[:150] or 'everyday life'}.\n"
               f"Story so far: {g('summary')[:800] or '(new story: make the student the main character and start the first scene)'}\n"
               f"Last message to the student: {g('last')[:1500] or '(none)'}\nThe student's reply: {g('reply')[:1500] or '(none yet)'}\n"
               "If there is a reply, list its grammar and word mistakes, then continue the story so that it reacts to what the student wrote. "
               "Write the next message from a character (a text message, an email or a spoken line), 40-120 words, at the student's level, ending with something the student must answer. Return JSON "
               '{"mistakes":[{"wrong":"the wrong words from the reply","right":"the correction","why":"one short reason"}],"praise":"one short line about what was good (empty if there is no reply)",'
               '"from":"character name and role","kind":"message, email or conversation","text":"the next message","summary":"the whole story so far in at most 80 words"}.', 1200, "{", "}"))
    if task == "habits":
        if not g("items").strip(): raise ValueError("Make some mistakes first, then come back.")
        return clean_habits(js(f"CEFR level {lv}. These are a Vietnamese learner's recent English mistakes (exercise -> what they wrote -> correct answer):\n{g('items')[:4000]}\n"
               f"Group them into habits using ONLY these names: {'; '.join(HABITS)}. Give the 3 most frequent habits (fewer if there are not enough mistakes), "
               "with how many of the mistakes show it, one real example from the list and one simple tip (explain why Vietnamese speakers often make it, e.g. Vietnamese has no plural endings, articles or verb endings). "
               "Then make 6 short exercises that practise those habits. Return JSON "
               '{"habits":[{"name":"","count":2,"example":"you wrote X, correct: Y","tip":""}],"exercises":[6 items of these types: '
               '{"type":"choice","q":"sentence with ___","options":["a","b","c"],"answer":"b"},{"type":"gap","q":"sentence with ___","answer":["x"]},'
               '{"type":"error","q":"a sentence with one mistake","answer":["the corrected sentence"]}]}.', 1600, "{", "}"))
    if task == "placement":
        return clean_placement(js("Make a placement test for a Vietnamese learner of English. 12 items: exactly 2 for each CEFR level A1, A2, B1, B2, C1, C2, "
            "in that order, each clearly at its level; mix grammar and vocabulary (everyday, study and work contexts). Return JSON "
            '{"items":[{"level":"A1","skill":"grammar or vocab","type":"choice","q":"sentence with ___","options":["a","b","c"],"answer":"b"},'
            '{"level":"B1","skill":"grammar","type":"gap","q":"sentence with ___ and the base word in (brackets)","answer":["x"]},'
            '{"level":"B2","skill":"vocab","type":"error","q":"sentence with one mistake","answer":["the corrected sentence"]}]} '
            "Use only these three types.", 1800, "{", "}"))
    if task == "course":
        return clean_course(js(f"A placement test says the student's level is {lv}. Scores: {g('scores')}. Missed items: {g('missed')}. "
            f"Writing sample (may be empty): {g('text')}\n"
            f"Make a personal practice plan of 8 daily speaking/writing ideas for this student (role-plays, emails and conversations about: {focus_text(d)}). "
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
    msgs = d.get("messages")
    if not isinstance(msgs, list) or not msgs or not all(isinstance(m, dict) and m.get("role") in ("user", "assistant")
                                                         and isinstance(m.get("content"), str) and len(m["content"]) <= 4000 for m in msgs):
        raise ValueError("Bad request")
    sysmsg = {"chat": SYSTEM, "email": EMAIL, "roleplay": ROLE.format(who=SCEN.get(d.get("scenario")))}[mode]
    return ask([{"role": m["role"], "content": m["content"]} for m in msgs[-40:]],
               f"{sysmsg} The student's level is {lv}. Their interests: {focus_text(d)}.", 500 if mode == "email" else None)

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
    for k in NUM_KEYS:
        if str(d.get(k, "")).strip():
            try: v = float(d[k])
            except ValueError: raise ValueError("Budget and prices must be numbers.")
            if not 0 <= v <= 100000: raise ValueError("Budget and prices must be between 0 and 100000.")
            c[k] = v
    c["history_turns"], c["max_tokens"] = max(1, int(c["history_turns"])), max(50, int(c["max_tokens"]))
    json.dump(c, open(CFG_FILE, "w"), indent=2)
    for field, path in (("api_key", ENV_FILE), ("yt_key", YT_FILE)):
        if str(d.get(field, "")).strip(): open(path, "w").write(d[field].strip())

def progress_file(uid): return os.path.join(DATA, re.sub(r"\W", "_", uid)[:40] + ".json")

def load_progress(uid):
    try: return json.load(open(progress_file(uid), encoding="utf-8"))
    except (OSError, ValueError): return {}

def backup_progress(uid):
    """Once a day, keep a copy of the saved progress (the last 7 days), so one bad save can be undone."""
    f = progress_file(uid)
    if not os.path.exists(f): return
    b = f[:-5] + time.strftime(".%Y-%m-%d.bak")
    if not os.path.exists(b): shutil.copy2(f, b)
    mine = os.path.basename(f)[:-5] + "."
    for old in sorted(x for x in os.listdir(DATA) if x.startswith(mine) and x.endswith(".bak"))[:-7]: os.remove(os.path.join(DATA, old))

def save_progress(uid, d):
    """shortcut: one JSON file per user, last write wins; move to a database (same two functions) when many users or devices."""
    data = d.get("data")
    if (not isinstance(data, dict) or not all(k in PROGRESS and isinstance(v, str) for k, v in data.items())
            or sum(map(len, data.values())) > 5_000_000): raise ValueError("Bad progress data.")
    with LOCK:
        os.makedirs(DATA, exist_ok=True)
        backup_progress(uid)
        tmp = progress_file(uid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump({**load_progress(uid), **data}, f)
        os.replace(tmp, progress_file(uid))  # atomic: a crash never leaves a half-written file
    return {"ok": True}

POST = {"/chat": lambda d: {"reply": chat(d)}, "/ai": lambda d: {"result": run_task(d["task"], d)},
        "/settings": lambda d: save_settings(d) or {"ok": True}}

class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", ctype); self.send_header("x-content-type-options", "nosniff")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def reply(self, fn):
        try: self.send(200, fn())
        except (ValueError, KeyError) as e:  # shown to the user in the page
            self.send(400, {"error": str(e)})
        except (TypeError, AttributeError):  # a request with the wrong shape (e.g. a list instead of an object)
            self.send(400, {"error": "Bad request."})
        except OSError:
            self.send(502, {"error": "Network problem. Check your internet."})
        except Exception as e:  # never leave the page waiting; details stay out of the reply
            print("server error:", type(e).__name__)
            self.send(500, {"error": "Server error. Please try again."})
    def body(self):
        n = int(self.headers.get("content-length") or 0)
        if not 0 < n <= 6_000_000: raise ValueError("Request too big." if n else "Bad request.")
        return json.loads(self.rfile.read(n))
    def user(self):
        """Who is asking: 'local' without a password; with APP_PASSWORD, the login name (None = not allowed)."""
        if not AUTH and not USERS: return "local"
        try: u, _, p = base64.b64decode(self.headers.get("authorization", "")[6:]).decode().partition(":")
        except ValueError: return None
        want = USERS.get(u, "") if USERS else AUTH
        return re.sub(r"\W", "_", u)[:40] if u and want and hmac.compare_digest(p.encode(), want.encode()) else None
    def deny(self):
        self.send_response(401); self.send_header("www-authenticate", 'Basic realm="English Learner"')
        self.send_header("content-length", "0"); self.end_headers()
    def do_GET(self):
        uid = self.user()
        if not uid: return self.deny()
        u = urllib.parse.urlparse(self.path)
        if u.path == "/settings": self.reply(lambda: {**DEFAULTS, **load_cfg(), "key_set": bool(get_key()), "yt_set": bool(get_ytkey())})
        elif u.path == "/usage": self.reply(usage_summary)
        elif u.path == "/search": self.reply(lambda: {"results": search(urllib.parse.parse_qs(u.query).get("q", [""])[0])})
        else:  # the saved progress is put into the page, so it is there before the page code runs ("<" escaped: no </script> tricks)
            page = open(os.path.join(DIR, "index.html"), encoding="utf-8").read()
            self.send(200, page.replace("__PROGRESS__", json.dumps(load_progress(uid)).replace("<", "\\u003c")).encode(), "text/html; charset=utf-8")
    def do_POST(self):
        uid = self.user()
        if not uid: return self.deny()
        if self.path == "/progress": return self.reply(lambda: save_progress(uid, self.body()))
        fn = POST.get(self.path)
        if not fn: return self.send(404, {"error": "not found"})
        if self.path == "/settings":
            if uid != ADMIN: return self.send(403, {"error": "Only the admin can change Settings."})
            return self.reply(lambda: fn(self.body()))
        self.reply(lambda: count_call(uid) or fn(self.body()))  # count_call returns None, or raises when the daily limit is reached
    def log_message(self, *a): pass  # keep the console free of request details

def watch():
    """Dev convenience: exit with code 3 when server.py changes, so start.bat restarts it. index.html needs no restart."""
    f = os.path.join(DIR, "server.py"); t = os.path.getmtime(f)
    while True:
        time.sleep(1)
        if os.path.getmtime(f) != t: os._exit(3)

if __name__ == "__main__":
    local = HOST in ("127.0.0.1", "localhost")
    if not local and not (AUTH or USERS):
        raise SystemExit("Set APP_USERS (or APP_PASSWORD) before exposing the app: anyone could use your API key and spend your money.")
    if local: threading.Thread(target=watch, daemon=True).start()  # auto-restart on code changes: only on your own computer
    print(f"Open http://{HOST}:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
