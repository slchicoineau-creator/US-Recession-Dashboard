"""
Serve a static snapshot the way GitHub Pages does, for local testing.

    python tools/serve_static.py --dir site --base /recession-dashboard/ --port 5055

- Files are served under the --base prefix (a Pages project site lives at
  /<repo>/), so asset paths built with VITE_BASE are exercised for real.
- An unknown path returns <dir>/404.html with HTTP 404 — exactly GitHub Pages'
  behaviour, which is what makes SPA deep links work there. (Python's plain
  http.server has no such fallback, so it would fail deep links for the wrong
  reason.)
"""

import argparse
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse


def make_handler(root: str, base: str):
    root = os.path.abspath(root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send_file(self, path: str, status: int):
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url_path = unquote(urlparse(self.path).path)
            if url_path + "/" == base:
                url_path = base
            if not url_path.startswith(base):
                return self._send_file(os.path.join(root, "404.html"), 404)
            rel = url_path[len(base):]
            candidate = os.path.abspath(os.path.join(root, rel))
            if not candidate.startswith(root):
                return self._send_file(os.path.join(root, "404.html"), 404)
            if os.path.isdir(candidate):
                candidate = os.path.join(candidate, "index.html")
            if os.path.isfile(candidate):
                return self._send_file(candidate, 200)
            return self._send_file(os.path.join(root, "404.html"), 404)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="site")
    ap.add_argument("--base", default="/")
    ap.add_argument("--port", type=int, default=5055)
    args = ap.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.dir, base))
    print(f"Serving {os.path.abspath(args.dir)} at http://127.0.0.1:{args.port}{base}")
    server.serve_forever()


if __name__ == "__main__":
    main()
