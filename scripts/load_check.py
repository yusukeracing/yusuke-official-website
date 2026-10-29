#!/usr/bin/env python3
"""Bounded, loopback-only static-page load measurement (no external traffic).

This is not a GitHub Pages capacity test. All clients fetch a local built site;
Google Forms, Analytics, social sites and the public website are never contacted.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
import hashlib
from html.parser import HTMLParser
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import resource
import socket
from threading import Barrier, Lock, Thread
import time
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 512 * 1024 * 1024
MAX_REQUESTS = 10000


class InitialResources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = ["index.html"]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = None
        if tag == "link" and attrs.get("rel") in {"stylesheet", "icon"}:
            value = attrs.get("href")
        elif tag == "script":
            value = attrs.get("src")
        elif tag == "img" and attrs.get("fetchpriority") == "high":
            value = attrs.get("src")
        elif tag == "use":
            value = attrs.get("href")
        if value:
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc:
                raise ValueError("The benchmark does not permit external page resources")
            path = unquote(parsed.path)
            if path and path not in self.paths:
                self.paths.append(path)


def manifest_for(directory):
    parser = InitialResources()
    parser.feed((directory / "index.html").read_text(encoding="utf-8"))
    loader = (directory / "assets/js/data-loader.js").read_text(encoding="utf-8")
    match = re.search(r"const\s+fileNames\s*=\s*(\[[^\]]+\])", loader)
    if not match:
        raise ValueError("Cannot identify the data loader's initial JSON requests")
    names = json.loads(match[1])
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z]+", name):
            raise ValueError("Unexpected initial JSON name")
        path = f"data/{name}.json"
        if path not in parser.paths:
            parser.paths.append(path)
    site = json.loads((directory / "data/site.json").read_text(encoding="utf-8"))
    hero = site.get("heroImage", "")
    if hero and "xxx" not in hero:
        parsed = urlsplit(hero)
        if parsed.scheme or parsed.netloc:
            raise ValueError("The benchmark only reads local HERO files")
        if parsed.path not in parser.paths:
            parser.paths.append(parsed.path)
    manifest = []
    for path in parser.paths:
        target = (directory / path).resolve()
        if (path.startswith("/") or not target.is_relative_to(directory)
                or not target.is_file()
                or not (path == "index.html" or path.startswith(("assets/", "data/")))):
            raise ValueError(f"Unsafe or missing public resource: {path}")
        body = target.read_bytes()
        manifest.append({"path": path, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    return manifest


class Counters:
    def __init__(self):
        self.lock = Lock()
        self.current = {"connections": 0, "handlers": 0, "requests": 0, "journeys": 0}
        self.peak = dict(self.current)

    def add(self, key, amount):
        with self.lock:
            self.current[key] += amount
            self.peak[key] = max(self.peak[key], self.current[key])


class LocalServer(ThreadingHTTPServer):
    # Explicit test setting: this is not the production CDN's queue configuration.
    request_queue_size = 128
    daemon_threads = True
    block_on_close = False


class LocalHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.connection.settimeout(5)
        self.counters = self.server.counters
        self.counters.add("connections", 1)

    def finish(self):
        try:
            super().finish()
        finally:
            self.counters.add("connections", -1)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = unquote(urlsplit(self.path).path).lstrip("/")
        if path not in self.server.allowed_paths:
            self.send_error(404)
            return
        self.counters.add("handlers", 1)
        try:
            super().do_GET()
        finally:
            self.counters.add("handlers", -1)

    def do_POST(self):
        self.send_error(405)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 3)


def distribution(values):
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95),
            "max": round(max(values), 3) if values else None}


def measure(server, manifest, concurrency, journeys_per_client, stage_seconds):
    counters = server.counters = Counters()
    barrier = Barrier(concurrency)
    stage_start = time.perf_counter()
    deadline = stage_start + stage_seconds

    def client(_number):
        outcomes, requests, first_bytes, errors = [], [], [], []
        transferred = 0
        attempts = 0
        barrier.wait(timeout=10)
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            for _ in range(journeys_per_client):
                if time.perf_counter() >= deadline:
                    outcomes.append(("aborted", 0))
                    continue
                counters.add("journeys", 1)
                started = time.perf_counter()
                outcome = "success"
                try:
                    for entry in manifest:
                        remaining = deadline - time.perf_counter()
                        if remaining <= 0:
                            raise TimeoutError("stage time limit")
                        connection.timeout = min(3, remaining)
                        if connection.sock:
                            connection.sock.settimeout(connection.timeout)
                        before = time.perf_counter()
                        attempts += 1
                        counters.add("requests", 1)
                        try:
                            connection.request("GET", "/" + entry["path"], headers={"Cache-Control": "no-cache"})
                            response = connection.getresponse()
                            first_bytes.append((time.perf_counter() - before) * 1000)
                            body = response.read()
                            elapsed = (time.perf_counter() - before) * 1000
                        finally:
                            counters.add("requests", -1)
                        requests.append(elapsed)
                        transferred += len(body)
                        if response.status != 200:
                            raise ValueError(f"HTTP {response.status}: {entry['path']}")
                        if response.getheader("Content-Length") != str(entry["bytes"]):
                            raise ValueError(f"Content-Length mismatch: {entry['path']}")
                        if len(body) != entry["bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
                            raise ValueError(f"body integrity mismatch: {entry['path']}")
                except Exception as error:
                    outcome = "failed"
                    errors.append(f"{type(error).__name__}: {error}")
                    connection.close()
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                finally:
                    counters.add("journeys", -1)
                outcomes.append((outcome, (time.perf_counter() - started) * 1000))
        finally:
            connection.close()
        return outcomes, requests, first_bytes, transferred, errors, attempts

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(client, range(concurrency)))
    elapsed = time.perf_counter() - stage_start
    outcomes = [item for result in results for item in result[0]]
    requests = [item for result in results for item in result[1]]
    first_bytes = [item for result in results for item in result[2]]
    errors = [item for result in results for item in result[4]]
    success = [ms for outcome, ms in outcomes if outcome == "success"]
    return {
        "configured_parallel_clients": concurrency,
        "journeys_per_client": journeys_per_client,
        "planned_journeys": concurrency * journeys_per_client,
        "successful_journeys": len(success),
        "failed_journeys": sum(outcome == "failed" for outcome, _ in outcomes),
        "aborted_journeys": sum(outcome == "aborted" for outcome, _ in outcomes),
        "completed_http_responses": len(requests),
        "http_request_attempts": sum(result[5] for result in results),
        "bytes_received": sum(result[3] for result in results),
        "duration_seconds": round(elapsed, 3),
        "successful_journeys_per_second": round(len(success) / elapsed, 3),
        "completed_responses_per_second": round(len(requests) / elapsed, 3),
        "journey_latency_ms": distribution(success),
        "response_transfer_latency_ms": distribution(requests),
        "response_headers_ttfb_ms": distribution(first_bytes),
        "peak_open_local_connections": counters.peak["connections"],
        "peak_client_journeys_in_flight": counters.peak["journeys"],
        "peak_client_http_requests_in_flight": counters.peak["requests"],
        "peak_server_handlers": counters.peak["handlers"],
        "errors": errors[:10],
    }


def read_system_file(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "dist", help="Already-built public directory")
    parser.add_argument("--max-concurrency", type=int, choices=(1, 10, 25, 50, 100), default=100)
    parser.add_argument("--journeys-per-client", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--stage-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/load-results.json")
    args = parser.parse_args()
    if not 5 <= args.stage_seconds <= 30:
        parser.error("--stage-seconds must be between 5 and 30")
    directory = args.directory.resolve()
    if not (directory / ".nojekyll").is_file():
        parser.error("Use a generated public directory containing .nojekyll")
    manifest = manifest_for(directory)
    levels = [level for level in (1, 10, 25, 50, 100) if level <= args.max_concurrency]
    planned_journeys = sum(levels) * args.journeys_per_client
    planned_requests = planned_journeys * len(manifest)
    planned_bytes = planned_journeys * sum(entry["bytes"] for entry in manifest)
    if planned_requests > MAX_REQUESTS or planned_bytes > MAX_BYTES:
        parser.error("The planned workload exceeds the local 10,000-request / 512 MiB safety budget")
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "loopback-only; local Python static server; NOT GitHub Pages or Google Forms capacity",
        "cache_model": "Every journey transfers all resources; no browser cache. OS filesystem cache is not flushed.",
        "server_configuration": {"implementation": "Python ThreadingHTTPServer", "http_version": "HTTP/1.1",
                                 "listen_address": "127.0.0.1 (ephemeral port)", "request_queue_size": 128,
                                 "tcp_nodelay": True},
        "limits": {"stage_seconds": args.stage_seconds, "planned_requests": planned_requests,
                   "planned_bytes": planned_bytes, "max_requests": MAX_REQUESTS, "max_bytes": MAX_BYTES},
        "hardware": {"python": platform.python_version(), "platform": platform.system(),
                     "host_logical_cpu_count": os.cpu_count(), "cgroup_cpu_max": read_system_file("/sys/fs/cgroup/cpu.max"),
                     "cgroup_memory_max_bytes": read_system_file("/sys/fs/cgroup/memory.max")},
        "manifest": manifest,
        "stages": [],
    }
    server = LocalServer(("127.0.0.1", 0), partial(LocalHandler, directory=str(directory)))
    server.allowed_paths = {entry["path"] for entry in manifest}
    server.counters = Counters()
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        for concurrency in levels:
            result = measure(server, manifest, concurrency, args.journeys_per_client, args.stage_seconds)
            report["stages"].append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        server.shutdown()
        server.server_close()
    report["process_peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
    no_error_stages = [stage["configured_parallel_clients"] for stage in report["stages"]
                       if stage["successful_journeys"] == stage["planned_journeys"]
                       and not stage["failed_journeys"] and not stage["aborted_journeys"]]
    report["highest_error_free_tested_parallel_clients"] = max(no_error_stages, default=0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved local-only measurement: {args.output}")
    print("This result does not establish a production concurrent-user limit.")
    return 0 if len(no_error_stages) == len(levels) else 1


if __name__ == "__main__":
    raise SystemExit(main())
