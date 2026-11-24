"""ocrmypdf plugin: OCR each page with engine.read_page and hand ocrmypdf hOCR.

Loaded by arabic-ocr as  ocrmypdf --plugin <this file>. It can run inside another Python's
ocrmypdf (Homebrew's on macOS), so it makes its own package importable first.

Environment (set by arabic-ocr): ARABIC_OCR_ENGINE, ARABIC_OCR_KEEP_HARAKAT=1.
"""

from __future__ import annotations

import html
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocrmypdf import hookimpl  # noqa: E402
from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence  # noqa: E402

from pdfcraft_arabic_ocr import config, engine  # noqa: E402

log = logging.getLogger(__name__)


def _hocr(image: Path, width: int, height: int, lines) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"',
        '    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ar" lang="ar">',
        "<head><title></title>",
        '<meta http-equiv="Content-Type" content="text/html;charset=utf-8"/>',
        "<meta name='ocr-system' content='pdfcraft-arabic-ocr'/>",
        "<meta name='ocr-capabilities' content='ocr_page ocr_carea ocr_par ocr_line ocrx_word ocrp_dir ocrp_lang ocrp_wconf'/>",
        "</head><body>",
        f"<div class='ocr_page' id='page_1' title='image \"{html.escape(image.name)}\"; bbox 0 0 {width} {height}; ppageno 0'>",
    ]
    wid = 0
    for i, ln in enumerate(lines, 1):
        l, t, w, h = ln.box
        r, b = l + w, t + h
        rtl = bool(engine.RTL_LETTER.search(ln.text))
        d, lang = ("rtl", "ara") if rtl else ("ltr", "eng")
        lh = max(1, h)
        out.append(f"<div class='ocr_carea' id='block_1_{i}' title='bbox {l} {t} {r} {b}'>")
        out.append(f"<p class='ocr_par' dir='{d}' id='par_1_{i}' lang='{lang}' title='bbox {l} {t} {r} {b}'>")
        out.append(
            f"<span class='ocr_line' id='line_1_{i}' title='bbox {l} {t} {r} {b}; baseline 0 -{round(lh * 0.22)}; "
            f"x_size {lh}; x_descenders {round(lh * 0.22)}; x_ascenders {round(lh * 0.2)}'>"
        )
        for wd in ln.words:
            wid += 1
            wl, wt, ww, wh = wd.box
            out.append(
                f"<span class='ocrx_word' id='word_1_{wid}' title='bbox {wl} {wt} {wl + ww} {wt + wh}; x_wconf {wd.conf}'>"
                f"{html.escape(wd.text)}</span>"
            )
        out.append("</span></p></div>")
    out.append("</div></body></html>")
    return "\n".join(out)


class ArabicOcrEngine(OcrEngine):
    @staticmethod
    def version() -> str:
        return "1"

    @staticmethod
    def creator_tag(options) -> str:
        return "pdfcraft-arabic-ocr"

    def __str__(self) -> str:
        return "pdfcraft-arabic-ocr"

    @staticmethod
    def languages(options):
        return set(engine.VISION_LANGS) | {"ara", "eng", "fas", "urd"}

    @staticmethod
    def get_orientation(input_file: Path, options) -> OrientationConfidence:
        try:
            from ocrmypdf._exec import tesseract

            return tesseract.get_orientation(input_file, engine_mode=None, timeout=180)
        except Exception as e:  # noqa: BLE001 - orientation is best effort
            log.debug("orientation check skipped: %s", e)
            return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options) -> float:
        return 0.0

    @staticmethod
    def generate_hocr(input_file: Path, output_hocr: Path, output_text: Path, options) -> None:
        cfg = config.load()
        langs = "+".join(options.languages or ["ara"])
        eng = os.environ.get("ARABIC_OCR_ENGINE") or None
        W, H, lines = engine.read_page(input_file, cfg, langs, eng)
        lines = engine.clean_lines(lines, os.environ.get("ARABIC_OCR_KEEP_HARAKAT") == "1")
        if not W:
            W, H = engine.image_size(Path(input_file))
        Path(output_hocr).write_text(_hocr(Path(input_file), W, H, lines), encoding="utf-8")
        Path(output_text).write_text("\n".join(ln.text for ln in lines) + "\n", encoding="utf-8")

    @staticmethod
    def generate_pdf(input_file: Path, output_pdf: Path, output_text: Path, options) -> None:
        raise NotImplementedError("pdfcraft-arabic-ocr produces hOCR; don't use --pdf-renderer sandwich")


@hookimpl
def get_ocr_engine(options=None):
    if getattr(options, "ocr_engine", "auto") not in (None, "auto"):
        return None
    return ArabicOcrEngine()
