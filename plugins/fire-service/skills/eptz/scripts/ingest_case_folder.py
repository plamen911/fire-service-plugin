#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_case_folder.py — Приема папка с материали по случай (сканирани PDF и снимки)
и извлича текста за анализ от пожаро-техническия експерт.

Логика:
- PDF: първо се чете вграденият текстов слой (pdftotext). Сканиранията от iPhone обикновено
  имат селектируем (кирилски) текстов слой и не се нуждаят от OCR. Ако текстов слой няма
  (само изображения), страниците се растеризират (pdftoppm) и се OCR-ват с tesseract.
- Изображения (jpg/png/tif/bmp): описват се като „за визуален преглед" (за оглед на огнищни
  признаци) и допълнително се OCR-ват, в случай че са снимки на документни страници.
- HEIC/HEIF (снимки от iPhone): опит за конвертиране към JPG (sips / heif-convert / Pillow),
  след което снимката се добавя за визуален преглед и се OCR-ва като останалите.
- Резултат: консолидиран `case_ingest.md` с текст по файлове + списък със снимки за преглед.

OCR език: `bul+eng`, ако системният tesseract има пакета `bul` (`tesseract-ocr-bul`) или
ако има `assets/tessdata/bul.traineddata`; иначе `eng` (с предупреждение). Текстовият слой на PDF е езиково-независим и е
предпочитан, затова при качествени сканирания OCR изобщо не е нужен.

Зависимости (външни инструменти):
- pdftotext, pdftoppm, pdfinfo  →  пакет poppler-utils
- tesseract                      →  пакет tesseract-ocr (+ tesseract-ocr-bul за кирилица)
- sips (macOS) или heif-convert (libheif) или Pillow+pillow-heif  →  за HEIC снимки
Скриптът НЕ спира при липсваща зависимост, а изрежда какво липсва и продължава с наличното.

Употреба:
    python scripts/ingest_case_folder.py --folder /път/до/папката --out case_ingest.md
"""

import argparse
import os
import shutil
import subprocess
import sys

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
HEIC_EXT = {".heic", ".heif"}
TEXT_EXT = {".txt", ".md"}
MIN_CHARS_PER_PAGE = 80  # под този праг PDF се счита за сканиран без текстов слой


def have(cmd):
    return shutil.which(cmd) is not None


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def check_dependencies():
    """Проверява наличието на външните инструменти и връща списък с предупреждения
    (човеко-четими указания за инсталиране). Не прекъсва изпълнението."""
    warnings = []
    if not have("pdftotext") or not have("pdftoppm") or not have("pdfinfo"):
        warnings.append(
            "Липсва poppler-utils (pdftotext/pdftoppm/pdfinfo) — PDF материалите няма да "
            "бъдат обработени. Инсталирайте: Debian/Ubuntu `apt install poppler-utils`; "
            "macOS `brew install poppler`."
        )
    if not have("tesseract"):
        warnings.append(
            "Липсва tesseract — сканирани PDF без текстов слой и снимки на документи няма "
            "да бъдат OCR-нати. Инсталирайте: Debian/Ubuntu `apt install tesseract-ocr "
            "tesseract-ocr-bul`; macOS `brew install tesseract tesseract-lang`."
        )
    if not (have("sips") or have("heif-convert") or _pillow_heif_ok()):
        warnings.append(
            "Няма конвертор за HEIC (sips/heif-convert/pillow-heif) — снимките от iPhone в "
            "HEIC ще бъдат само изброени, без OCR. Инсталирайте libheif "
            "(`apt install libheif-examples` или `brew install libheif`) или "
            "`pip install pillow pillow-heif`."
        )
    return warnings


def _pillow_heif_ok():
    try:
        import PIL  # noqa: F401
        import pillow_heif  # noqa: F401
        return True
    except Exception:
        return False


def convert_heic_to_jpg(path, workdir):
    """Опитва да конвертира HEIC/HEIF към JPG. Връща пътя до JPG или None."""
    base = os.path.splitext(os.path.basename(path))[0] + ".jpg"
    out = os.path.join(workdir, base)
    # 1) macOS sips
    if have("sips"):
        res = run(["sips", "-s", "format", "jpeg", path, "--out", out])
        if os.path.exists(out):
            return out
    # 2) libheif heif-convert
    if have("heif-convert"):
        res = run(["heif-convert", path, out])
        if os.path.exists(out):
            return out
    # 3) Pillow + pillow-heif
    if _pillow_heif_ok():
        try:
            import pillow_heif
            from PIL import Image
            pillow_heif.register_heif_opener()
            Image.open(path).convert("RGB").save(out, "JPEG", quality=90)
            if os.path.exists(out):
                return out
        except Exception:
            pass
    return None


def find_tessdata():
    """Връща (tessdata_dir или None, lang_string)."""
    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.dirname(here)
    bundled = os.path.join(skill_root, "assets", "tessdata")
    if os.path.exists(os.path.join(bundled, "bul.traineddata")):
        return bundled, "bul+eng"
    # системни езици
    res = run(["tesseract", "--list-langs"]) if have("tesseract") else None
    langs = res.stdout if res else ""
    if "bul" in langs:
        return None, "bul+eng"
    return None, "eng"


def ocr_image(path, tessdata_dir, lang):
    if not have("tesseract"):
        return ""
    cmd = ["tesseract", path, "stdout", "-l", lang]
    if tessdata_dir:
        cmd += ["--tessdata-dir", tessdata_dir]
    res = run(cmd)
    return res.stdout.strip()


def pdf_text_layer(path):
    if not have("pdftotext"):
        return ""
    res = run(["pdftotext", "-layout", path, "-"])
    return res.stdout.strip()


def pdf_page_count(path):
    if have("pdfinfo"):
        res = run(["pdfinfo", path])
        for line in res.stdout.splitlines():
            if line.lower().startswith("pages:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
    return 1


def ocr_pdf(path, tessdata_dir, lang, workdir):
    """Растеризира PDF и OCR-ва всяка страница. Връща обединен текст."""
    if not (have("pdftoppm") and have("tesseract")):
        return ""
    prefix = os.path.join(workdir, "page")
    run(["pdftoppm", "-r", "200", "-png", path, prefix])
    pages = sorted(p for p in os.listdir(workdir) if p.startswith("page") and p.endswith(".png"))
    chunks = []
    for pg in pages:
        txt = ocr_image(os.path.join(workdir, pg), tessdata_dir, lang)
        if txt:
            chunks.append(txt)
    return "\n\n".join(chunks).strip()


def main():
    ap = argparse.ArgumentParser(description="Приема папка с материали по случай и извлича текст.")
    ap.add_argument("--folder", required=True, help="Папка с PDF/снимки по случая.")
    ap.add_argument("--out", required=True, help="Изходен .md файл с извлечения текст.")
    args = ap.parse_args()

    folder = args.folder
    if not os.path.isdir(folder):
        sys.exit("Папката не съществува: %s" % folder)

    dep_warnings = check_dependencies()
    for w in dep_warnings:
        sys.stderr.write("⚠️  " + w + "\n")

    tessdata_dir, lang = find_tessdata()
    import tempfile

    files = sorted(
        os.path.join(dp, f)
        for dp, _, fns in os.walk(folder)
        for f in fns
    )

    docs = []          # (име, текст, метод)
    photos = []        # пътища за визуален преглед
    skipped = []       # (име, причина)

    for path in files:
        name = os.path.relpath(path, folder)
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            text = pdf_text_layer(path)
            method = "текстов слой (pdftotext)"
            if len(text) < MIN_CHARS_PER_PAGE * pdf_page_count(path):
                with tempfile.TemporaryDirectory() as wd:
                    ocr = ocr_pdf(path, tessdata_dir, lang, wd)
                if len(ocr) > len(text):
                    text, method = ocr, "OCR (%s)" % lang
            docs.append((name, text, method))
        elif ext in IMAGE_EXT:
            photos.append(path)
            ocr = ocr_image(path, tessdata_dir, lang)
            if ocr:
                docs.append((name, ocr, "OCR на изображение (%s)" % lang))
        elif ext in HEIC_EXT:
            with tempfile.TemporaryDirectory() as wd:
                jpg = convert_heic_to_jpg(path, wd)
                if jpg:
                    # запази конвертирания JPG до оригинала за визуален преглед
                    jpg_final = os.path.splitext(path)[0] + "_converted.jpg"
                    try:
                        shutil.copyfile(jpg, jpg_final)
                        photos.append(jpg_final)
                    except Exception:
                        photos.append(path)
                    ocr = ocr_image(jpg, tessdata_dir, lang)
                    if ocr:
                        docs.append((name, ocr, "OCR след HEIC→JPG (%s)" % lang))
                else:
                    photos.append(path)
                    skipped.append((name, "HEIC – не успях да конвертирам към JPG; "
                                          "инсталирайте sips/heif-convert/pillow-heif за OCR "
                                          "(може да се прегледа визуално)"))
        elif ext in TEXT_EXT:
            with open(path, encoding="utf-8", errors="replace") as f:
                docs.append((name, f.read().strip(), "текстов файл"))
        else:
            skipped.append((name, "неподдържан формат"))

    lines = ["# Извлечени материали по случая", ""]
    lines.append("Папка: `%s`" % folder)
    lines.append("OCR език: `%s`%s" % (lang, "" if tessdata_dir or lang != "eng"
                 else "  ⚠️ Българският пакет липсва – инсталирай tesseract-ocr-bul (apt) или tesseract-lang (brew)"))
    if dep_warnings:
        lines.append("")
        lines.append("## ⚠️ Липсващи зависимости")
        for w in dep_warnings:
            lines.append("- %s" % w)
    lines.append("")

    if docs:
        lines.append("## Текстови материали")
        for name, text, method in docs:
            lines.append("")
            lines.append("### %s  _(%s)_" % (name, method))
            lines.append("")
            lines.append(text if text else "_(няма извлечен текст)_")
    else:
        lines.append("_Няма извлечени текстови материали._")

    lines.append("")
    lines.append("## Снимки за визуален преглед")
    if photos:
        lines.append("Прегледай тези изображения за огнищни признаци, термични поражения и др.:")
        for p in photos:
            lines.append("- `%s`" % p)
    else:
        lines.append("_Няма изображения._")

    if skipped:
        lines.append("")
        lines.append("## Пропуснати / за внимание")
        for name, why in skipped:
            lines.append("- `%s` – %s" % (name, why))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("✅ Извлечено: %d текстови материала, %d снимки. Записано в: %s"
          % (len(docs), len(photos), args.out))
    if lang == "eng" and not tessdata_dir:
        print("ℹ️  Само английски OCR. За кирилица добавете bul.traineddata в assets/tessdata/ "
              "(текстовият слой на iPhone сканиранията обикновено прави OCR ненужен).")


if __name__ == "__main__":
    main()
