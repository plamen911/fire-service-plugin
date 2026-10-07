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
  "seminar"  семинар / професионално обучение по месторабота – една тема, полета I–VI;
  "psp"      занятие по пожаро-строева подготовка с дежурните смени – по образеца от Приложение № 4
             на Специализираната методика по ПСП (заповед № 8121з-1702/09.12.2022 г.): тема, цел,
             място, участващи, материално-техническо осигуряване, мерки за безопасност и здраве,
             таблица „Организация и ход на занятието“ и таблица за провежданията през годината.

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
  "zaglavie_izlozhenie": "ИЗЛОЖЕНИЕ НА УЧЕБНИЯ МАТЕРИАЛ",          // заглавието пред изложението (по подразбиране това)
  "izlozhenie": [
    "## 1. Причини за възникване",                                   // подзаглавие (на отделен ред, без получер)
    "Обикновен абзац със свои думи. *Курсив* (име на възел, термин) се огражда със звездички.",
    "> Чл. 42. При гасене на пожар в посеви … РОД е необходимо да:", // дословен цитат от акт (курсив)
    "- първа точка от изброяване",
    {"fig": "fig/s02.png", "caption": "Фиг. 1. Булин", "height_cm": 4.5},   // фигура, центрирана, с надпис
    {"figs": ["a.png", "b.png"], "caption": "Фиг. 2. …", "height_cm": 4}   // няколко изображения в един ред
  ],
  "tema2": {"uprazhnenie": "1.1"},                                   // "oc": упражнение от методиката (scripts/uprazhneniya.py)
        // или изцяло свой текст: {"tekst": "…", "tsel_uvod": "…", "tsel": ["…"], "materialno": "…"}
        // по желание: "opisanie": true – описанието, скалата за резултата и забележката от методиката;
        //             или "opisanie": ["свой ред", …]
  "izgotvil": {"date": "20.10.2026 г.", "lines": ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"],
               "name": "инспектор Иван Петров"}
}

За "psp" (останалите полета – както по-горе; "izlozhenie" не се ползва):
{
  "kind": "psp",
  "year": "2026",
  "zveno": "РСПБЗН – Левски",                      // звеното; началникът му утвърждава (от списъка)
  "uprazhnenie": "1.9 Б",                           // от методиката (scripts/uprazhneniya.py): тема, описание, скала
  "tema": "…", "tsel": "…",                         // по подразбиране – от упражнението
  "myasto": "Двор на РСПБЗН – Левски",
  "uchastvashti": "Служителите от дежурните смени на РСПБЗН – Левски",
  "materialno": ["…"],                              // по подразбиране – от упражнението
  "merki": ["Упражнението се изпълнява с облекло и оборудване по Вариант № 2.", "…"],   // мерки за БЗР
  "hod": {"podgotvitelna": ["…"], "osnovna": ["…"], "zaklyuchitelna": ["…"]},   // своите действия по части;
                                                    // по подразбиране – чл. 7 от методиката и описанието на упражнението
  "minuti": {"podgotvitelna": 10, "osnovna": 30, "zaklyuchitelna": 5},
  "redove_provezhdane": 6                           // празни редове в таблицата за провежданията
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

EX_FILE = None      # --uprazhneniya: a saved data file instead of the regulations base (n8n)
OC_SUBTITLE = ["за провеждане на занятие съгласно план–график, {plan_grafik},",
               "за провеждане на занятията от инспекторите в група „Оперативен център“",
               "на сектор „Пожарогасителна и спасителна дейност“ през {year} г."]
SEMINAR_SUBTITLE = ["за провеждане на професионално обучение по месторабота през {year} година",
                    "на държавните служители на изпълнителски и ръководни длъжности от РДПБЗН – Плевен"]
UCHASTVASHTI = ("държавни служители, заемащи младши изпълнителски длъжности от направление "
                "„Пожарогасителна и спасителна дейност“ в {zvena}")
OC_SIGN = ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"]
MAX_FIG_WIDTH_CM = 16.0
EXPOSITION_TITLE = "ИЗЛОЖЕНИЕ НА УЧЕБНИЯ МАТЕРИАЛ"     # the heading that opens the lecture itself
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]


def bad(msg):
    sys.exit(f"BAD_INPUT: {msg}")


def exercises():
    """The exercises of the methodology – from the regulations base (scripts/uprazhneniya.py)."""
    import uprazhneniya
    return uprazhneniya.load(EX_FILE)


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


PSP_PARTS = [("podgotvitelna", "Подготвителна част", 10), ("osnovna", "Основна част", None),
             ("zaklyuchitelna", "Заключителна част", 5)]
PSP_DEFAULT = {
    "podgotvitelna": ["Ръководителят на занятието обявява темата, обяснява накратко целите и задачите на занятието "
                      "и разяснява мерките за безопасност и здраве при работа.",
                      "Обучаемите се строяват, проверяват облеклото и оборудването си и правят кратка загрявка."],
    "zaklyuchitelna": ["Ръководителят на занятието прави разбор: анализира действията на служителите, обявява "
                       "постигнатите резултати, отбелязва допуснатите слабости и дава насоки за бъдещата работа.",
                       "Обучаемите привеждат техниката и въоръжението в готовност."],
}


def build_psp(d, out):
    """Занятие по ПСП – the form of Приложение № 4 of the methodology."""
    warnings = []
    year = str(d.get("year") or "").strip()
    unit = B.typo(str(d.get("zveno") or "").strip())
    if not year or not unit:
        bad('за вид "psp" трябват "year" и "zveno"')
    number = d.get("uprazhnenie")
    ex_data = exercises() if number else {"uprazhneniya": {}}
    ex = ex_data["uprazhneniya"].get(number) if number else None
    if number and ex is None:
        bad(f"няма упражнение „{number}“ в данните за упражненията")
    if not ex and not (d.get("tema") and d.get("tsel")):
        bad('за вид "psp" трябва "uprazhnenie" или свои "tema" и "tsel"')
    tema = d.get("tema") or f"Упражнение № {number} „{ex['ime']}“"
    if d.get("tsel"):
        tsel = [d["tsel"]]
    else:
        tsel = [ex["tsel_uvod"]] + ["– " + g for g in ex["tsel"]]
    approver = d.get("approver") or B.unit_chief_approver(unit)
    if not approver:
        approver = {"lines": ["НАЧАЛНИК НА", unit.upper() + ":", B.PLACEHOLDER_RANK], "name": B.PLACEHOLDER_NAME}
        warnings.append("няма данни за утвърждаващия (началника на звеното) – подай \"approver\"")
    sign = dict(d.get("izgotvil") or {})
    if not sign.get("name"):
        warnings.append("няма данни за изготвилия – подай \"izgotvil\"")
    merki = d.get("merki") or []
    if not merki:
        warnings.append("празни „Мерки за безопасност и здраве“ – попълни ги по упражнението и указанията към него")
    hod, minutes = dict(d.get("hod") or {}), dict(d.get("minuti") or {})
    if not hod.get("osnovna"):
        hod["osnovna"] = exercise_description(number, ex) if ex else []
        if not hod["osnovna"]:
            warnings.append("празна „Основна част“ – подай \"hod\": {\"osnovna\": […]}")

    doc = B.new_document()
    B.letterhead(doc, extra=unit)
    B.approval(doc, approver, year, reg=True)
    B.title(doc, "ПЛАН–КОНСПЕКТ", d.get("subtitle") or [f"за провеждане на занятие по ПСП със служителите от {unit}"])
    field(doc, "ТЕМА", tema.rstrip(".") + ".")
    field(doc, "ЦЕЛ", tsel[0])
    for line in tsel[1:]:
        B.para(doc, line)
    field(doc, "МЯСТО", (d.get("myasto") or f"Сградата на {unit} и прилежащите към нея площи").rstrip(".") + ".")
    field(doc, "УЧАСТВАЩИ В ЗАНЯТИЕТО", (d.get("uchastvashti") or f"Служителите от дежурните смени на {unit}").rstrip(".") + ".")
    field_list(doc, "МАТЕРИАЛНО-ТЕХНИЧЕСКО ОСИГУРЯВАНЕ", d.get("materialno") or ((ex or {}).get("materialno") or ""))
    field_list(doc, "МЕРКИ ЗА БЕЗОПАСНОСТ И ЗДРАВЕ", merki)
    B.blank(doc)
    B.para(doc, "ОРГАНИЗАЦИЯ И ХОД НА ЗАНЯТИЕТО:", indent=False, keep=True)
    rows = []
    for i, (key, label, limit) in enumerate(PSP_PARTS, 1):
        m = minutes.get(key)
        dur = f"{m} минути" if m else (f"до {limit} минути" if limit else "…… минути")
        rows.append([str(i), [label, dur], hod.get(key) or PSP_DEFAULT.get(key) or [""]])
    B.grid(doc, ["№", "УЧЕБНИ ВЪПРОСИ И ПРОДЪЛЖИТЕЛНОСТ В МИНУТИ", "ДЕЙСТВИЯ НА РЪКОВОДИТЕЛЯ НА ЗАНЯТИЕТО И НА ОБУЧАЕМИТЕ"],
           rows, [1.0, 5.2, 10.3])
    B.blank(doc, 2)
    B.signature(doc, sign.get("date") or "", sign.get("lines") or [], sign.get("name") or B.PLACEHOLDER_NAME)
    B.blank(doc, 2)
    n = int(d.get("redove_provezhdane") or 6)
    B.grid(doc, ["№", ["ДАТА И ЧАСОВИ ИНТЕРВАЛ", "НА ПРОВЕЖДАНЕ"], ["РЪКОВОДИТЕЛ НА ЗАНЯТИЕТО", "(име, длъжност, подпис)"],
                 ["РЪКОВОДИТЕЛ", "НА ЗВЕНОТО ЗА ПБЗН", "(име, длъжност, подпис)"]],
           [[str(i), ["", ""], "", ""] for i in range(1, n + 1)], [1.0, 4.5, 5.5, 5.5])
    B.page_numbers(doc)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    doc.save(out)
    chars = sum(len(x) for v in hod.values() for x in (v or []))
    return {"output": out, "kind": "psp", "znatsi_izlozhenie": chars, "figuri": 0, "preduprezhdeniya": warnings}


def build(d, out, base):
    kind = d.get("kind")
    if kind == "psp":
        return build_psp(d, out)
    if kind not in ("oc", "seminar"):
        bad('"kind" трябва да е "oc", "seminar" или "psp"')
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
    heading = str(d.get("zaglavie_izlozhenie") or EXPOSITION_TITLE).strip().rstrip(":")
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
        if items:
            B.para(doc, heading.upper() + ":", keep=True)
        chars, figs = exposition(doc, items, base, warnings)
        B.blank(doc)

        t2 = dict(d.get("tema2") or {})
        ex_data = {} if t2.get("tekst") and not t2.get("uprazhnenie") else exercises()
        number = t2.get("uprazhnenie") or (None if t2.get("tekst") else ex_data["po_podrazbirane"])
        ex = {}
        if number:
            ex = ex_data["uprazhneniya"].get(number)
            if ex is None:
                bad(f"няма упражнение „{number}“ в данните за упражненията – налични: "
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
        if items:
            B.para(doc, f"{ROMAN[ROMAN.index(roman) + 1]}. {heading[0].upper() + heading[1:].lower()}:", keep=True)
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
    ap.add_argument("--uprazhneniya", help="записан файл с упражненията вместо нормативната база (тестове)")
    a = ap.parse_args()
    global EX_FILE
    EX_FILE = a.uprazhneniya
    try:
        with open(a.data, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        bad(f"data.json не се чете: {e}")
    print(json.dumps(build(d, a.output, os.path.dirname(os.path.abspath(a.data))), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
