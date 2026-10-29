"""Full-page screenshots + console check with headless Chrome (no Playwright needed).
usage: python tools/shots.py URL OUTPREFIX [widths=1440,768,390]   -> OUTPREFIX-<w>.png ; exits 1 if the console shows errors."""
import subprocess, sys, re, tempfile, os, threading, functools, http.server, socketserver
from PIL import Image, ImageChops
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
url, prefix = sys.argv[1], sys.argv[2]
widths = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "1440,768,390").split(",")]
bad = 0
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
for w in widths:
    out = f"{prefix}-{w}.png"
    shot_url, win, srv, wrap = url, w, None, None
    if w < 500 and url.startswith("file://"):  # headless Chrome enforces a ~500px minimum window: lay out in a w-wide iframe over http
        d, f = os.path.split(url[7:])
        wrap = os.path.join(d, "_wrap.html")
        open(wrap, "w").write(f'<body style="margin:0;background:#faf6ee"><iframe src="{f}" style="display:block;width:{w}px;height:24000px;border:0"></iframe>')
        srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=d))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        shot_url, win = f"http://127.0.0.1:{srv.server_address[1]}/_wrap.html", 500
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={win},24000", "--virtual-time-budget=6000",
                        "--enable-logging=stderr", "--v=0", f"--screenshot={out}", shot_url], capture_output=True, text=True, timeout=120)
    if srv: srv.shutdown(); os.remove(wrap)
    im = Image.open(out).convert("RGB")
    if im.width > w: im = im.crop((0, 0, w, im.height))
    bg = Image.new("RGB", im.size, im.getpixel((2, im.height - 40)))
    box = ImageChops.difference(im, bg).getbbox()
    if box and box[3] + 24 < im.height - 40:
        im = im.crop((0, 0, im.width, box[3] + 24))
    im.save(out)
    msgs = [l for l in r.stderr.splitlines() if re.search(r"CONSOLE|ERR_|Uncaught|net::", l)]
    print(f"{out}: {im.size[0]}x{im.size[1]} console_messages={len(msgs)}")
    for m in msgs[:8]:
        print("   ", m[:240]); bad += 1
sys.exit(1 if bad else 0)
