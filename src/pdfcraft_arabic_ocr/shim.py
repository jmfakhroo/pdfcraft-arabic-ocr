"""tesseract-for-pdfcraft: what PdfCraft runs as "tesseract" (via $PDFCRAFT_TESSERACT).

PdfCraft (tested 0.18 to 0.22) offers only English for OCR and always runs
    tesseract <page.png> stdout -l eng tsv
with a nearly empty environment. This answers that call with an Arabic reading:
  * page readings go through engine.read_page (Apple Vision / RapidOCR / Tesseract);
  * every other call (--list-langs, --version) goes to the real Tesseract;
  * PdfCraft stores right-to-left words letter-reversed ("مسب" for "بسم"), so each Arabic
    word is handed over pre-reversed, which makes PdfCraft's search find it;
  * harakat are left out of the searchable text unless keep_harakat is set, because
    PdfCraft's search doesn't ignore them.
"""

from __future__ import annotations

import subprocess
import sys

from . import config, engine


def _reverse(text: str) -> str:
    # Whole grapheme clusters, so a harakah stays on its letter. Only words with RTL letters:
    # PdfCraft leaves digits (incl. ١٢٣) and Latin alone.
    if not engine.RTL_LETTER.search(text):
        return text
    clusters: list[str] = []
    for ch in text:
        if clusters and (0x064B <= ord(ch) <= 0x065F or ord(ch) in (0x0670,) or 0x0610 <= ord(ch) <= 0x061A
                         or 0x06D6 <= ord(ch) <= 0x06ED or 0x0300 <= ord(ch) <= 0x036F):
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return "".join(reversed(clusters))


def page_tsv(image: str, cfg: dict) -> str:
    W, H, lines = engine.read_page(image, cfg)
    lines = engine.clean_lines(lines, cfg.get("keep_harakat", False))
    out = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
           f"1\t1\t0\t0\t0\t0\t0\t0\t{W}\t{H}\t-1\t"]
    for n, ln in enumerate(lines, 1):
        l, t, w, h = ln.box
        out.append(f"4\t1\t1\t1\t{n}\t0\t{l}\t{t}\t{w}\t{h}\t-1\t")
        for j, wd in enumerate(ln.words, 1):
            l, t, w, h = wd.box
            text = _reverse(wd.text).replace("\t", " ")
            out.append(f"5\t1\t1\t1\t{n}\t{j}\t{l}\t{t}\t{w}\t{h}\t{wd.conf}\t{text}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cfg = config.load()
    if len(args) >= 2 and args[-1] == "tsv" and args[1] == "stdout":
        try:
            sys.stdout.buffer.write(page_tsv(args[0], cfg).encode("utf-8"))
            return 0
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"tesseract-for-pdfcraft: {e}\n")
            return 1
    exe = cfg.get("tesseract")
    if not exe:
        sys.stderr.write("tesseract-for-pdfcraft: the real tesseract wasn't found; run arabic-ocr-doctor\n")
        return 1
    return subprocess.run([exe, *args], env=config.tess_env(cfg), **config.no_window()).returncode


if __name__ == "__main__":
    sys.exit(main())
