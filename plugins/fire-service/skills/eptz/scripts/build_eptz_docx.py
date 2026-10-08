#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_eptz_docx.py (v3) — генерира ЕПТЗ .docx, като КЛОНИРА форматирането на
официалния образец `assets/eptz_template.docx` (бланка в рамка, междуредие 16 pt,
отстъп 1,5 см, подравняване двустранно, подчертани заглавия, без удебеляване,
таблици за подпис „ЕКСПЕРТ“ и „Изготвил“, номерирана литература).

Употреба:
  python build_eptz_docx.py --content report.md --meta meta.json --out EPTZ.docx
  [--template path/to/eptz_template.docx]

Документът няма маркировка „ЧЕРНОВА“ – излиза направо готов за преглед и подпис. Параметърът
--final се приема заради старите извиквания и не променя нищо.

meta.json: виж assets/eptz_meta.example.json. Прокуратурата се задава с "prokuratura"
(напр. "ОП – Плевен"); без него се ползва "РП – {rp_grad}".

Съдържанието (.md) е това между REPORT_START/END: ## I. Обстоятелства…,
## II. Поставени въпроси…, ## III. Пожаро-техническо изследване…, ### Отговор на въпрос № N:
Раздели I–II на документа (Основание, Представен материал) идват от meta.json.
"""
import argparse, copy, json, os, re, sys
from docx import Document
from docx.oxml.ns import qn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_shared", "scripts"))
from docx_common import report, typo, typo_all  # noqa: E402  (the common typography rules and the final check)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "..", "assets", "eptz_template.docx")
PH = "[...]"
CITATION_RE = re.compile(r"\s*\[\s*Източник\s*:[^\]]*\]", re.I)
DEFAULT_LIT = [
    "„Пожаротехническа експертиза“, Веселин Симеонов, „Атеа Букс” – гр. София, 2023 г.;",
    "„Методическо ръководство за установяване на причините за възникване на пожари”, НПИПАБ – НСПБЗН – МВР, гр. София, 2007 г.;",
    "„Справочник за пожарната опасност на веществата и материалите”, Държавно издателство „Техника” 1980 г."
]

def m(meta, k, default=PH):
    v = meta.get(k)
    return v if v not in (None, "") else default

def clean(t):
    t = CITATION_RE.sub("", t)
    return t.replace("**", "").replace("__", "").strip()

# ---------- низко ниво ----------
def ptext(p_el):
    return "".join(t.text or "" for t in p_el.iter(qn("w:t")))

def set_text(p_el, text):
    """Задава текст на параграф, като пази формата на първия run."""
    runs = p_el.findall(qn("w:r"))
    for child in list(p_el):
        if child.tag in (qn("w:proofErr"), qn("w:bookmarkStart"), qn("w:bookmarkEnd")):
            p_el.remove(child)
    if not runs:
        r = p_el.makeelement(qn("w:r"), {})
        ppr = p_el.find(qn("w:pPr"))
        if ppr is not None and ppr.find(qn("w:rPr")) is not None:
            r.append(copy.deepcopy(ppr.find(qn("w:rPr"))))
        p_el.append(r); runs = [r]
    first = runs[0]
    for r in runs[1:]:
        p_el.remove(r)
    for t in first.findall(qn("w:t")):
        first.remove(t)
    t = first.makeelement(qn("w:t"), {}); t.text = typo(text)
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    first.append(t)

def clone(proto, text=None):
    el = copy.deepcopy(proto)
    if text is not None:
        set_text(el, text)
    return el

def replace_in(el, old, new):
    for p in el.iter(qn("w:p")):
        s = ptext(p)
        if old in s:
            set_text(p, s.replace(old, new))

# ---------- markdown ----------
def parse_md(md):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    secs, cur = {}, None
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and not line.startswith("## "):
            continue
        if line.startswith("## "):
            title = line[3:].lower()
            cur = ("circ" if "обстоятелства" in title else
                   "q" if "въпрос" in title and "изследване" not in title else
                   "res" if "изследване" in title else None)
            secs[cur] = []
            continue
        if cur is None:
            continue
        s = line.strip()
        if not s or re.fullmatch(r"-{3,}|\*{3,}", s):
            secs[cur].append(("sep", None)); continue
        if s.startswith("### "):
            secs[cur].append(("ans", clean(s[4:]))); continue
        if re.match(r"^[-*•] ", s):
            secs[cur].append(("p", "– " + clean(s[2:]))); continue
        secs[cur].append(("p", clean(s)))
    # слива съседни редове от един параграф (разделени без празен ред)
    return {k: [x for x in v if x[0] != "sep"] for k, v in secs.items()}

# ---------- основно ----------
def build(content, meta, out, final, template):
    doc = Document(template)
    body = doc.element.body
    kids = list(body)

    def find_p(pred, start=0):
        for i, el in enumerate(kids):
            if i >= start and el.tag == qn("w:p") and pred(ptext(el)):
                return i
        raise SystemExit("Образецът не съдържа очакван параграф.")

    i_I   = find_p(lambda s: s.startswith("I. Основание"))
    i_Ib  = i_I + 1
    i_bl  = i_I + 2
    i_V   = find_p(lambda s: s.startswith("V. Пожаро"))
    i_ans = i_V + 1
    i_bj  = find_p(lambda s: s == "", i_ans + 2)            # празен двустранен
    P_HDR, P_BODY, P_BLANK = kids[i_I], kids[i_Ib], kids[i_bl]
    P_ANS, P_BLANKJ = kids[i_ans], kids[i_bj]
    protos = [copy.deepcopy(x) for x in (P_HDR, P_BODY, P_BLANK, P_ANS, P_BLANKJ)]
    P_HDR, P_BODY, P_BLANK, P_ANS, P_BLANKJ = protos

    # крайна таблица „ЕКСПЕРТ“ (първата таблица след раздел V)
    i_sig = next(i for i, el in enumerate(kids) if i > i_V and el.tag == qn("w:tbl"))
    del_to = i_sig - 2  # запазва двата празни реда преди подписа
    for el in kids[i_I:del_to]:
        body.remove(el)
    anchor = kids[del_to]   # първият запазен празен ред

    new = []
    zm = f"ЗМ № {m(meta,'zm_no')} по описа на {m(meta,'zm_opis')}"
    # прокуратура: "prokuratura" (напр. "ОП – Плевен") има предимство; иначе "РП – {rp_grad}"
    prok = m(meta, "prokuratura", f"РП – {m(meta, 'rp_grad')}")
    dp = f"ДП № {m(meta,'dp_no')} по описа на {prok}"
    post = f"постановление № {m(meta,'postanovlenie_no')} от {m(meta,'postanovlenie_date')}"
    new += [clone(P_HDR, "I. Основание за провеждане на експертизата."),
            clone(P_BODY, f"{post[0].upper()+post[1:]} за назначаване на СЪДЕБНА ПОЖАРО-ТЕХНИЧЕСКА ЕКСПЕРТИЗА на {m(meta,'naznachil')} във връзка със {zm} и {dp}."),
            clone(P_BLANK),
            clone(P_HDR, "II. Представен доказателствен материал."),
            clone(P_BODY, m(meta, "predstaven_material",
                  f"Материали по ДП № {m(meta,'dp_no')} по описа на {prok} и ЗМ № {m(meta,'zm_no')} г. по описа на {m(meta,'zm_opis')}."))]
    secs = parse_md(content)
    for key, title in (("circ", "III. Обстоятелства по делото."),
                       ("q", "IV. Поставени въпроси пред експерта.")):
        new += [clone(P_BLANK), clone(P_HDR, title)]
        new += [clone(P_BODY, t) for k, t in secs.get(key, []) if k == "p"]
    new += [clone(P_BLANK), clone(P_HDR, "V. Пожаро-техническо изследване, общи изводи от проведеното изследване на поставените въпроси.")]
    first = True
    for k, t in secs.get("res", []):
        if k == "ans":
            if not first:
                new.append(clone(P_BLANKJ))
            new.append(clone(P_ANS, t)); first = False
        else:
            new.append(clone(P_BODY, t))
    for el in new:
        anchor.addprevious(el)

    # ---- заглавна част ----
    kids = list(body)
    for el in kids[:find_p(lambda s: s.startswith("I. Основание"))]:
        if el.tag != qn("w:p"):
            continue
        s = ptext(el)
        if s.startswith("За проведена"):
            set_text(el, f"За проведена СЪДЕБНА ПОЖАРО-ТЕХНИЧЕСКА ЕКСПЕРТИЗА по {zm} и {dp}, назначена с {post} на {m(meta,'naznachil')}.")
        elif s.startswith("Експерт по досъдебното"):
            rs = el.findall(qn("w:r"))
            tail = f" {m(meta,'expert_name','[Име на експерта]')} – {m(meta,'expert_position')}."
            for r in rs[2:]: el.remove(r)
            for t in rs[1].findall(qn("w:t")): t.text = typo(tail)
        elif s.startswith("Образование:"):
            rs = el.findall(qn("w:r")); rs[-1].find(qn("w:t")).text = f" {m(meta,'expert_education','Висше')}."
        elif s.startswith("Специалност:"):
            rs = el.findall(qn("w:r")); rs[-1].find(qn("w:t")).text = f" „{m(meta,'expert_specialnost','Пожарна и аварийна безопасност')}“."
        elif s.startswith("ЧЕРНОВА"):   # a template made before 2.4.3 still carries the notice
            body.remove(el)
    lh = doc.tables[0]
    replace_in(lh._tbl, "– ПЛЕВЕН", f"– {m(meta,'rd_grad','Плевен').upper()}")

    # ---- подписи и „Изготвил“ ----
    name = m(meta, "expert_name", "[Име на експерта]")
    for t in doc.tables[1:]:
        replace_in(t._tbl, "[Име Фамилия]", name)
        replace_in(t._tbl, "[ЗВАНИЕ]", m(meta, "expert_rank", "[ЗВАНИЕ]").upper())
    izg = doc.tables[-1]
    replace_in(izg._tbl, "[звание]", m(meta, "izgotvil_position", "[звание]"))
    rows = izg._tbl.findall(qn("w:tr"))
    date_p = rows[1].find(".//" + qn("w:p")); set_text(date_p, m(meta, "izgotvil_date"))
    copies = meta.get("copies") or ["деловодство"]
    proto_row = rows[4]
    for r in rows[4:]:
        izg._tbl.remove(r)
    set_text(rows[3].find(".//" + qn("w:p")), f"Отп:  в {len(copies)} екз.")
    for n, c in enumerate(copies, 1):
        r = copy.deepcopy(proto_row)
        set_text(r.find(".//" + qn("w:p")), f"Екз. № {n} – {c}")
        izg._tbl.append(r)

    # ---- литература ----
    lit_ps = [el for el in body if el.tag == qn("w:p") and el.find(".//" + qn("w:numPr")) is not None
              and el.find(".//" + qn("w:pStyle")) is not None
              and el.find(".//" + qn("w:pStyle")).get(qn("w:val")) == "BodyTextIndent3"]
    if lit_ps:
        proto = copy.deepcopy(lit_ps[0])
        for el in lit_ps[1:]: body.remove(el)
        items = meta.get("literatura") or DEFAULT_LIT
        cur = lit_ps[0]
        set_text(cur, items[0])
        for it in items[1:]:
            e = clone(proto, it); cur.addnext(e); cur = e

    # ---- no draft notice in the footer either (templates made before 2.4.3) ----
    for sec in doc.sections:
        for f in (sec.footer, sec.first_page_footer, sec.even_page_footer):
            for p in f._element.iter(qn("w:p")):
                for r in p.findall(qn("w:r")):
                    t = r.find(qn("w:t"))
                    if t is not None and "ЧЕРНОВА" in (t.text or ""):
                        p.remove(r)
    typo_all(doc, qn("w:t"))
    doc.save(out)
    report(out)
    print(f"✅ {out}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True); ap.add_argument("--meta")
    ap.add_argument("--out", required=True); ap.add_argument("--final", action="store_true", help="без действие – приема се заради старите извиквания")
    ap.add_argument("--template", default=DEFAULT_TEMPLATE)
    a = ap.parse_args()
    meta = json.load(open(a.meta, encoding="utf-8")) if a.meta else {}
    md = open(a.content, encoding="utf-8").read()
    build(md, meta, a.out, a.final, a.template)
