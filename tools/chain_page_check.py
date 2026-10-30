"""Drive web/index.html in headless Chrome (DevTools protocol): the chain verifies in the page, the tamper demo breaks at the right
entry, the console stays clean. Saves a screenshot of the receipts panel before and after tampering.
usage: python3 tools/chain_page_check.py OUTPREFIX [widths=1440,390]    (needs: pip install websocket-client pillow)"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
page = "file://" + os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "index.html"))
prefix = sys.argv[1]
widths = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "1440,390").split(",")]
errors, fails = [], []

def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))
    if not ok: fails.append(name)

for w in widths:
    port = 9400 + w % 100
    prof = tempfile.mkdtemp()
    ch = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--hide-scrollbars", "about:blank"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
            except Exception: time.sleep(0.2)
        ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], timeout=30)
        n = [0]
        def call(method, **params):
            n[0] += 1; ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            while True:
                m = json.loads(ws.recv())
                if m.get("method") == "Runtime.exceptionThrown": errors.append(m["params"]["exceptionDetails"]["text"] + str(m["params"]["exceptionDetails"].get("exception", {}).get("description", "")))
                if m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] in ("error", "warning"): errors.append(str(m["params"]["args"]))
                if m.get("method") == "Log.entryAdded" and m["params"]["entry"]["level"] in ("error", "warning"): errors.append(m["params"]["entry"]["text"] + " " + m["params"]["entry"].get("url", ""))
                if m.get("id") == n[0]: return m.get("result", {})
        ev = lambda js: call("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True).get("result", {}).get("value")
        call("Runtime.enable"); call("Log.enable"); call("Page.enable")
        call("Emulation.setDeviceMetricsOverride", width=w, height=1000, deviceScaleFactor=1, mobile=False)
        call("Page.navigate", url=page)
        for _ in range(60):
            if ev("document.querySelector('#chStat')&&document.querySelector('#chStat').textContent.startsWith('Chain')"): break
            time.sleep(0.25)
        print(f"-- {w}px")
        check("chain verifies in the page", ev("document.querySelector('#chStat').textContent") == "Chain OK", ev("document.querySelector('#chMsg').textContent"))
        head = ev("document.querySelector('#chHead').textContent")
        check("head shown", len(head) == 64, head)
        def shot(name):
            r = ev("(()=>{const b=document.querySelector('#p-chain').getBoundingClientRect();return [b.x,b.y+scrollY,b.width,b.height]})()")
            out = call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=0, y=r[1], width=w, height=r[3] + 16, scale=1))
            open(f"{prefix}-{name}-{w}.png", "wb").write(base64.b64decode(out["data"]))
        shot("chain")
        for kind, want in (("bytes", "bytes"), ("field", "edited"), ("delete", "missing"), ("reorder", "reordered")):
            ev(f"(()=>{{const k=document.querySelector('#chKind');k.value='{kind}';document.querySelector('#chSeq').value='7';document.querySelector('#chGo').click()}})()")
            time.sleep(0.6)
            t = ev("document.querySelector('#chOut').textContent")
            seq = 7 if kind in ("bytes", "field") else 7
            check(f"tamper {kind} fails at seq 7 ({want})", f"Broken at seq 7" in t and want in t, t[:160])
            if kind == "bytes": shot("tampered")
        ev("document.querySelector('#chReset').click()")
        check("page chain untouched after demo", ev("document.querySelector('#chStat').textContent") == "Chain OK")
        # anchored head compare: right head passes, a wrong one fails
        ev(f"(()=>{{document.querySelector('#chAnch').value='{head}';document.querySelector('#chCmp').click()}})()"); time.sleep(0.4)
        check("anchored head matches", "Head matches" in ev("document.querySelector('#chCmpOut').textContent"))
        ev(f"(()=>{{document.querySelector('#chAnch').value='{'0'*64}';document.querySelector('#chCmp').click()}})()"); time.sleep(0.4)
        check("wrong anchored head fails", "Broken at seq" in ev("document.querySelector('#chCmpOut').textContent"))
        check("no horizontal overflow", ev("document.documentElement.scrollWidth<=innerWidth+1"), str(ev("document.documentElement.scrollWidth")))
        ws.close()
    finally:
        ch.terminate()
check("console clean", not errors, "; ".join(errors[:4]))
sys.exit(1 if fails else 0)
