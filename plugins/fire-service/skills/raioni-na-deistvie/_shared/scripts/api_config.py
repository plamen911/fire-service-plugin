#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_config.py — адресите на n8n и личният ключ за скриптовете на fire-service.

В пакета няма ключ. Ключът се търси в този ред:
  1. променливата на средата FIRE_SERVICE_KEY;
  2. поле "key" в `_shared/incident_api.json` (лично копие на пакета; в общия пакет е празно);
  3. личен скил `fire-service-key` в акаунта на потребителя – в неговия SKILL.md има ред
     `key: fs_…` (и по желание редове с лични данни за документите – виж `profile()`).
FIRE_SERVICE_NO_KEY=1 изключва и трите (тестовете не пипат мрежата).

Няма ключ → скриптовете, които питат n8n, спират с `NO_KEY: …`. Това е нормалното състояние
при колега с конектора Fire Service: тогава данните идват от инструментите на конектора
(`_shared/connector.md`), не от скриптовете.

    python3 _shared/scripts/api_config.py        # казва има ли ключ и откъде е (никога самия ключ)
"""
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), "incident_api.json")
KEY_SKILL = "fire-service-key"
NO_KEY = ("NO_KEY: няма личен ключ за n8n – данните идват от инструментите на конектора Fire Service "
          "(виж _shared/connector.md)")
_cache = {}


def _key_skill_files():
    """SKILL.md of the personal skill `fire-service-key`, wherever this environment keeps user skills."""
    home = os.path.expanduser("~")
    patterns = [
        f"/mnt/skills/*/{KEY_SKILL}/SKILL.md", f"/mnt/skills/*/*/{KEY_SKILL}/SKILL.md",
        f"{home}/.claude/skills/{KEY_SKILL}/SKILL.md", f"{home}/.claude/skills/*/*/{KEY_SKILL}/SKILL.md",
    ]
    folder = HERE
    for _ in range(9):  # next to the plugin, whatever the install path is
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
        patterns += [f"{folder}/{KEY_SKILL}/SKILL.md", f"{folder}/skills/{KEY_SKILL}/SKILL.md",
                     f"{folder}/skills/*/*/{KEY_SKILL}/SKILL.md"]
    seen = []
    for p in patterns:
        for f in sorted(glob.glob(p)):
            if f not in seen:
                seen.append(f)
    return seen


def _key_skill():
    """{"key": …, "profile": {field: value}} from the personal skill, or {}."""
    if "skill" not in _cache:
        found = {}
        for path in _key_skill_files():
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            fields = dict(re.findall(r"^\s*([a-z_]+):\s*(\S.*?)\s*$", text.split("---", 2)[-1], re.M))
            if fields.get("key"):
                found = {"key": fields.pop("key"), "profile": fields, "path": path}
                break
        _cache["skill"] = found
    return _cache["skill"]


def load():
    """The endpoint addresses, the header name and the key ("" when there is none)."""
    if "cfg" not in _cache:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        key, source = os.environ.get("FIRE_SERVICE_KEY", "").strip(), "FIRE_SERVICE_KEY"
        if os.environ.get("FIRE_SERVICE_NO_KEY"):  # tests: never touch the network
            key = ""
        else:
            if not key:
                key, source = str(cfg.get("key") or "").strip(), "incident_api.json"
            if not key:
                key, source = _key_skill().get("key", ""), f"скил {KEY_SKILL}"
        cfg["key"], cfg["key_source"] = key, source if key else None
        cfg.setdefault("header", "X-Api-Key")
        _cache["cfg"] = cfg
    return _cache["cfg"]


def has_key():
    try:
        return bool(load()["key"])
    except (OSError, ValueError):
        return False


def profile():
    """Personal data for the documents written in the personal skill (overrides what the staff list gives)."""
    if os.environ.get("FIRE_SERVICE_NO_KEY"):  # tests: independent of the account they run in
        return {}
    return dict(_key_skill().get("profile") or {})


def write_private(path, text):
    """Write a cached copy of server data so that only its owner can read it (0600), never group or others."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)   # a file left by an older version keeps its old mode otherwise


def request(url_field, body, timeout=60):
    """A urllib Request for one of the endpoints; exits with NO_KEY when there is no key."""
    cfg = load()
    if not cfg["key"]:
        sys.exit(NO_KEY)
    if not cfg.get(url_field):
        sys.exit(f"N8N_UNAVAILABLE: в incident_api.json няма {url_field}")
    return urllib.request.Request(
        cfg[url_field], json.dumps(body, ensure_ascii=False).encode(),
        {"Content-Type": "application/json", cfg["header"]: cfg["key"]})


def post(url_field, body, timeout=60):
    """POST to an endpoint → parsed JSON. A rejected key ends with KEY_REJECTED; other HTTP errors are raised."""
    try:
        with urllib.request.urlopen(request(url_field, body), timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f"KEY_REJECTED: n8n не приема личния ключ (от {load()['key_source']}) – "
                     "провери реда `key:` в скила fire-service-key или поискай нов ключ от администратора.")
        raise


if __name__ == "__main__":
    c = load()
    print(json.dumps({"key": bool(c["key"]), "key_source": c["key_source"],
                      "profile_fields": sorted(profile())}, ensure_ascii=False))
