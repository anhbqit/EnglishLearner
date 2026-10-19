import json, os, shutil, tempfile, threading, urllib.error, urllib.request
import server

tmp = tempfile.mkdtemp(dir=server.DIR)  # temp config/keys/books: never touches the real ones
server.CFG_FILE, server.ENV_FILE, server.YT_FILE, server.BOOKS = (os.path.join(tmp, f) for f in ("c.json", ".env", ".yt", "books"))
json.dump({"provider": "anthropic", "model": "m", "base_url": "u", "history_turns": 4, "max_tokens": 300}, open(server.CFG_FILE, "w"))
U = "http://127.0.0.1:8123"
s = server.ThreadingHTTPServer(("127.0.0.1", 8123), server.H); threading.Thread(target=s.serve_forever, daemon=True).start()
def post(p, b): return json.load(urllib.request.urlopen(urllib.request.Request(U + p, json.dumps(b).encode())))
def get(p): return json.load(urllib.request.urlopen(U + p))
def err(fn, text):
    try: fn(); raise SystemExit("expected error: " + text)
    except urllib.error.HTTPError as e: assert text.encode() in e.read(), text
    except ValueError as e: assert text in str(e), text

try:
    assert len(server.trim(list(range(20)), 4)) == 8
    err(lambda: post("/chat", {"messages": []}), "No API key")
    post("/settings", {"model": "x", "api_key": "secret", "yt_key": "ytsecret", "history_turns": "2"})
    r = get("/settings")
    assert r["model"] == "x" and r["history_turns"] == 2 and r["key_set"] and r["yt_set"] and "secret" not in json.dumps(r)
    assert b"English Learner" in urllib.request.urlopen(U + "/").read()

    # books: upload, list, excerpt in prompt, bad input
    assert post("/book", {"name": "My Book", "pages": ["page one text", "page two text", "page three text"]}) == {"name": "My Book"}
    assert get("/books")["books"] == [{"name": "My Book", "pages": 3}]
    src = server.source({"book": "My Book", "from": 2, "to": 3})
    assert "page two" in src and "page three" in src and "page one" not in src
    assert server.source({"book": "Destination B1"}).count("<<<") == 0 and server.source({}) == ""
    err(lambda: post("/book", {"name": "", "pages": ["x"]}), "Bad book")
    err(lambda: server.source({"book": "My Book", "from": "x"}), "Bad page")
    assert os.path.dirname(server.book_path("../../evil")) == server.BOOKS

    # AI tasks with a fake model (no network, no real text)
    seen = []
    fake = lambda reply: (lambda m, system=None, max_tokens=None: (seen.append(m[0]["content"]) or reply))
    server.ask = fake('```json\n{"title":"t","words":[]}\n```')
    assert server.run_task("vocab", {"level": "B1", "topic": "meetings", "book": "My Book", "from": 1, "to": 1})["title"] == "t"
    assert "meetings" in seen[-1] and "page one" in seen[-1]
    assert server.run_task("grammar", {"level": "A1"})["title"] == "t" and server.run_task("plan", {"level": "A1"})["title"] == "t"
    server.ask = fake("not json")
    err(lambda: server.run_task("grammar", {"level": "A1"}), "not valid")
    err(lambda: server.run_task("vocab", {"level": "Z9"}), "Bad level")
    server.ask = fake("fb")
    assert all(server.run_task(t, {"level": "C2"}) == "fb" for t in ("sentence", "grade", "test"))

    # chat modes
    got = {}
    server.ask = lambda m, system=None, max_tokens=None: (got.update(s=system, t=max_tokens) or "r")
    assert server.chat({"messages": [], "mode": "roleplay", "scenario": "meeting", "level": "B2"}) == "r" and "colleague" in got["s"]
    server.chat({"messages": [], "mode": "email"}); assert got["t"] == 500
    for bad in ({"mode": "x"}, {"mode": "roleplay"}, {"level": "Z"}):
        err(lambda: server.chat({"messages": [], **bad}), "")

    # YouTube search: parsing, entity decoding, id validation, missing key
    class R:  # fake HTTP response
        def read(self): return json.dumps({"items": [
            {"id": {"videoId": "abcdefghijk"}, "snippet": {"title": "Tom &amp; Jerry", "channelTitle": "C"}},
            {"id": {"videoId": "bad"}, "snippet": {"title": "x", "channelTitle": "y"}}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass
    real = urllib.request.urlopen; urllib.request.urlopen = lambda *a, **k: R()
    assert server.search("english") == [{"id": "abcdefghijk", "title": "Tom & Jerry", "channel": "C"}]
    urllib.request.urlopen = real
    os.remove(server.YT_FILE); err(lambda: get("/search?q=hi"), "YouTube API key")
    print("all ok")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
