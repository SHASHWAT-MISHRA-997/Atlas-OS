"""Research questions 1 (ATLAS overhead only) and 2 (cancellation latency). See docs/RESEARCH.md.

    cd backend && python research/bench_latency.py [runs]

MOCK NOTICE: the model is a fake OpenAI-compatible server in this process that streams a token
every 2 ms. The numbers measure ATLAS's own overhead and how fast Stop reaches the model server.
They say nothing about how fast a real model answers.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
TOKEN_INTERVAL = 0.002


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeModel:
    def __init__(self):
        self.closed_at: list[float] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": "bench:1b", "size": 1, "details": {}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for i in range(5000):
                        data = json.dumps({"choices": [{"delta": {"content": f"t{i} "}, "finish_reason": None}]})
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(TOKEN_INTERVAL)
                except (BrokenPipeError, ConnectionResetError):
                    outer.closed_at.append(time.perf_counter())

        self.port = free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def summary(values: list[float]) -> dict:
    ms = sorted(v * 1000 for v in values)
    return {"n": len(ms), "median_ms": round(statistics.median(ms), 1),
            "p95_ms": round(ms[max(0, int(len(ms) * 0.95) - 1)], 1), "max_ms": round(ms[-1], 1)}


CLIENT = httpx.Client(timeout=10)  # one client, so the benchmark's own set-up cost is not measured


def first_token_direct(base: str) -> float:
    start = time.perf_counter()
    with CLIENT.stream("POST", base + "/v1/chat/completions", json={"model": "bench:1b", "stream": True,
                      "messages": [{"role": "user", "content": "hi"}]}) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                return time.perf_counter() - start
    raise RuntimeError("no token")


def first_token_via_atlas(atlas: str, cancel: bool, fake: FakeModel) -> tuple[float, float | None]:
    body = {"provider": "ollama", "model": "bench:1b", "messages": [{"role": "user", "content": "hi"}]}
    before = len(fake.closed_at)
    start = time.perf_counter()
    with CLIENT.stream("POST", atlas + "/api/llm/chat/stream", json=body) as r:
        r.raise_for_status()
        event = ""
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "delta":
                ttft = time.perf_counter() - start
                break
        stop_at = time.perf_counter()
    if not cancel:
        return ttft, None
    deadline = time.time() + 5
    while len(fake.closed_at) == before and time.time() < deadline:
        time.sleep(0.001)
    if len(fake.closed_at) == before:
        return ttft, float("inf")
    return ttft, fake.closed_at[-1] - stop_at


def main(runs: int) -> dict:
    fake = FakeModel()
    model_base = f"http://127.0.0.1:{fake.port}"
    port = free_port()
    env = {**os.environ, "ATLAS_OLLAMA_BASE_URL": model_base, "ATLAS_DATA_DIR": tempfile.mkdtemp(),
           "ATLAS_AUTH_REQUIRED": "false", "ATLAS_LLM_RATE_LIMIT_PER_MINUTE": "100000", "PYTHONPATH": str(BACKEND)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
                            cwd=BACKEND, env=env)
    atlas = f"http://127.0.0.1:{port}"
    try:
        for _ in range(200):
            try:
                if httpx.get(atlas + "/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        for _ in range(3):  # warm-up
            first_token_direct(model_base)
            first_token_via_atlas(atlas, True, fake)
        direct = [first_token_direct(model_base) for _ in range(runs)]
        via, cancel = [], []
        for _ in range(runs):
            ttft, closed = first_token_via_atlas(atlas, True, fake)
            via.append(ttft)
            cancel.append(closed)
            time.sleep(0.02)
    finally:
        proc.terminate()
        proc.wait(10)
    return {
        "environment": {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system(),
                        "cpus": os.cpu_count(), "token_interval_ms": TOKEN_INTERVAL * 1000},
        "first_token_direct_to_fake_model": summary(direct),
        "first_token_through_atlas": summary(via),
        "stop_to_model_connection_closed": summary([c for c in cancel if c != float("inf")]),
        "stop_never_reached_model": sum(1 for c in cancel if c == float("inf")),
    }


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]) if len(sys.argv) > 1 else 50), indent=2))
