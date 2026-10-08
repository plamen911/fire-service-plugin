#!/usr/bin/env python3
"""Tests for scripts/regs.py – listing, finding one file, downloading – with a local stand-in for the server.
Run from the skill folder:  python3 tests/test_regs.py
"""
import contextlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
os.environ.pop("FIRE_SERVICE_NO_KEY", None)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import regs  # noqa: E402
api_config = regs.api_config

failures = []
FILES = [
    {"id": "ID-IDX-OLD", "name": "_INDEX_pozharna_bezopasnost_2026-09-30a.md", "folder": "", "modified_at": "2026-09-30T10:00:00Z", "size": 10},
    {"id": "ID-IDX-NEW", "name": "_INDEX_pozharna_bezopasnost_2026-10-08w.md", "folder": "", "modified_at": "2026-10-08T10:00:00Z", "size": 12},
    {"id": "ID-MAP", "name": "_MAP_pg_sd.md", "folder": "", "modified_at": "2026-08-01T10:00:00Z", "size": 5},
    {"id": "ID-1006", "name": "GDPBZN_Ordinance_8121з-1006_2026.md", "folder": "tier-a", "modified_at": "2026-02-27T10:00:00Z", "size": 100},
    {"id": "ID-1006-APP", "name": "GDPBZN_Ordinance_8121з-1006_2026_Appendices.md", "folder": "tier-b", "modified_at": "2026-02-27T10:00:00Z", "size": 50},
    {"id": "ID-PDF", "name": "8121з-282.pdf", "folder": "tier-a", "modified_at": "2015-03-19T10:00:00Z", "size": 4000},
]
for f in FILES:
    f["path"] = (f["folder"] + "/" if f["folder"] else "") + f["name"]


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Stub(http.server.BaseHTTPRequestHandler):
    seen, fail = [], None

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Stub.seen.append(body)
        status, answer = 200, {}
        if Stub.fail:
            status, answer = Stub.fail
        elif body.get("action") == "list":
            answer = {"count": len(FILES), "files": FILES}
        elif body.get("action") == "download":
            f = next((x for x in FILES if x["id"] == body.get("id")), None)
            if f is None:
                status, answer = 404, {"error": "NOT_FOUND: File not found"}
            elif f["name"].endswith(".pdf"):
                status, answer = 415, {"error": "UNSUPPORTED: not a text file"}
            else:
                answer = {"path": f["path"], "modified_at": f["modified_at"], "content": f"# {f['name']}\n\n## Чл. 5\nтекст\n"}
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps(answer, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *a):
        pass


def call(argv):
    out, old = io.StringIO(), sys.argv
    sys.argv = ["regs.py"] + argv
    try:
        with contextlib.redirect_stdout(out):
            regs.main()
        code = None
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = old
    return code, out.getvalue()


def main():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api_config._cache["cfg"] = {"key": "stub-key-for-tests", "key_source": "test", "header": "X-Api-Key",
                                "regs_url": f"http://127.0.0.1:{srv.server_port}/regs"}
    api_config.RETRY_PAUSE = 0
    with tempfile.TemporaryDirectory() as tmp:
        code, out = call(["list"])
        res = json.loads(out)
        check(code is None and res["count"] == 6 and set(res["files"][0]) == {"path", "id", "modified_at", "size"}, "list: every file with path, id, date and size")
        code, out = call(["list", "--folder", ""])
        check([f["path"] for f in json.loads(out)["files"]] == [f["path"] for f in FILES[:3]], "list --folder \"\": only the root")
        code, out = call(["list", "--folder", "tier-a", "--name", "1006"])
        check([f["id"] for f in json.loads(out)["files"]] == ["ID-1006"], "list: folder and part of the name together")

        code, out = call(["index", "-o", tmp])
        res = json.loads(out)
        check(res["id"] == "ID-IDX-NEW" and Stub.seen[-1] == {"action": "download", "id": "ID-IDX-NEW"}, "index: the newest _INDEX_ file is the one downloaded")
        text = open(res["file"], encoding="utf-8").read()
        check(text.startswith("# _INDEX_") and res["bytes"] == len(text.encode()) and res["link"].endswith("/ID-IDX-NEW/view"),
              "the file is written as received; the answer carries its size and the Drive link")

        for what, want in (("ID-MAP", "ID-MAP"), ("_MAP_pg_sd.md", "ID-MAP"), ("tier-b/GDPBZN_Ordinance_8121з-1006_2026_Appendices.md", "ID-1006-APP"),
                           ("1006_2026.md", "ID-1006"), ("APPENDICES", "ID-1006-APP")):
            code, out = call(["get", what, "-o", tmp])
            check(code is None and json.loads(out)["id"] == want, f"get „{what}“ → one file")
        code, out = call(["get", "tier-a/GDPBZN_Ordinance_8121з-1006_2026.md", "-o", tmp])
        name = os.path.basename(json.loads(out)["file"])
        check("/" not in name and name.startswith("tier-a_") and os.path.dirname(json.loads(out)["file"]) == tmp,
              "the saved name keeps the folder in the name and cannot leave the output folder")

        before = len(Stub.seen)
        code, out = call(["get", "8121з-1006", "-o", tmp])
        check(str(code).startswith("AMBIGUOUS") and "tier-a/" in str(code) and "tier-b/" in str(code) and len(Stub.seen) == before + 1,
              "a name that fits several files lists them and downloads none")
        code, out = call(["get", "няма-такъв", "-o", tmp])
        check(str(code).startswith("NOT_FOUND"), "an unknown name is NOT_FOUND")
        code, out = call(["get", "8121з-282.pdf", "-o", tmp])
        check(str(code).startswith("UNSUPPORTED"), "a PDF original is UNSUPPORTED, not a server failure")

        Stub.fail = (200, {"oops": 1})
        code, out = call(["list"])
        check(str(code) == "N8N_UNAVAILABLE: unexpected response shape", "an unexpected answer is not taken for an empty base")
        Stub.fail = (500, {"message": "Error in workflow"})
        code, out = call(["list"])
        check(str(code).startswith("N8N_UNAVAILABLE: HTTP 500"), "a server failure is N8N_UNAVAILABLE")
        Stub.fail = (403, {"error": "UNAUTHORIZED"})
        code, out = call(["index", "-o", tmp])
        check(str(code).startswith("KEY_REJECTED") and "stub-key" not in str(code), "a rejected key is KEY_REJECTED, without printing it")
        Stub.fail = None
    srv.shutdown()
    print("\nALL PASS" if not failures else f"\n{len(failures)} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
