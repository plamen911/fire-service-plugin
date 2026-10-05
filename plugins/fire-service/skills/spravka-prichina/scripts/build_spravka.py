#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Изгражда СПРАВКА за установяване на причината за произшествие (.docx)
по официалната бланка на РСПБЗН (по подразбиране – Плевен; друга районна служба
се задава с полето "unit").

Употреба:
    python3 build_spravka.py data.json [-o изходен_файл.docx]

data.json (всички полета са низове, освен body_sections):
{
  "legal_basis": "new",              // "new" = чл. 20 ал. 3 / 8121з-1055/17.08.2021 (по подразбиране)
                                     // "old" = чл.21 ал.3 / Iз-2775/28.10.2011
  "unit": "ПЛЕВЕН",                  // районната служба в бланката и в адресата по подразбиране
  "addressee": ["ДО", "НАЧАЛНИКА НА", "РСПБЗН – ПЛЕВЕН", "ГЛАВЕН ИНСПЕКТОР", "ИМЕ ФАМИЛИЯ"],
                                     // по подразбиране от "unit" + званието и името на началника
                                     // от _shared/sluzhiteli (липсва ли – само първите три реда)
  "addressee_chief": true,           // false = без званието и името на началника
  "intro": "Днес, 01.08.2025 г., в гр.Плевен, ... и направения оглед установих следното:",
  "section1": ["абзац", "абзац"],    // Обстановка, предшествуваща произшествието
  "section2": ["абзац"],             // Обстановка по време на произшествието
  "section3": ["абзац", "абзац"],    // Обстоятелства и факти + заключителен абзац
  "signer_title": "инспектор IV ст.", // званието в реда под „ИЗГОТВИЛ:“ (spravka_izgotvil от профила):
                                     // „(инспектор IV ст. Иван Петров)“
  "signer_name": "Иван Петров",       // име и фамилия на съставителя (ime от профила)
  "city": "Плевен",                  // „гр. …“ долу вляво; по подразбиране от "unit"
  "reg_year": "2026"                 // годината в „.............2026 г.“; по подразбиране от датата в увода
}

Блокът „Рег. № ...................., екз. № ......“ се оставя с точки – попълва се на ръка
при регистриране.

Скриптът НЕ пише съдържание — само форматира подадения текст в бланката.
"""

import argparse
import copy
import datetime
import json
import os
import re
import sys

from docx import Document
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "template.docx")
MODEL = os.path.join(HERE, "..", "assets", "body_paragraph_model.xml")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

LEGAL = {
    "new": [
        "по чл. 20 ал. 3 от Правила за дейността на ГДПБЗН – МВР при регистриране и",
        "отчитане на възникналите пожари, бедствия и извънредни ситуации, утвърдени",
        "със заповед рег. № 8121з – 1055/17.08.2021 г. на главния секретар на МВР",
    ],
    "old": [
        "по чл.21 ал.3 от Правила за дейността на ГДПБЗН – МВР при регистриране и",
        "отчитане на възникналите пожари, бедствия и извънредни ситуации, утвърдени",
        "със заповед рег. № Iз – 2775/28.10.2011 г. на главния секретар на МВР",
    ],
}

HEADINGS = [
    "1. Обстановка, предшествуваща произшествието:",
    "2. Обстановка по време на произшествието:",
    "3. Обстоятелства и факти, позволяващи да се установи вероятната причина за пожара:",
]


NO_RE = re.compile(r"№\s*(?=\S)")   # „№4“ → „№ 4“ (_shared/conventions.md)


DASH_RE = re.compile(r"(^|\s)-(?=\s)")   # самостоятелно „-“ между интервали → „–“

def typo(text):
    """Типографски правила от _shared/conventions.md: „№ 4“; тирето е „–“ (не „-“ и не „—“).
    Дефисът в думи и номера („1234р-56789“, „Бала-баир“) не се пипа."""
    text = NO_RE.sub("№ ", text).replace("—", "–")
    return DASH_RE.sub(lambda m: m.group(1) + "–", text)


def typo_all(doc, tag):
    """Прилага typo() върху целия документ — тяло, текстови полета, колонтитули."""
    parts = [doc.element.body]
    for sec in doc.sections:
        for hf in (sec.header, sec.first_page_header, sec.even_page_header,
                   sec.footer, sec.first_page_footer, sec.even_page_footer):
            parts.append(hf._element)
    for part in parts:
        for t in part.iter(tag):
            if t.text:
                t.text = typo(t.text)


def set_paragraph_text(p, text):
    """Оставя само първия run в параграфа и му задава новия текст,
    за да се запази оригиналното форматиране (шрифт, размер, отстъп)."""
    runs = p.findall(W + "r")
    if not runs:
        return
    for r in runs[1:]:
        p.remove(r)
    keep = runs[0]
    for t in keep.findall(W + "t"):
        keep.remove(t)
    t = etree.SubElement(keep, W + "t")
    t.text = typo(text)
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def make_body_paragraph(model_xml, text):
    p = copy.deepcopy(model_xml)
    set_paragraph_text(p, text)
    return p


def fill_column(table, col, values):
    """Writes values top-down into column `col` of the table (one per row), keeping the
    formatting of the run that is already there. Empty cells are left untouched."""
    idx = 0
    for row in table.rows:
        if idx >= len(values):
            break
        cell = row.cells[col]
        for p in cell.paragraphs:
            if p.text.strip():
                set_paragraph_text(p._p, values[idx])
                idx += 1
                break


# abbreviations that stay in capitals when an upper-case title is turned to lower case
ABBR = {"РСПБЗН", "РДПБЗН", "УПБЗН", "ГДПБЗН", "МВР", "ВПД", "ОЦ", "ПГ", "СД", "ДПК", "ПД"}
ROMAN_RE = re.compile(r"^[IVXІ]+$")


def title_lower(title):
    """Upper-case title → lower case for the line under „ИЗГОТВИЛ:“
    („ИНСПЕКТОР IV СТ.“ → „инспектор IV ст.“).
    A title that already has lower-case letters outside the quotes is returned unchanged.
    Text in quotes, abbreviations and Roman numerals keep their case; a place name after
    the dash is capitalised („НАЧАЛНИК НА РСПБЗН – ЛЕВСКИ“ → „началник на РСПБЗН – Левски“)."""
    title = title.strip()
    outside = re.sub(r"[„“\"][^„“”\"]*[”“\"]", "", title)
    if outside != outside.upper():
        return title
    head, dash, place = title.partition(" – ")
    parts = re.split(r"([„“\"][^„“”\"]*[”“\"])", head)
    for i in range(0, len(parts), 2):
        parts[i] = " ".join(w if w in ABBR or ROMAN_RE.match(w) else w.lower()
                            for w in parts[i].split(" "))
    return "".join(parts) + (dash + place.title() if dash else "")


def chief_lines(unit):
    """[ЗВАНИЕ, ИМЕ] на началника на РСПБЗН – {unit} от таблицата със служителите."""
    import importlib.util
    path = os.path.join(HERE, "..", "_shared", "scripts", "sluzhiteli.py")
    if not os.path.exists(path):
        return []
    spec = importlib.util.spec_from_file_location("sluzhiteli", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    c = mod.nachalnik(unit)
    if not c or not c["ime"]:
        return []
    lines = [c["zvanie"].upper()] if c["zvanie"] else []
    return lines + [c["ime"].upper()]


def fit_rows(table, n):
    """Добавя редове (копие на последния), докато таблицата стане поне n реда."""
    while len(table.rows) < n:
        tr = copy.deepcopy(table.rows[-1]._tr)
        table._tbl.append(tr)


def build(data, out_path):
    doc = Document(TEMPLATE)
    body = doc.element.body
    model_xml = etree.parse(MODEL).getroot()

    # --- правно основание (параграфи 6,7,8 в шаблона) ---
    basis = LEGAL.get(data.get("legal_basis", "new"), LEGAL["new"])
    paras = [ch for ch in body if ch.tag == W + "p"]
    # намираме реда по характерния текст
    for p in paras:
        txt = "".join(p.itertext())
        if txt.startswith("по чл"):
            set_paragraph_text(p, basis[0])
        elif txt.startswith("отчитане на възникналите"):
            set_paragraph_text(p, basis[1])
        elif txt.startswith("със заповед"):
            set_paragraph_text(p, basis[2])

    # --- районна служба в бланката ---
    unit = (data.get("unit") or "ПЛЕВЕН").strip().upper()
    # заглавието е в текстово поле (mc:AlternateContent – Choice + Fallback),
    # затова се сменя текстът във всеки w:t, без да се пипа структурата
    prefix = "РАЙОННА СЛУЖБА „ПОЖАРНА БЕЗОПАСНОСТ И ЗАЩИТА НА НАСЕЛЕНИЕТО” – "
    for t in body.iter(W + "t"):
        if t.text and t.text.startswith(prefix):
            t.text = prefix + unit
            if len(unit) > 8:   # a long name ("ДОЛНА МИТРОПОЛИЯ") must still fit on one line
                rpr = t.getparent().find(W + "rPr")
                for el in rpr.iter(W + "sz", W + "szCs"):
                    el.set(W + "val", "21" if len(unit) > 12 else "22")

    # --- адресат ---
    addressee = data.get("addressee")
    if not addressee:
        addressee = ["ДО", "НАЧАЛНИКА НА", f"РСПБЗН – {unit}"]
        if data.get("addressee_chief", True):
            addressee += chief_lines(unit)
    fit_rows(doc.tables[1], len(addressee))
    fill_column(doc.tables[1], 1, addressee)

    # --- рег. № (лявата колона на адресата): само годината се попълва ---
    m = re.search(r"\b\d{1,2}\.\d{1,2}\.(\d{4})", data.get("intro", ""))
    year = str(data.get("reg_year") or (m.group(1) if m else datetime.date.today().year))
    fill_column(doc.tables[1], 0, ["Рег. № ...................., екз. № ......",
                                  f".............{year} г."])

    # --- „гр. …“ и „ИЗГОТВИЛ:“ ---
    city = (data.get("city") or unit.title()).strip()
    fill_column(doc.tables[2], 0, [f"гр. {city}"])
    # „ИЗГОТВИЛ:“ (with the tabs that leave room for the signature) is fixed text in the
    # template, on the same line as the place; only the line under it is filled in
    signer = "{} {}".format(title_lower(data.get("signer_title", "[звание]")),
                            data.get("signer_name", "[Име Фамилия]")).strip()
    set_paragraph_text(doc.tables[2].rows[1].cells[1].paragraphs[0]._p, f"({signer})")

    # --- тяло ---
    # празният параграф между заглавния блок и таблицата с подписа е котвата
    anchor = None
    children = list(body)
    tbl_sign = doc.tables[2]._tbl
    sign_pos = children.index(tbl_sign)
    for ch in reversed(children[:sign_pos]):
        if ch.tag == W + "p":
            anchor = ch
            break

    lines = [data["intro"]]
    for i, key in enumerate(("section1", "section2", "section3")):
        lines.append(HEADINGS[i])
        lines.extend(data.get(key) or [])

    for text in lines:
        anchor.addprevious(make_body_paragraph(model_xml, text))

    typo_all(doc, W + "t")
    doc.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as fh:
        data = json.load(fh)

    out = args.out or os.path.splitext(args.data)[0] + ".docx"
    build(data, out)
    print(out)


if __name__ == "__main__":
    sys.exit(main())
