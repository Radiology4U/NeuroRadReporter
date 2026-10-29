#!/usr/bin/env python3
"""
Tiny local RAG API server — run this alongside your app in production.
Exposes: POST /retrieve  { "text": "...", "n": 3 }
Returns: { "cases": [...], "context": "markdown string" }

For production SaaS: deploy this on a small VPS or Fly.io alongside
your static GitHub Pages frontend. The frontend calls this endpoint
before sending to Claude.

Run: python rag_server.py  (default port 8765)
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from query_rag import retrieve_similar_cases, format_rag_context


class RAGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress noisy access logs

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/retrieve":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        query_text = body.get("text", "").strip()
        n = min(int(body.get("n", 3)), 5)

        if not query_text:
            self._json({"error": "text required"}, 400)
            return

        try:
            cases = retrieve_similar_cases(query_text, n_results=n)
            context = format_rag_context(cases)
            self._json({"cases": cases, "context": context})
        except Exception as e:
            self._json({"error": str(e), "cases": [], "context": ""}, 500)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = HTTPServer(("0.0.0.0", port), RAGHandler)
    print(f"RAG server running on http://0.0.0.0:{port}")
    print("POST /retrieve  {\"text\": \"findings...\", \"n\": 3}")
    server.serve_forever()
