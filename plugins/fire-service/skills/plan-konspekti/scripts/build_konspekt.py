#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_konspekt.py — изгражда ПЛАН-КОНСПЕКТ за провеждане на занятие като .docx на бланката на
РДПБЗН – Плевен: шапка, „УТВЪРЖДАВАМ“, тема/цел/метод/време/място, изложение (с подзаглавия,
цитати от актове и фигури) и „ИЗГОТВИЛ“.

    python3 scripts/build_konspekt.py data.json -o /mnt/user-data/outputs/Plan-konspekt_....docx

Два вида (поле "kind"):
  "oc"       занятие на инспекторите от група „Оперативен център“ по годишния план-график –
             ТЕМА 1 (лекция, с изложение) и ТЕМА 2 (практика – упражнение от методиката по ППС);
  "seminar"  семинар / професионално обучение по месторабота – една тема, полета I–VI.

data.json (всичко извън "kind", "tema", "tsel" и "izlozhenie" има стойност по подразбиране):
{
  "kind": "oc",
  "year": "2026",
  "approver": {"lines": ["ДИРЕКТОР НА", "РДПБЗН – ПЛЕВЕН:", "КОМИСАР"], "name": "Име Фамилия",
               "zamestvane": "Съгласно заповед за заместване № …"},   // по подразбиране – директорът от списъка
  "plan_grafik": "рег. № 947р-0000/15.12.2025 г.",                  // "oc": номерът на план-графика
  "subtitle": ["за провеждане на …", "…"],                          // "seminar": редовете под заглавието
  "reg": true,                                                       // редове „Рег. № …, екз. № …“ вляво
  "tema": "Гасене на пожари в житни масиви",
  "tsel": "Опресняване на знанията на служителите за …",
  "metod": "лекция",
  "data": "27.10.2026 г.",                                           // датата на занятието
  "vreme": "1 учебен час на 27.10.2026 г.",                          // по подразбиране – от "data"
  "zvena": ["РСПБЗН – Червен бряг", "РСПБЗН – Кнежа"],              // "oc": от тях се образуват място и участващи
  "myasto": "…", "uchastvashti": "…",                               // ако трябва друг текст
  "materialno": ["Наредба № 8121з-1006 от 24.08.2015 г. за …", "…"],
  "izlozhenie": [
    "## 1. Причини за възникване",                                   // подзаглавие (на отделен ред, без получер)
    "Обикновен абзац със свои думи. *Курсив* (име на възел, термин) се огражда със звездички.",
    "> Чл. 42. При гасене на пожар в посеви … РОД е необходимо да:", // дословен цитат от акт (курсив)
    "- първа точка от изброяване",
    {"fig": "fig/s02.png", "caption": "Фиг. 1. Булин", "height_cm": 4.5},   // фигура, центрирана, с надпис
    {"figs": ["a.png", "b.png"], "caption": "Фиг. 2. …", "height_cm": 4}   // няколко изображения в един ред
  ],
  "tema2": {"uprazhnenie": "1.1"},                                   // "oc": упражнение от data/uprazhneniya.json
        // или изцяло свой текст: {"tekst": "…", "tsel_uvod": "…", "tsel": ["…"], "materialno": "…"}
        // по желание: "opisanie": true – описанието, скалата за резултата и забележката от методиката;
        //             или "opisanie": ["свой ред", …]
  "izgotvil": {"date": "20.10.2026 г.", "lines": ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"],
               "name": "инспектор Иван Петров"}
}

Пътищата на фигурите са спрямо папката на data.json. Типографията следва _shared/conventions.md:
„№ 4“, тире „–“ и НИКАКЪВ получер шрифт – подзаглавията и етикетите са обикновен текст. Скриптът отпечатва JSON {"output", "kind", "znatsi_izlozhenie", "figuri", "preduprezhdeniya"}.

Грешки (на stderr, код ≠ 0):
    BAD_INPUT: ...   — липсва задължително поле, непознат вид или упражнение, няма го файлът на фигура
"""
import argparse
import json
import os
import sys

from docx.shared import Cm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blanka as B  # noqa: E402

DATA = os.path.join(HERE, "..", "data", "uprazhneniya.json")
OC_SUBTITLE = ["за провеждане на занятие съгласно план–график, {plan_grafik},",
               "за провеждане на занятията от инспекторите в група „Оперативен център“",
               "на сектор „Пожарогасителна и спасителна дейност“ през {year} г."]
SEMINAR_SUBTITLE = ["за провеждане на професионално обучение по месторабота през {year} година",
                    "на държавните служители на изпълнителски и ръководни длъжности от РДПБЗН – Плевен"]
UCHASTVASHTI = ("държавни служители, заемащи младши изпълнителски длъжности от направление "
                "„Пожарогасителна и спасителна дейност“ в {zvena}")
OC_SIGN = ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"]
MAX_FIG_WIDTH_CM = 16.0


def bad(msg):
    sys.exit(f"BAD_INPUT: {msg}")


def exercises():
    with open(DATA, encoding="utf-8") as f:
        d = json.load(f)

    def deref(v):
        return d[v[1:]] if isinstance(v, str) and v.startswith("@") else v
    for ex in d["uprazhneniya"].values():
        for key in ("tsel_uvod", "tsel", "materialno"):
            ex[key] = deref(ex[key])
    return d


def exercise_text(number, ex, metodika):
    return f"Проиграване на Упражнение № {number} „{ex['ime']}“ от {metodika}."


def norm_text(ex):
    """„6 точки ≤ 65 секунди; …; 0 точки > 80 секунди“ or „най-много 6 точки по картата …“."""
    if ex.get("normativ"):
        steps = sorted(ex["normativ"], key=lambda s: s["do_sek"])
        return "; ".join(f"{s['tochki']} точки ≤ {s['do_sek']} секунди" for s in steps) + f"; 0 точки > {steps[-1]['do_sek']} секунди"
    if ex.get("max_tochki"):
        return f"до {ex['max_tochki']} точки по картата за отчитане на резултатите"
    return ""


def exercise_description(number, ex):
    """The exercise as the methodology describes it: numbered steps, the result scale, the note."""
    if not ex or not ex.get("opisanie"):
        return []
    lines = [f"Упражнение № {number} „{ex['ime']}“"] + [f"{i}. {t}" for i, t in enumerate(ex["opisanie"], 1)]
    if norm_text(ex):
        lines.append("Резултат: " + norm_text(ex) + ".")
    if ex.get("zabelezhka"):
        lines.append("Забележка: " + ex["zabelezhka"])
    return lines


def field(doc, label, value, roman=None):
    label = f"{roman}. {label}" if roman else label
    B.para(doc, f"{label}: {value}")


def field_list(doc, label, items, roman=None):
    """A field whose value is one line or a bulleted list."""
    items = [items] if isinstance(items, str) else [i for i in items if str(i).strip()]
    if len(items) <= 1:
        return field(doc, label, items[0] if items else "", roman)
    field(doc, label, "", roman)
    for it in items:
        B.para(doc, "– " + it.rstrip(";. ") + (";" if it is not items[-1] else "."))


def figure(doc, item, base, warnings):
    from PIL import Image
    paths = item.get("figs") or [item.get("fig")]
    paths = [p if os.path.isabs(p) else os.path.join(base, p) for p in paths if p]
    if not paths:
        bad("фигура без файл (fig или figs)")
    for p in paths:
        if not os.path.isfile(p):
            bad(f"няма го файлът на фигурата: {p}")
    height = float(item.get("height_cm") or 4.5)
    ratios = []
    for p in paths:
        with Image.open(p) as im:
            ratios.append(im.width / im.height)
    gap = 0.4 * (len(paths) - 1)
    if sum(ratios) * height + gap > MAX_FIG_WIDTH_CM:        # the row must fit the text width
        height = (MAX_FIG_WIDTH_CM - gap) / sum(ratios)
        warnings.append(f"фигурата „{item.get('caption', paths[0])}“ е намалена до височина {height:.1f} см, за да се побере")
    par = B.fmt(doc.add_paragraph(), B.CENTER, line=None, keep=bool(item.get("caption")))
    par.paragraph_format.space_before = B.Pt(6)
    for i, p in enumerate(paths):
        if i:
            par.add_run("  ")
        par.add_run().add_picture(p, height=Cm(height))
    if item.get("caption"):
        cap = B.para(doc, item["caption"], align=B.CENTER, indent=False, italic=True, size=11, line=None)
        cap.paragraph_format.space_after = B.Pt(6)


def exposition(doc, items, base, warnings):
    """→ (characters of text, number of figures). A paragraph stays on the page of the figure after it."""
    chars = figs = 0
    for i, it in enumerate(items):
        if isinstance(it, dict):
            figure(doc, it, base, warnings)
            figs += 1
            continue
        text = str(it).strip()
        keep = i + 1 < len(items) and isinstance(items[i + 1], dict)
        if not text:
            B.blank(doc)
        elif text.startswith("## "):
            p = B.para(doc, text[3:], keep=True)
            p.paragraph_format.space_before = B.Pt(6)
        elif text.startswith("> "):
            B.para(doc, text[2:], italic=True, keep=keep)
        elif text.startswith("- "):
            B.para(doc, "– " + text[2:], keep=keep)
        else:
            B.para(doc, text, keep=keep)
        chars += len(text)
    return chars, figs


def build(d, out, base):
    kind = d.get("kind")
    if kind not in ("oc", "seminar"):
        bad('"kind" трябва да е "oc" или "seminar"')
    for k in ("tema", "tsel"):
        if not str(d.get(k) or "").strip():
            bad(f'липсва "{k}"')
    warnings = []
    date = str(d.get("data") or "").strip()
    year = str(d.get("year") or (date[6:10] if len(date) >= 10 else "")).strip()
    if not year:
        bad('липсва "year" (или "data" във вид ДД.ММ.ГГГГ г.)')
    zvena = B.join_units(d.get("zvena") or [])
    vreme = d.get("vreme") or (f"1 учебен час на {date}" if date else "1 учебен час на …………… г.")
    approver = d.get("approver") or B.director_approver()
    if B.PLACEHOLDER_NAME in (approver.get("name") or B.PLACEHOLDER_NAME):
        warnings.append("няма данни за утвърждаващия – подай \"approver\"")
    sign = dict(d.get("izgotvil") or {})
    if not sign.get("name"):
        warnings.append("няма данни за изготвилия – подай \"izgotvil\"")
    materialno = d.get("materialno") or []
    if not materialno:
        warnings.append("празно „Материално осигуряване“")
    items = d.get("izlozhenie") or []
    if not items:
        warnings.append("няма изложение – план-конспектът трябва да носи текста на занятието")

    doc = B.new_document()
    B.letterhead(doc)
    B.approval(doc, approver, year, reg=bool(d.get("reg", kind == "seminar")))

    if kind == "oc":
        if not d.get("plan_grafik"):
            warnings.append("липсва номерът на план-графика (\"plan_grafik\")")
        subtitle = [s.format(plan_grafik=d.get("plan_grafik") or "рег. № ……………", year=year) for s in OC_SUBTITLE]
        B.title(doc, "ПЛАН–КОНСПЕКТ", d.get("subtitle") or subtitle)
        if not zvena and not (d.get("myasto") and d.get("uchastvashti")):
            bad('за вид "oc" трябват "zvena" (или "myasto" и "uchastvashti")')
        many = len(d.get("zvena") or []) > 1
        place = d.get("myasto") or (("Сградите на " if many else "Сградата на ") + zvena)
        people = d.get("uchastvashti") or UCHASTVASHTI.format(zvena=zvena)
        field(doc, "ТЕМА 1", f"„{d['tema'].strip().rstrip('.')}.“")
        field(doc, "ЦЕЛ", d["tsel"])
        field(doc, "МЕТОД", (d.get("metod") or "лекция") + ";")
        field(doc, "ВРЕМЕ", vreme.rstrip(";") + ";")
        field(doc, "МЯСТО", place.rstrip(";") + ";")
        field(doc, "УЧАСТВАЩИ", people.rstrip(";") + ";")
        field_list(doc, "МАТЕРИАЛНО ОСИГУРЯВАНЕ", materialno)
        B.blank(doc)
        chars, figs = exposition(doc, items, base, warnings)
        B.blank(doc)

        t2 = dict(d.get("tema2") or {})
        ex_data = exercises()
        number = t2.get("uprazhnenie") or (None if t2.get("tekst") else ex_data["po_podrazbirane"])
        ex = {}
        if number:
            ex = ex_data["uprazhneniya"].get(number)
            if ex is None:
                bad(f"няма упражнение „{number}“ в data/uprazhneniya.json – налични: "
                    + ", ".join(ex_data["uprazhneniya"]) + '; подай "tema2" със свой текст ("tekst", "tsel")')
        text2 = t2.get("tekst") or exercise_text(number, ex, ex_data["metodika"])
        field(doc, "ТЕМА 2", text2)
        goals = t2.get("tsel") or ex.get("tsel") or []
        field(doc, "ЦЕЛ", t2.get("tsel_uvod") or ex.get("tsel_uvod") or "")
        for g in goals:
            B.para(doc, "– " + g)
        field(doc, "МЕТОД", "практически;")
        field(doc, "ВРЕМЕ", (t2.get("vreme") or vreme).rstrip(";") + ";")
        field(doc, "МЯСТО", (t2.get("myasto") or place.rstrip(";") + (" или прилежащи към тях площи" if many else " или прилежащи към нея площи")) + ";")
        field(doc, "УЧАСТВАЩИ", (t2.get("uchastvashti") or people).rstrip(";.") + ".")
        field(doc, "МАТЕРИАЛНО ОСИГУРЯВАНЕ", t2.get("materialno") or ex.get("materialno") or "")
        lines = t2.get("opisanie")
        if lines is True:                                   # the description from the methodology
            lines = exercise_description(number, ex)
        if lines:
            B.blank(doc)
            for line in lines:
                B.para(doc, line)
    else:
        subtitle = [s.format(year=year) for s in SEMINAR_SUBTITLE]
        B.title(doc, "ПЛАН–КОНСПЕКТ", d.get("subtitle") or subtitle)
        field(doc, "Тема", d["tema"].strip().rstrip(".") + ".", "I")
        field(doc, "Цел", d["tsel"], "II")
        field(doc, "Метод", (d.get("metod") or "Лекция").rstrip(".") + ".", "III")
        field(doc, "Място", (d.get("myasto") or "Учебен кабинет в сградата на РДПБЗН – Плевен").rstrip(".") + ".", "IV")
        field(doc, "Време", vreme.rstrip(".") + ".", "V")
        roman = "VI"
        if d.get("uchastvashti"):
            field(doc, "Участващи", d["uchastvashti"].rstrip(".") + ".", "VI")
            roman = "VII"
        field_list(doc, "Материално осигуряване", materialno, roman)
        B.blank(doc)
        chars, figs = exposition(doc, items, base, warnings)

    B.blank(doc)
    B.signature(doc, sign.get("date") or "", sign.get("lines") or OC_SIGN, sign.get("name") or B.PLACEHOLDER_NAME)
    B.page_numbers(doc)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    doc.save(out)
    return {"output": out, "kind": kind, "znatsi_izlozhenie": chars, "figuri": figs, "preduprezhdeniya": warnings}


def main():
    ap = argparse.ArgumentParser(description="План-конспект за занятие (.docx)")
    ap.add_argument("data", help="data.json")
    ap.add_argument("-o", "--output", required=True, help="изходен .docx")
    a = ap.parse_args()
    try:
        with open(a.data, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        bad(f"data.json не се чете: {e}")
    print(json.dumps(build(d, a.output, os.path.dirname(os.path.abspath(a.data))), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
