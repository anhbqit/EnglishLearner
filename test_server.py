import base64, json, os, shutil, tempfile, threading, urllib.error, urllib.request
import server

tmp = tempfile.mkdtemp(dir=server.DIR)  # temp config/keys/data: never touches the real ones
server.CFG_FILE, server.ENV_FILE, server.YT_FILE, server.DATA = (os.path.join(tmp, f) for f in ("c.json", ".env", ".yt", "data"))
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

    # AI tasks with a fake model (no network, no real text)
    seen = []
    fake = lambda reply: (lambda m, system=None, max_tokens=None: (seen.append(m[0]["content"]) or reply))
    ex = [{"type": "choice", "q": "q", "options": ["a", "b"], "answer": "b"}, {"type": "choice", "q": "q", "options": ["a", "b"], "answer": "z"},
          {"type": "gap", "q": "q ___", "answer": "x"}, {"type": "order", "answer": "she walks to work"}, {"type": "order", "answer": "too short"},
          {"type": "match", "pairs": [["a", "1"], ["b", "2"]]}, {"type": "match", "pairs": [["a", "1"], ["b", "1"]]},
          {"type": "error", "q": "q", "answer": ["x", "y"]}, {"type": "write", "q": "q"}, {"type": "nope"}, "junk"]
    word = {"word": "agenda", "ipa": "/a/", "vi": "v", "meaning": "m", "example": "e", "note": "n", "type": "topic word", "pos": "noun"}
    server.ask = fake("```json\n" + json.dumps({"title": "t", "words": [word, {"word": "x"}, "junk"], "exercises": ex}) + "\n```")
    r = server.run_task("vocab", {"level": "B1", "topic": "Meetings", "avoid": "old word"})
    assert r["title"] == "t" and len(r["words"]) == 1 and r["words"][0]["word"] == "agenda"
    assert [e["type"] for e in r["exercises"]] == ["choice", "gap", "order", "match", "error", "write"] and r["exercises"][1]["answer"] == ["x"]
    assert "Meetings" in seen[-1] and "old word" in seen[-1] and "8 items" in seen[-1] and "exactly ONE correct answer" in seen[-1]
    for cnt, want in ((5, 5), ("x", 8), (99, 12), (None, 8)):
        server.run_task("vocab", {"level": "B1", "topic": "x", "count": cnt}); assert f"Teach {want} useful" in seen[-1], cnt
    assert len(server.run_task("grammar", {"level": "A1", "topic": "Past perfect"})["exercises"]) == 6 and "Past perfect" in seen[-1]
    server.ask = fake(json.dumps({"title": "t", "words": [word], "exercises": [{"type": "nope"}]}))
    err(lambda: server.run_task("vocab", {"level": "A1"}), "incomplete")

    # new exercises for one topic: kind is validated, earlier mistakes go into the prompt
    server.ask = fake(json.dumps({"exercises": ex}))
    r = server.run_task("exercises", {"level": "B1", "kind": "vocab", "topic": "Meetings", "words": "agenda, minutes", "missed": "q1 -> a1"})
    assert len(r["exercises"]) == 6 and "agenda, minutes" in seen[-1] and "q1 -> a1" in seen[-1]
    server.run_task("exercises", {"level": "B1", "kind": "grammar", "topic": "Past perfect"}); assert "grammar point 'Past perfect'" in seen[-1]
    err(lambda: server.run_task("exercises", {"level": "B1", "kind": "x"}), "Bad request")
    server.ask = fake(json.dumps({"exercises": [{"type": "nope"}]}))
    err(lambda: server.run_task("exercises", {"level": "B1", "kind": "grammar"}), "incomplete")

    # progress test made from the learner's data: only closed question types, a paragraph task, at least 5 questions
    exam = {"title": "T", "exercises": ex, "paragraph": {"prompt": "Write about your week.", "use": ["agenda", "minutes"]}}
    server.ask = fake(json.dumps(exam))
    r = server.run_task("exam", {"level": "B1", "words": "agenda, minutes", "grammar": "Past perfect", "missed": "q1 -> a1"})
    assert [e["type"] for e in r["exercises"]] == ["choice", "gap", "order", "match", "error"] and r["paragraph"]["use"] == ["agenda", "minutes"]
    assert "agenda, minutes" in seen[-1] and "Past perfect" in seen[-1] and "q1 -> a1" in seen[-1] and "10 items" in seen[-1]
    server.ask = fake(json.dumps({**exam, "exercises": ex[:3]}))
    err(lambda: server.run_task("exam", {"level": "B1"}), "incomplete")
    server.ask = fake(json.dumps({"title": "T", "exercises": ex}))
    err(lambda: server.run_task("exam", {"level": "B1"}), "incomplete")

    # level test and practice plan
    pit = lambda lv, sk="grammar": {"level": lv, "skill": sk, "type": "choice", "q": "q ___", "options": ["a", "b"], "answer": "a"}
    items = [pit(l) for l in ("B1", "A1", "A2", "A1")] + [pit("C2", "vocab"), pit("B2"), {**pit("A1"), "skill": "x"},
             {**pit("A1"), "type": "write"}, pit("Z9"), "junk"]
    server.ask = fake(json.dumps({"items": items}))
    assert [e["level"] for e in server.run_task("placement", {})["items"]] == ["A1", "A1", "A2", "B1", "B2", "C2"]
    server.ask = fake(json.dumps({"items": items[:3]}))
    err(lambda: server.run_task("placement", {}), "incomplete")
    server.ask = fake(json.dumps({"summary": "s", "strengths": ["a"], "weak": ["b", "c"], "units": [{"practice": "p"}] * 3 + [{"practice": ""}, "junk"]}))
    c = server.run_task("course", {"level": "B1", "scores": "A1: 2/2"})
    assert len(c["units"]) == 3 and c["weak"] == ["b", "c"] and "B1" in seen[-1] and "A1: 2/2" in seen[-1]
    server.ask = fake(json.dumps({"summary": "s", "units": [{"practice": "p"}]}))
    err(lambda: server.run_task("course", {"level": "A1"}), "incomplete")

    server.ask = fake("not json")
    err(lambda: server.run_task("grammar", {"level": "A1"}), "not valid")
    err(lambda: server.run_task("vocab", {"level": "Z9"}), "Bad level")
    server.ask = fake("fb")
    assert all(server.run_task(t, {"level": "C2"}) == "fb" for t in ("sentence", "grade", "test", "verify"))
    server.run_task("verify", {"level": "B1", "q": "Match: a", "key": "a = 2", "yours": "a = 1"})
    assert "Answer key: a = 2" in seen[-1] and "Student answered: a = 1" in seen[-1] and "RIGHT or WRONG" in seen[-1]

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

    # progress: saved per user on the server, put into the page, merged, validated; optional login
    page = lambda h={}: urllib.request.urlopen(urllib.request.Request(U + "/", headers=h)).read().decode()
    assert "__PROGRESS__" not in page() and "SERVER_PROGRESS={}" in page()
    post("/progress", {"data": {"cards": '{"a":1}', "log": "x</script>"}})
    post("/progress", {"data": {"lv": "B1", "missed": "[]", "lessons": "{}", "testmark": "null", "sessions": "{}", "_t": "123"}})
    p = page()
    assert "x</script>" not in p and "x\\u003c/script>" in p and '"lv": "B1"' in p and '"cards"' in p
    for bad in ({"evil": "x"}, {"cards": 5}, {"bk": "x"}): err(lambda: post("/progress", {"data": bad}), "Bad progress")
    err(lambda: post("/progress", {}), "Bad progress")
    server.AUTH = "pw"
    try: page(); raise SystemExit("expected 401")
    except urllib.error.HTTPError as e: assert e.code == 401
    ok = {"Authorization": "Basic " + base64.b64encode(b"daisy:pw").decode()}
    assert "SERVER_PROGRESS={}" in page(ok)  # her own, still empty
    urllib.request.urlopen(urllib.request.Request(U + "/progress", json.dumps({"data": {"lv": "A2"}}).encode(), ok))
    assert os.path.exists(os.path.join(server.DATA, "daisy.json")) and '"lv": "A2"' in page(ok) and '"lv": "B1"' not in page(ok)
    try: page({"Authorization": "Basic " + base64.b64encode(b"daisy:bad").decode()}); raise SystemExit("expected 401")
    except urllib.error.HTTPError as e: assert e.code == 401
    server.AUTH = ""
    print("all ok")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
