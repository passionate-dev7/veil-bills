"""Full-page screenshots + console check with headless Chrome (no Playwright needed).
usage: python tools/shots.py URL OUTPREFIX [widths=1440,768,390]   -> OUTPREFIX-<w>.png ; exits 1 if the console shows errors."""
import subprocess, sys, re, tempfile, os
from PIL import Image, ImageChops
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
url, prefix = sys.argv[1], sys.argv[2]
widths = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "1440,768,390").split(",")]
bad = 0
for w in widths:
    out = f"{prefix}-{w}.png"
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},16000", "--virtual-time-budget=6000",
                        "--enable-logging=stderr", "--v=0", f"--screenshot={out}", url], capture_output=True, text=True, timeout=120)
    im = Image.open(out).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((2, im.height - 2)))
    box = ImageChops.difference(im, bg).getbbox()
    if box and box[3] + 24 < im.height:
        im = im.crop((0, 0, im.width, box[3] + 24))
    im.save(out)
    msgs = [l for l in r.stderr.splitlines() if re.search(r"CONSOLE|ERR_|Uncaught|net::", l)]
    print(f"{out}: {im.size[0]}x{im.size[1]} console_messages={len(msgs)}")
    for m in msgs[:8]:
        print("   ", m[:240]); bad += 1
sys.exit(1 if bad else 0)
