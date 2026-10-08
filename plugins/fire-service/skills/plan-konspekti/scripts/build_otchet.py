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
  "tema2": {"uprazhnenie": "1.1"},                          // упражнение от данните за упражненията
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
  "sekundi"             упражнение за време (Приложение № 1 на методиката): точките се смятат по
                        норматива му в данните за упражненията; за упражнение без норматив (за правилно
                        изпълнение или със свой текст) скриптът спира с NO_NORM – попитай за точките;
  "tochki"              упражнение за правилно изпълнение (Приложение № 2): „При изпълнение на
                        упражнението служителите постигнаха N точки.“; повече от най-многото по
                        картата на упражнението се отказва

Отчетът се изготвя заедно с план-конспекта и излиза попълнен. Каквото не е подадено, скриптът
го попълва по обичайното от одобрените отчети и го казва в "preduprezhdeniya":
  "prisastvali"   РСПБЗН – Плевен – 6 служители; всяко друго звено – 3;
  резултат        упражнение за време – секунди за 6 точки („отличен“) или за 5 точки („добър“)
                  по норматива му; упражнение за правилно изпълнение – най-многото точки по картата.
Попълнените стойности са еднакви при всяко изграждане за същата дата и звено. Истинските числа,
щом са известни, се подават и имат предимство. С "popalni": false нищо не се попълва – липсващото
излиза с точки за попълване на ръка.

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
import build_konspekt  # noqa: E402
from build_konspekt import exercise_text, exercises  # noqa: E402


def bad(msg):
    sys.exit(f"BAD_INPUT: {msg}")


def points(norm, seconds):
    """norm: [{"do_sek": 60, "tochki": 6}, …] ascending by do_sek; slower than the last → 0."""
    for step in sorted(norm, key=lambda s: s["do_sek"]):   # the best score first: ≤ 65 s → 6 points
        if seconds <= step["do_sek"]:
            return step["tochki"]
    return 0


def num(v):
    f = float(v)
    return str(int(f)) if f == int(f) else str(f).replace(".", ",")


DOTS = "………"


def blank_result(ex):
    """The result line left for filling in by hand – the lesson has not been held yet."""
    if (ex or {}).get("normativ"):
        return f"Резултатът при проиграване на поставеното упражнение е {DOTS} сек., което е за {DOTS} точки."
    if (ex or {}).get("max_tochki"):
        return f"При изпълнение на упражнението служителите постигнаха {DOTS} точки."
    return "…" * 60


PRESENT_DEFAULT = {"РСПБЗН – Плевен": 6}     # the usual size of the shift in the approved reports
PRESENT_OTHER = 3


def _pick(key, n):
    """A stable choice 0..n-1 for the same date, unit and exercise (no randomness between builds)."""
    import hashlib
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % n


def usual_present(unit):
    name = " ".join(str(unit).replace(" - ", " – ").split())
    return PRESENT_DEFAULT.get(name, PRESENT_OTHER)


def usual_result(z, ex, key):
    """The usual result of the shifts – excellent or good: for a timed exercise seconds worth 6 or
    5 points by its norm, otherwise the top score of the card. → the keys to merge into z."""
    norm = sorted((ex or {}).get("normativ") or [], key=lambda s: s["do_sek"])
    if len(norm) >= 2:
        best, good = norm[0]["do_sek"], norm[1]["do_sek"]
        if _pick(key + "|band", 2) == 0:
            return {"sekundi": best - _pick(key, 3)}
        return {"sekundi": good - _pick(key, max(1, min(4, good - best)))}
    if norm:
        return {"sekundi": norm[0]["do_sek"] - _pick(key, 3)}
    if (ex or {}).get("max_tochki"):
        return {"tochki": ex["max_tochki"]}
    return {}


def result_sentence(z, ex, number, warnings=None, fill=None):
    norm = (ex or {}).get("normativ")
    if str(z.get("rezultat") or "").strip():
        return str(z["rezultat"]).strip()
    sec, pts = z.get("sekundi"), z.get("tochki")
    if sec is None and pts is None and fill:
        usual = usual_result(z, ex, fill)
        if usual:
            z = dict(z, **usual)
            sec, pts = z.get("sekundi"), z.get("tochki")
            warnings.append(f"за {z.get('zveno')} резултатът е попълнен по обичайното ("
                            + (f"{sec} сек." if sec is not None else f"{pts} точки") + ") – смени го, ако истинският е друг")
    if sec is None and pts is None and warnings is not None:
        warnings.append(f"за {z.get('zveno')} няма резултат – оставен е за попълване на ръка")
        return blank_result(ex)
    if sec is not None and pts is None:
        if not norm:
            sys.exit(f"NO_NORM: за упражнение {number or '(свой текст)'} няма норматив в данните за упражненията – "
                     f"подай \"tochki\" за {z.get('zveno')}")
        pts = points(norm, float(sec))
    top = (ex or {}).get("max_tochki") or (6 if (ex or {}).get("normativ") else None)
    if pts is not None and top is not None and float(pts) > top:
        bad(f"за {z.get('zveno')}: {num(pts)} точки са повече от най-многото за упражнение {number} ({top})")
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
    ex_data = {} if t2.get("tekst") and not t2.get("uprazhnenie") else exercises()
    number = t2.get("uprazhnenie") or (None if t2.get("tekst") else ex_data["po_podrazbirane"])
    ex = ex_data["uprazhneniya"].get(number) if number else {}
    if number and ex is None:
        bad(f"няма упражнение „{number}“ в данните за упражненията – подай \"tema2\": {{\"tekst\": …}}")
    text2 = t2.get("tekst") or exercise_text(number, ex, ex_data["metodika"])
    tema1 = d["tema1"].strip().rstrip(".")
    names = B.join_units([u.get("zveno", "") for u in units])
    sign = dict(d.get("izgotvil") or {})
    if not sign.get("name"):
        warnings.append("няма данни за изготвилия – подай \"izgotvil\"")

    fill = d.get("popalni", True) is not False
    doc = B.new_document()
    B.letterhead(doc)
    B.para(doc, "Рег. № ............................, екз. № .......", align=B.LEFT, indent=False)
    B.para(doc, f"..........................{year} г.", align=B.LEFT, indent=False)
    B.blank(doc, 2 if len(units) < 2 else 1)
    B.title(doc, "ОТЧЕТ", ["за", f"проведено занятие със служителите на {names},",
                           f"които са на смяна на {date}"])
    B.para(doc, f"На {date} се проведоха занятия, както следва:")
    for i, u in enumerate(units, 1):
        if not str(u.get("zveno") or "").strip():
            bad("звено без име")
        present = u.get("prisastvali")
        if present is None and fill:
            present = usual_present(u["zveno"])
            warnings.append(f"за {u['zveno']} присъствалите са попълнени по обичайното ({present}) – смени ги, ако са други")
        elif present is None:
            warnings.append(f"за {u['zveno']} няма брой присъствали – оставен е за попълване на ръка")
        B.blank(doc)
        B.para(doc, f"{i}. В {u['zveno']}")
        B.para(doc, f"ТЕМА 1 (лекция): „{tema1}.“")
        B.para(doc, f"ТЕМА 2 (практика): {text2}")
        word = "служител" if present is not None and int(present) == 1 else "служители"
        count = DOTS if present is None else int(present)
        B.para(doc, f"ПРИСЪСТВАЛИ СЛУЖИТЕЛИ: {count} {word} от състава на дежурната смяна.")
        key = f"{date}|{u['zveno']}|{number}" if fill else None
        B.para(doc, f"ПОСТИГНАТИ РЕЗУЛТАТИ: {result_sentence(u, ex, number, warnings, key)}")
    B.blank(doc, 3 if len(units) < 2 else 1)       # two units and the signature still fit on one page
    position = sign.get("position") or ""
    name = sign.get("name") or B.PLACEHOLDER_NAME
    footer = [line for line in ["Изготвил:", position, name.replace("инспектор ", "").replace("Инспектор ", ""),
                                sign.get("date") or date, "Отп. в 1 екз.", "Екз. № 1 – деловодство"] if line]
    lines = sign.get("lines") or ["ИНСПЕКТОР В", "ГРУПА „ОПЕРАТИВЕН ЦЕНТЪР“"]
    if len(units) < 2:
        B.signature(doc, "", lines, name, left_extra=[])
        B.blank(doc, 2)
        for line in footer:
            B.para(doc, line, align=B.LEFT, indent=False)
    else:           # two units: the block goes beside the signature, so the report stays on one page
        B.signature(doc, "", lines, name, left=footer)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    doc.save(out)
    B.report(out)
    return {"output": out, "zvena": len(units), "preduprezhdeniya": warnings}


def main():
    ap = argparse.ArgumentParser(description="Отчет за проведено занятие (.docx)")
    ap.add_argument("data", help="data.json")
    ap.add_argument("-o", "--output", required=True, help="изходен .docx")
    ap.add_argument("--uprazhneniya", help="записан файл с упражненията вместо нормативната база (тестове)")
    a = ap.parse_args()
    build_konspekt.EX_FILE = a.uprazhneniya
    try:
        with open(a.data, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        bad(f"data.json не се чете: {e}")
    print(json.dumps(build(d, a.output), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
