import json, os, server, threading, urllib.request, urllib.error
assert len(server.trim(list(range(20)), 4)) == 8
server.ENV_FILE = server.CFG_FILE + ".tmpenv"; server.CFG_FILE += ".tmp"
json.dump({"provider":"anthropic","model":"m","base_url":"u","history_turns":4,"max_tokens":300}, open(server.CFG_FILE,"w"))
s = server.ThreadingHTTPServer(("127.0.0.1", 8123), server.H); threading.Thread(target=s.serve_forever, daemon=True).start()
U = "http://127.0.0.1:8123"
def post(p, b): return json.load(urllib.request.urlopen(urllib.request.Request(U+p, json.dumps(b).encode())))
try: post("/chat", {"messages":[]}); raise SystemExit("expected error")
except urllib.error.HTTPError as e: assert b"No API key" in e.read()
post("/settings", {"model":"x","api_key":"secret","history_turns":"2"})
r = json.load(urllib.request.urlopen(U+"/settings"))
assert r["model"]=="x" and r["history_turns"]==2 and r["key_set"] and "secret" not in json.dumps(r)
assert b"English Learner" in urllib.request.urlopen(U+"/").read()
os.remove(server.CFG_FILE); os.remove(server.ENV_FILE); print("ok")

# AI tasks with a fake model (no network, no real text)
seen = []
server.ask = lambda m, system=None, max_tokens=None: (seen.append(m[0]["content"]) or '```json\n[{"word":"a","ipa":"/a/","vi":"b","example":"c"}]\n```')
assert server.run_task("cards", {"level": "B1", "avoid": "x"})[0]["word"] == "a" and "B1" in seen[0]
server.ask = lambda m, system=None, max_tokens=None: "not json"
try: server.run_task("grammar", {"level": "A1"}); raise SystemExit("expected error")
except ValueError as e: assert "not valid" in str(e)
try: server.run_task("cards", {"level": "Z9"}); raise SystemExit("expected error")
except ValueError: pass
server.ask = lambda m, system=None, max_tokens=None: "fb"
assert all(server.run_task(t, {"level": "C2"}) == "fb" for t in ("sentence", "grade", "test"))
print("ok tasks")

# chat modes
got = {}
server.ask = lambda m, system=None, max_tokens=None: (got.update(s=system, t=max_tokens) or "r")
assert server.chat({"messages": [], "mode": "roleplay", "scenario": "meeting", "level": "B2"}) == "r" and "colleague" in got["s"] and "B2" in got["s"]
server.chat({"messages": [], "mode": "email"}); assert got["t"] == 500
for bad in ({"mode": "x"}, {"mode": "roleplay"}, {"level": "Z"}):
    try: server.chat({"messages": [], **bad}); raise SystemExit("expected error")
    except ValueError: pass
print("ok chat")
