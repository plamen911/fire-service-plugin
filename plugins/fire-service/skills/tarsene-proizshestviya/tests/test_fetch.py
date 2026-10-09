#!/usr/bin/env python3
"""Tests for the shared network helper and fetch_incidents.py – with a local stub instead of n8n.
Run from the skill folder:  python3 tests/test_fetch.py
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SHARED = os.path.join(SKILL, "_shared", "scripts")
STATS = os.path.join(SKILL, "scripts", "incident_stats.py")
F26 = os.path.join(HERE, "fixtures", "records_2026.json")
os.environ.pop("FIRE_SERVICE_NO_KEY", None)
sys.path.insert(0, SHARED)
import api_config  # noqa: E402
import fetch_incidents  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Stub(http.server.BaseHTTPRequestHandler):
    plan, calls, keys = [], 0, []

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Stub.calls += 1
        Stub.keys.append(self.headers.get("X-Api-Key"))
        status, body = Stub.plan.pop(0) if Stub.plan else (200, "{}")
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *a):
        pass


def main():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api_config._cache["cfg"] = {"key": "test-key", "key_source": "test", "header": "X-Api-Key",
                                "url": f"http://127.0.0.1:{srv.server_port}/"}
    api_config.RETRY_PAUSE = 0

    Stub.plan, Stub.calls = [(200, '{"ok": true}')], 0
    check(api_config.post("url", {}) == {"ok": True} and Stub.calls == 1, "a good answer is returned after one call")
    check(Stub.keys[-1] == "test-key", "the key travels in the header")

    Stub.plan, Stub.calls = [(503, "down"), (200, '{"ok": true}')], 0
    check(api_config.post("url", {}) == {"ok": True} and Stub.calls == 2, "503 from the proxy → one more attempt")

    Stub.plan, Stub.calls = [(503, "down"), (503, "down"), (200, "{}")], 0
    try:
        api_config.post("url", {})
        check(False, "two 503 in a row → the error is raised")
    except Exception as e:  # noqa: BLE001
        check(getattr(e, "code", None) == 503 and Stub.calls == 2, "two 503 in a row → raised after exactly two calls")

    Stub.plan, Stub.calls = [(500, "boom"), (200, "{}")], 0
    try:
        api_config.post("url", {})
        check(False, "500 → raised")
    except Exception as e:  # noqa: BLE001
        check(getattr(e, "code", None) == 500 and Stub.calls == 1, "500 is not repeated (the request may have been carried out)")

    Stub.plan, Stub.calls = [(200, "<html>Bad gateway</html>")], 0
    try:
        api_config.post("url", {})
        check(False, "not JSON → ValueError")
    except ValueError as e:
        check("не е JSON" in str(e) and "<html>" in str(e), "an answer that is not JSON gives a clear message")

    Stub.plan = [(401, "no")]
    try:
        api_config.post("url", {})
        check(False, "401 → KEY_REJECTED")
    except SystemExit as e:
        check(str(e).startswith("KEY_REJECTED"), "401 → KEY_REJECTED")

    dead = dict(api_config._cache["cfg"], url="http://127.0.0.1:9/")   # nothing listens on port 9
    api_config._cache["cfg"] = dead
    try:
        api_config.post("url", {}, timeout=3)
        check(False, "refused connection → raised")
    except OSError:
        check(True, "a refused connection is raised after the second attempt")
    srv.shutdown()

    # fetch_incidents: arguments and the local filter
    a = fetch_incidents.parse_args(["2026-09-24", "--filter", "location=Опанец", "--filter", "object=", "--limit", "99999"])
    check(a.date_from == a.date_to == "2026-09-24" and a.filters == {"location": ["Опанец"]} and a.limit == 5000,
          "one date = a one-day period; an empty filter is dropped; the limit is capped at 5000")
    for bad in (["2026-13-01"], ["--from", "2026-02-01", "--to", "2026-01-01"], ["--from", "2024-01-01", "--to", "2026-01-01"]):
        try:
            fetch_incidents.parse_args(bad)
            check(False, f"{bad} → BAD_REQUEST")
        except SystemExit as e:
            check(str(e).startswith("BAD_REQUEST"), f"{' '.join(bad)} → BAD_REQUEST")
    rows = json.load(open(F26, encoding="utf-8"))
    a = fetch_incidents.parse_args(["2026-01-01", "--all", "--limit", "3"])
    got, total = fetch_incidents.select(list(rows), a)
    check(len(got) == 3 and total == len(rows), "select: the limit cuts the list, total stays the full count")

    # --place: the place is looked for in every field that may carry it
    road = [
        {"id": "1", "dat": "2026-10-08 22:45:00", "casulaty": "катастрофа с транспортни средства-12",
         "location": "пътя Плевен-Ясен", "address": "пътя Плевен-Ясен", "object": "катастрофа между два автомобила"},
        {"id": "2", "dat": "2026-10-09 02:14:00", "casulaty": "техническа помощ-13",
         "location": "гр. Плевен ", "address": "гр. Плевен, пътя Плевен – Ясен", "object": "измиване на пътното платно след ПТП"},
        {"id": "3", "dat": "2026-10-09 05:00:00", "casulaty": "техническа помощ-13",
         "location": "гр. Плевен ", "address": "гр. Плевен, ж.к. Дружба", "object": "отваряне на врата"},
        {"id": "4", "dat": "2026-10-09 06:00:00", "casulaty": "пожар без преки материални загуби-03",
         "location": "с. Опанец", "address": None, "object": "суха трева край пътя за ЯСЕН"},
    ]
    a = fetch_incidents.parse_args(["--from", "2026-10-08", "--to", "2026-10-09", "--all", "--place", "Ясен"])
    got, total = fetch_incidents.select([dict(r) for r in road], a)
    check([r["id"] for r in got] == ["4", "2", "1"] and total == 3,
          "--place finds the place in location, in the address and in the object, not only in location")
    check({r["id"]: r["matched_in"] for r in got} == {"1": ["location", "address"], "2": ["address"], "4": ["object"]},
          "… and every record says in which fields it was found")
    a = fetch_incidents.parse_args(["2026-10-09", "--all", "--filter", "location=Ясен"])
    got, _ = fetch_incidents.select([dict(r) for r in road], a)
    check([r["id"] for r in got] == ["1"], "--filter location alone misses the follow-up call at the same place")
    a = fetch_incidents.parse_args(["2026-10-09", "--all", "--place", "Ясен", "--place", "Дружба", "--filter", "casulaty=техническа"])
    got, _ = fetch_incidents.select([dict(r) for r in road], a)
    check([r["id"] for r in got] == ["3", "2"], "repeated --place = any of them; together with --filter = both must hold")
    check(fetch_incidents.parse_args(["2026-10-09", "--place", "  "]).places == [], "an empty --place is dropped")

    # a list that was cut is marked beside the file, and the statistics say so
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "rec.json")
        json.dump(rows, open(f, "w", encoding="utf-8"), ensure_ascii=False)
        r = subprocess.run([sys.executable, STATS, f, "--count-only"], capture_output=True, text=True)
        check("warning" not in json.loads(r.stdout), "a complete file → no warning")
        json.dump({"returned": len(rows), "total": len(rows) + 40, "truncated": True}, open(f + ".meta.json", "w"))
        res = json.loads(subprocess.run([sys.executable, STATS, f, "--count-only"], capture_output=True, text=True).stdout)
        check("НЕПЪЛНИ ДАННИ" in res.get("warning", "") and res["truncated"][0]["total"] == len(rows) + 40,
              "a file marked as cut → the result carries a warning")

    print("\nALL PASS" if not failures else f"\n{len(failures)} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
