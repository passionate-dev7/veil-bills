#!/usr/bin/env python3
"""Throwaway stub for the M0 routing test (NOT the Veil gateway).
Logs every request it receives (method, path, headers minus auth, body preview)
and forwards to Nebius Token Factory using the key from the NEBIUS_API_KEY env var.
Usage: NEBIUS_API_KEY=... python3 stub_gateway.py [port] [bind]
"""
import http.server, json, os, sys, time, urllib.request, urllib.error

UPSTREAM = "https://api.tokenfactory.nebius.com"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
BIND = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
KEY = os.environ.get("NEBIUS_API_KEY", "")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "stub_gateway.log")

def log(rec):
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    line = json.dumps(rec)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        hdrs = {k: ("<redacted>" if k.lower() in ("authorization", "x-api-key") else v) for k, v in self.headers.items()}
        log({"event": "request", "client": self.client_address[0], "method": self.command, "path": self.path,
             "headers": hdrs, "body_preview": body[:300].decode("utf-8", "replace")})
        req = urllib.request.Request(UPSTREAM + self.path, data=body or None, method=self.command)
        req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
        req.add_header("Authorization", "Bearer " + KEY)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                code, data, ct = r.status, r.read(), r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            code, data, ct = e.code, e.read(), e.headers.get("Content-Type", "application/json")
        except Exception as e:
            code, data, ct = 502, json.dumps({"error": str(e)}).encode(), "application/json"
        log({"event": "forwarded", "path": self.path, "status": code, "bytes": len(data)})
        self.send_response(code); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_DELETE = _do
    def log_message(self, *a): pass

if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    print(f"stub gateway on {BIND}:{PORT} -> {UPSTREAM}", flush=True)
    http.server.ThreadingHTTPServer((BIND, PORT), H).serve_forever()
