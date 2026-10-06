#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_otchet.py — изгражда ОТЧЕТ за проведено занятие на инспектор от група „Оперативен център“
(по план-графика) като .docx на бланката на РДПБЗН – Плевен. За семинарите отчет не се прави.

    python3 scripts/build_otchet.py data.json -o /mnt/user-data/outputs/Otchet_....docx

data.json:
{
  "data": "27.10.2026 г.",                                  // датата на занятието
  "tema1": "Гасене на пожари в житни масиви",               // темата на лекцията
  "tema2": {"uprazhnenie": "1.1"},                          // упражнение от data/uprazhneniya.json
                                                            //   или {"tekst": "Проиграване на …"}
  "zvena": [
    {"zveno": "РСПБЗН – Червен бряг", "prisastvali": 3, "sekundi": 72, "tochki": 4},
    {"zveno": "РСПБЗН – Кнежа", "prisastvali": 3, "rezultat": "Служителите изпълниха упражнението без грешки."}
  ],
  "izgotvil": {"name": "Иван Петров", "position": "Инспектор IV ст. в група ОЦ",
               "lines": ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"], "date": "27.10.2026 г."}
}

Резултат за едно звено – по реда на предимство:
  "rezultat"            свободен текст (едно изречение);
  "sekundi" + "tochki"  „… е 72 сек., което е за 4 точки.“;
  "sekundi"             точките се смятат по норматива на упражнението, ако го има в
                        data/uprazhneniya.json ("normativ"); без норматив скриптът спира с NO_NORM –
                        тогава попитай потребителя за точките;
  "tochki"              „При изпълнение на упражнението служителите постигнаха N точки.“

Скриптът отпечатва JSON {"output", "zvena", "preduprezhdeniya"}.

Грешки (на stderr, код ≠ 0):
    BAD_INPUT: ...   — липсва поле, непознато упражнение
    NO_NORM: ...     — подадени са само секунди, а за упражнението няма норматив
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blanka as B  # noqa: E402
from build_konspekt import exercise_text, exercises  # noqa: E402


def bad(msg):
    sys.exit(f"BAD_INPUT: {msg}")


def points(norm, seconds):
    """norm: [{"do_sek": 60, "tochki": 6}, …] ascending by do_sek; slower than the last → 0."""
    for step in sorted(norm, key=lambda s: s["do_sek"]):
        if seconds <= step["do_sek"]:
            return step["tochki"]
    return 0


def num(v):
    f = float(v)
    return str(int(f)) if f == int(f) else str(f).replace(".", ",")


def result_sentence(z, norm, number):
    if str(z.get("rezultat") or "").strip():
        return str(z["rezultat"]).strip()
    sec, pts = z.get("sekundi"), z.get("tochki")
    if sec is not None and pts is None:
        if not norm:
            sys.exit(f"NO_NORM: за упражнение {number or '(свой текст)'} няма норматив в data/uprazhneniya.json – "
                     f"подай \"tochki\" за {z.get('zveno')}")
        pts = points(norm, float(sec))
    if sec is not None:
        return f"Резултатът при проиграване на поставеното упражнение е {num(sec)} сек., което е за {num(pts)} точки."
    if pts is not None:
        return f"При изпълнение на упражнението служителите постигнаха {num(pts)} точки."
    bad(f"за {z.get('zveno')} няма резултат (\"sekundi\", \"tochki\" или \"rezultat\")")


def build(d, out):
    date = str(d.get("data") or "").strip()
    if len(date) < 10:
        bad('липсва "data" във вид ДД.ММ.ГГГГ г.')
    if not str(d.get("tema1") or "").strip():
        bad('липсва "tema1"')
    units = d.get("zvena") or []
    if not units:
        bad('липсва "zvena"')
    warnings = []
    year = date[6:10]
    t2 = dict(d.get("tema2") or {})
    ex_data = exercises()
    number = t2.get("uprazhnenie") or (None if t2.get("tekst") else ex_data["po_podrazbirane"])
    ex = ex_data["uprazhneniya"].get(number) if number else {}
    if number and ex is None:
        bad(f"няма упражнение „{number}“ в data/uprazhneniya.json – подай \"tema2\": {{\"tekst\": …}}")
    text2 = t2.get("tekst") or exercise_text(number, ex, ex_data["metodika"])
    tema1 = d["tema1"].strip().rstrip(".")
    names = B.join_units([u.get("zveno", "") for u in units])
    sign = dict(d.get("izgotvil") or {})
    if not sign.get("name"):
        warnings.append("няма данни за изготвилия – подай \"izgotvil\"")

    doc = B.new_document()
    B.letterhead(doc)
    B.para(doc, "Рег. № ............................, екз. № .......", align=B.LEFT, indent=False)
    B.para(doc, f"..........................{year} г.", align=B.LEFT, indent=False)
    B.blank(doc, 2)
    B.title(doc, "ОТЧЕТ", ["за", f"проведено занятие със служителите на {names},",
                           f"които са на смяна на {date}"])
    B.para(doc, f"На {date} се проведоха занятия, както следва:")
    for i, u in enumerate(units, 1):
        if not str(u.get("zveno") or "").strip():
            bad("звено без име")
        present = u.get("prisastvali")
        if present is None:
            bad(f"за {u['zveno']} липсва \"prisastvali\"")
        B.blank(doc)
        B.para(doc, f"{i}. В {u['zveno']}")
        B.para(doc, f"ТЕМА 1 (лекция): „{tema1}.“")
        B.para(doc, f"ТЕМА 2 (практика): {text2}")
        word = "служител" if int(present) == 1 else "служители"
        B.para(doc, f"ПРИСЪСТВАЛИ СЛУЖИТЕЛИ: {int(present)} {word} от състава на дежурната смяна.")
        B.para(doc, f"ПОСТИГНАТИ РЕЗУЛТАТИ: {result_sentence(u, (ex or {}).get('normativ'), number)}")
    B.blank(doc, 3)
    position = sign.get("position") or ""
    name = sign.get("name") or B.PLACEHOLDER_NAME
    B.signature(doc, "", sign.get("lines") or ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"], name,
                left_extra=[])
    B.blank(doc, 2)
    for line in ["Изготвил:", position, name.replace("инспектор ", "").replace("Инспектор ", ""),
                 sign.get("date") or date, "Отп. в 1 екз.", "Екз. № 1 – деловодство"]:
        if line:
            B.para(doc, line, align=B.LEFT, indent=False)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    doc.save(out)
    return {"output": out, "zvena": len(units), "preduprezhdeniya": warnings}


def main():
    ap = argparse.ArgumentParser(description="Отчет за проведено занятие (.docx)")
    ap.add_argument("data", help="data.json")
    ap.add_argument("-o", "--output", required=True, help="изходен .docx")
    a = ap.parse_args()
    try:
        with open(a.data, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        bad(f"data.json не се чете: {e}")
    print(json.dumps(build(d, a.output), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
