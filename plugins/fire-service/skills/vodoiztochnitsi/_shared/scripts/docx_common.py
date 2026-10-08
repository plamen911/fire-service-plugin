#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx_common.py — the typography rules and the final check shared by every script that builds a document
(_shared/conventions.md, т. 2): „№ 4“, the dash „–“, no bold, one letterhead.

    from docx_common import typo, typo_all, check_document, report

    typo("ул. Иван Вазов №4 - Плевен")        →  "ул. Иван Вазов № 4 – Плевен"
    typo_all(doc)                              applies typo() to the body, the headers and the footers
    check_document("out.docx")                 →  [] or a list of what breaks the rules
    report("out.docx")                         prints the problems to stderr (the builders call it after saving)

    python3 docx_common.py out.docx            # the same check from the command line; exit code 1 on a problem
"""
import re
import sys
import zipfile

NO_RE = re.compile(r"№\s*(?=\S)")          # „№4“ → „№ 4“
DASH_RE = re.compile(r"(^|\s)-(?=\s)")     # a lone „-“ between spaces → „–“
BOLD_RE = re.compile(r"<w:b(Cs)?[ /]|<b/>|<b val=\"(1|true)\"")
TAG_RE = re.compile(r"<[^>]+>")
LETTERHEAD = ("МИНИСТЕРСТВО НА ВЪТРЕШНИТЕ РАБОТИ",
              "ГЛАВНА ДИРЕКЦИЯ „ПОЖАРНА БЕЗОПАСНОСТ И ЗАЩИТА НА НАСЕЛЕНИЕТО”")
THIRD_LINE = re.compile(r"(РЕГИОНАЛНА ДИРЕКЦИЯ|РАЙОННА СЛУЖБА) „ПОЖАРНА БЕЗОПАСНОСТ И ЗАЩИТА НА НАСЕЛЕНИЕТО” – \S")


def typo(text, quotes=False):
    """„№ 4“; the dash is „–“ (never „-“ between spaces and never „—“). A hyphen inside words and numbers
    („1234р-56789“, „Бала-баир“) is left alone. With quotes=True the closing quote „”“ becomes „“ “."""
    text = NO_RE.sub("№ ", str(text)).replace("—", "–")
    if quotes:
        text = text.replace("”", "“")
    return DASH_RE.sub(lambda m: m.group(1) + "–", text)


def typo_all(doc, tag=None, quotes=False):
    """typo() over the whole python-docx document – body, text boxes, headers and footers."""
    if tag is None:
        from docx.oxml.ns import qn
        tag = qn("w:t")
    parts = [doc.element.body]
    for sec in doc.sections:
        for hf in (sec.header, sec.first_page_header, sec.even_page_header,
                   sec.footer, sec.first_page_footer, sec.even_page_footer):
            parts.append(hf._element)
    for part in parts:
        for t in part.iter(tag):
            if t.text:
                t.text = typo(t.text, quotes)


def _texts(path):
    """(part name, raw xml, plain text) for the parts of a .docx/.xlsx that carry text."""
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if re.match(r"word/(document|header\d*|footer\d*)\.xml$|xl/(sharedStrings|worksheets/sheet\d+)\.xml$", n):
                xml = z.read(n).decode("utf-8", "ignore")
                paras = re.split(r"</w:p>|</si>|</c>", xml)
                out.append((n, xml, [TAG_RE.sub("", p) for p in paras]))
    return out


def check_document(path, letterhead=True):
    """What in a finished document breaks the common rules. An empty list means it is fine."""
    problems = []
    body = ""
    for name, xml, paras in _texts(path):
        if BOLD_RE.search(xml):
            problems.append(f"получер шрифт в {name}")
        for p in paras:
            if "—" in p:
                problems.append(f"дълго тире „—“: …{p[max(0, p.find('—') - 20):p.find('—') + 20]}…")
            if DASH_RE.search(p) and p.strip() != "-":
                problems.append(f"„-“ между интервали вместо „–“: …{p.strip()[:50]}…")
            if re.search(r"№\S", p):
                problems.append(f"„№“ без интервал: …{p[max(0, p.find('№') - 15):p.find('№') + 15]}…")
            m = re.search(r"\{\{\w+\}\}", p)
            if m:
                problems.append(f"непопълнено поле: {m.group(0)}")
        if name == "word/document.xml":
            body = "".join(paras)
    if letterhead and path.lower().endswith(".docx"):
        for line in LETTERHEAD:
            if line not in body:
                problems.append(f"в шапката липсва ред „{line}“")
        if not THIRD_LINE.search(body):
            problems.append("третият ред на шапката не е изписан изцяло („РЕГИОНАЛНА ДИРЕКЦИЯ …“ / „РАЙОННА СЛУЖБА …“)")
    return sorted(set(problems))


def report(path, letterhead=True):
    """Print the problems of a finished document to stderr; returns them. Never stops the builder."""
    try:
        problems = check_document(path, letterhead)
    except Exception as e:  # noqa: BLE001  (the check must never break a finished document)
        print(f"DOC_CHECK: проверката не можа да се изпълни ({type(e).__name__})", file=sys.stderr)
        return []
    for p in problems:
        print(f"DOC_CHECK: {p}", file=sys.stderr)
    return problems


if __name__ == "__main__":
    bad = False
    for f in sys.argv[1:]:
        found = check_document(f, letterhead="--no-letterhead" not in sys.argv)
        bad = bad or bool(found)
        print(f"{'✗' if found else '✓'} {f}")
        for line in found:
            print("   ", line)
    sys.exit(1 if bad else 0)
