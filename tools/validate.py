#!/usr/bin/env python3
"""
validate.py — проверява репозиторито преди push (и в CI).

    python3 tools/validate.py            # всички проверки + тестовете на скиловете
    python3 tools/validate.py --no-tests # без тестовете
    python3 tools/validate.py --live     # и със сверка със списъка на служителите от n8n (иска личен ключ)

Без --live проверката не пипа мрежата: личният ключ не се търси и нищо не се сваля от сървъра.

Проверява:
  • marketplace.json и plugin.json са валиден JSON и имената съвпадат;
  • всеки скил има SKILL.md с front-matter (name = име на папката, description ≤ 1024 знака)
    и задължителните раздели от templates/SKILL_TEMPLATE.md;
  • всеки SKILL.md сочи към _shared/conventions.md;
  • файловете, споменати в SKILL.md като `references/…`, `assets/…`, `scripts/…`, `_shared/…`,
    съществуват;
  • _shared/ копията са синхронизирани с plugins/fire-service/shared/;
  • всички .py се компилират; няма очевидни пароли/токени;
  • в хранилището няма лични данни и тайни (tools/check_public.py) – то е публично;
  • в шаблоните на документите няма получер шрифт;
  • шапката в шаблоните е еднаква (shared/conventions.md, „Шапката“);
  • тестовете в skills/*/tests/ минават.
"""
import argparse
import glob
import json
import os
import py_compile
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "fire-service")
SKILLS = os.path.join(PLUGIN, "skills")
REQUIRED = ["## Какво е и кога", "## Преди да започнеш", "## Входни данни", "## Работен поток",
            "## Изход", "## Правила за съдържанието", "## Известни ограничения"]
SECRET = re.compile(r'("password"\s*:\s*"[^"]+")|(ghp_[A-Za-z0-9]{20,})|(github_pat_[A-Za-z0-9_]{20,})'
                    r'|(\bfs_[0-9a-f]{16,})|([?&]key=[A-Za-z0-9_-]{8,})')
errors = []


def err(msg):
    errors.append(msg)
    print("✗", msg)


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fm, key = {}, None
    for line in m.group(1).splitlines():
        km = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if km:
            key = km.group(1)
            fm[key] = km.group(2).strip().strip('"')
            if fm[key] in (">-", ">", "|"):
                fm[key] = ""
        elif key:
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm


def check_manifests():
    try:
        mk = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
        pl = json.load(open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return err(f"manifest JSON: {e}")
    names = [p["name"] for p in mk.get("plugins", [])]
    if pl.get("name") not in names:
        err(f"plugin.json name '{pl.get('name')}' not listed in marketplace.json {names}")
    for p in mk.get("plugins", []):
        if not os.path.isdir(os.path.join(ROOT, p["source"])):
            err(f"marketplace source missing: {p['source']}")
    print("✓ manifests")


def check_skill(d):
    name = os.path.basename(d)
    p = os.path.join(d, "SKILL.md")
    if not os.path.isfile(p):
        return err(f"{name}: SKILL.md missing")
    text = open(p, encoding="utf-8").read()
    fm = frontmatter(text)
    if not fm:
        return err(f"{name}: no front-matter")
    if fm.get("name") != name:
        err(f"{name}: front-matter name '{fm.get('name')}' ≠ folder name")
    desc = fm.get("description", "")
    if not desc:
        err(f"{name}: empty description")
    elif len(desc) > 1024:
        err(f"{name}: description is {len(desc)} chars (max 1024)")
    for h in REQUIRED:
        if not re.search("^" + re.escape(h), text, re.M):
            err(f"{name}: missing section '{h}'")
    if "_shared/conventions.md" not in text:
        err(f"{name}: does not point to _shared/conventions.md")
    for ref in set(re.findall(r"`((?:references|assets|scripts|_shared|tests)/[^`\s*{}<>]+)`", text)):
        if not os.path.exists(os.path.join(d, ref.rstrip("/"))):
            err(f"{name}: referenced path not found: {ref}")
    print(f"✓ {name}: SKILL.md ({len(desc)}-char description)")


def check_python():
    bad = 0
    for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            bad += 1
            err(f"py_compile: {e.msg}")
    print(f"✓ python compiles" if not bad else f"✗ {bad} python files fail")


def check_secrets():
    for f in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True):
        if os.path.isfile(f) and f.endswith((".md", ".py", ".json", ".yml", ".txt")):
            if SECRET.search(open(f, encoding="utf-8", errors="ignore").read()):
                err(f"possible secret in {os.path.relpath(f, ROOT)}")
    # the key is personal and never lives in the package: the field must be empty in every copy of the settings
    for f in glob.glob(os.path.join(PLUGIN, "**", "incident_api.json"), recursive=True):
        try:
            if json.load(open(f, encoding="utf-8")).get("key"):
                err(f"a key is written in {os.path.relpath(f, ROOT)} – the field must stay empty")
        except ValueError as e:
            err(f"{os.path.relpath(f, ROOT)}: {e}")
    print("✓ secret scan")


def check_no_bold():
    """No bold in the templates of the documents (a rule of the directorate – shared/conventions.md)."""
    import zipfile
    rx = re.compile(r"<w:b(Cs)?[ /]|<b/>|<b val=\"(1|true)\"")
    bad = 0
    for f in glob.glob(os.path.join(SKILLS, "*", "assets", "*.docx")) + glob.glob(os.path.join(SKILLS, "*", "assets", "*.xlsx")) \
            + glob.glob(os.path.join(SKILLS, "*", "assets", "*.xml")):
        if f.endswith(".xml"):
            texts = [open(f, encoding="utf-8").read()]
        else:
            with zipfile.ZipFile(f) as z:
                texts = [z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml")]
        if any(rx.search(t) for t in texts):
            bad += 1
            err(f"bold text in a template: {os.path.relpath(f, ROOT)}")
    if not bad:
        print("✓ no bold in the templates")


LETTERHEAD = [("МИНИСТЕРСТВО НА ВЪТРЕШНИТЕ РАБОТИ", "28", "32"),
              ("ГЛАВНА ДИРЕКЦИЯ „ПОЖАРНА БЕЗОПАСНОСТ И ЗАЩИТА НА НАСЕЛЕНИЕТО”", "28", "-16"),
              ("„ПОЖАРНА БЕЗОПАСНОСТ И ЗАЩИТА НА НАСЕЛЕНИЕТО” – ПЛЕВЕН", "24", "-16")]


def check_letterhead():
    """The letterhead is the same in every .docx template: three lines, their sizes and character
    spacing, a 10188 dxa table with a bottom rule (shared/conventions.md)."""
    import zipfile
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    from xml.etree import ElementTree as ET
    bad = 0
    for f in sorted(glob.glob(os.path.join(SKILLS, "*", "assets", "*.docx"))):
        rel = os.path.relpath(f, ROOT)
        with zipfile.ZipFile(f) as z:
            body = ET.fromstring(z.read("word/document.xml")).find(w + "body")
        first = body[0] if len(body) else None
        if first is None or first.tag != w + "tbl":
            continue                                      # a template without a letterhead
        paras = [p for p in first.iter(w + "p") if "".join(p.itertext()).strip()]
        if not paras or "".join(paras[0].itertext()).strip() != LETTERHEAD[0][0]:
            continue
        problems = []
        if len(paras) != 3:
            problems.append(f"{len(paras)} lines instead of 3")
        for p, (text, size, spacing) in zip(paras, LETTERHEAD):
            got = "".join(p.itertext()).strip()
            if not got.endswith(text):
                problems.append(f"line „{got}“")
            sizes = {e.get(w + "val") for e in p.iter(w + "sz")}
            spacings = {e.get(w + "val") for r in p.iter(w + "r") for e in r.iter(w + "spacing")}
            if sizes != {size} or spacings != {spacing}:
                problems.append(f"„{got[:24]}…“: sz {sorted(sizes)} spacing {sorted(spacings)}, expected {size}/{spacing}")
        width = first.find(w + "tblPr/" + w + "tblW")
        if width is None or width.get(w + "w") != "10188":
            problems.append("table width is not 10188 dxa")
        if first.find(w + "tblPr/" + w + "tblBorders/" + w + "bottom") is None:
            problems.append("no rule under the letterhead")
        for msg in problems:
            bad += 1
            err(f"letterhead in {rel}: {msg}")
    if not bad:
        print("✓ one letterhead in the templates")



def run_tests():
    for t in sorted(glob.glob(os.path.join(SKILLS, "*", "tests", "test_*.py"))):
        r = subprocess.run([sys.executable, t], cwd=os.path.dirname(os.path.dirname(t)),
                           capture_output=True, text=True,
                           env=dict(os.environ, FIRE_SERVICE_NO_KEY="1"))
        rel = os.path.relpath(t, ROOT)
        if r.returncode:
            err(f"test failed: {rel}\n{r.stdout[-1500:]}{r.stderr[-1500:]}")
        else:
            print(f"✓ {rel}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--live", action="store_true", help="сверка и със списъка на служителите от n8n (иска личен ключ)")
    a = ap.parse_args()
    env = dict(os.environ) if a.live else dict(os.environ, FIRE_SERVICE_NO_KEY="1")
    check_manifests()
    for d in sorted(glob.glob(os.path.join(SKILLS, "*"))):
        if os.path.isdir(d):
            check_skill(d)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sync_shared.py"), "--check"],
                       capture_output=True, text=True, env=env)
    (print("✓ _shared in sync") if r.returncode == 0 else err(r.stdout.strip()))
    # the repository is public: no personal data, no secrets
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_public.py")], capture_output=True, text=True, env=env)
    (print(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else err("public check:\n" + r.stdout.strip()[-3000:]))
    check_python()
    check_secrets()
    check_no_bold()
    check_letterhead()
    if not a.no_tests:
        run_tests()
    print()
    if errors:
        print(f"FAILED — {len(errors)} problem(s)")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
