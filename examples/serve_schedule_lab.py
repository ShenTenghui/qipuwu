"""Serve the synthetic scheduling lab on a separate loopback port.

Usage: python -B examples/serve_schedule_lab.py
Defaults to an OS-selected free port. No database, engine, collector or writes.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.schedule_demo import DEFAULT_SEED, run_demo


PAGE = Path(__file__).with_name("schedule_lab.html")


class LabHandler(BaseHTTPRequestHandler):
    server_version = "QipuwuScheduleLab/1.0"

    def respond(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def json_response(self, status, payload):
        self.respond(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/":
            self.respond(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if url.path != "/api/schedule":
            self.json_response(404, {"error": "Not found"})
            return
        if len(url.query) > 1024:
            self.json_response(400, {"error": "Query too long"})
            return
        try:
            query = parse_qs(url.query, keep_blank_values=True, max_num_fields=8)
            if any(key not in {"new", "review", "sources", "seed"} or len(values) != 1
                   for key, values in query.items()):
                raise ValueError("Unsupported or repeated parameter")
            result = run_demo(
                int(query.get("new", [12])[0]),
                int(query.get("review", [12])[0]),
                int(query.get("sources", [8])[0]),
                query.get("seed", [DEFAULT_SEED])[0],
            )
        except (ValueError, TypeError) as error:
            self.json_response(400, {"error": str(error)})
            return
        self.json_response(200, result)

    def log_message(self, format, *args):
        pass


def make_server(port=0):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be from 0 to 65535")
    if port == 8642:
        raise ValueError("8642 is reserved for the separate full application")
    return ThreadingHTTPServer(("127.0.0.1", port), LabHandler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="0 chooses a free local port")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.port)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Scheduling lab: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    print("Synthetic inputs only. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
