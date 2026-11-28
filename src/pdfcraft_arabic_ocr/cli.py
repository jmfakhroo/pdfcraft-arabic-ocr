"""arabic-ocr: make scanned Arabic PDFs (or images) searchable, ready for PdfCraft.

Writes <name>.ocr.pdf (searchable copy, original untouched) and <name>.ocr.txt next to the
input. Uses ocrmypdf with this package's plugin, so the reading comes from engine.read_page.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, engine

IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic"}


def find_ocrmypdf() -> list[str] | None:
    exe = config.command_path("ocrmypdf")
    if exe.is_file():
        return [str(exe)]
    for c in ("/opt/homebrew/bin/ocrmypdf", "/usr/local/bin/ocrmypdf"):
        if Path(c).is_file():
            return [c]
    w = shutil.which("ocrmypdf")
    return [w] if w else None


def open_in_pdfcraft(path: Path) -> None:
    if config.SYSTEM == "Darwin":
        subprocess.run(["open", "-a", "PdfCraft", str(path)])
    elif config.SYSTEM == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for exe in (local / "Programs/PdfCraft/PdfCraft.exe", Path(r"C:\Program Files\PdfCraft\PdfCraft.exe")):
            if exe.is_file():
                subprocess.Popen([str(exe), str(path)])
                return
        os.startfile(str(path))  # noqa: S606 - the user's default PDF app
    else:
        exe = shutil.which("pdfcraft")
        subprocess.Popen([exe, str(path)] if exe else ["xdg-open", str(path)])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arabic-ocr",
        description="Make scanned Arabic PDFs or images searchable (writes NAME.ocr.pdf and NAME.ocr.txt).",
        epilog="Examples:  arabic-ocr book.pdf   |   arabic-ocr -o scan.jpg   |   arabic-ocr ~/Downloads/scans",
    )
    p.add_argument("inputs", nargs="+", help="PDFs, images, or folders of them")
    p.add_argument("--out", help="output file (one input) or folder (default NAME.ocr.pdf; for a folder: FOLDER-ocr)")
    p.add_argument("-l", "--lang", default=None, help="languages joined with + (default: ara). e.g. ara+eng")
    p.add_argument("-e", "--engine", choices=["auto", "vision", "rapidocr", "tesseract"], default=None,
                   help="auto (default): Apple Vision on macOS, RapidOCR on Windows/Linux, each with Tesseract filling gaps")
    p.add_argument("-k", "--keep-harakat", action="store_true",
                   help="keep harakat in the searchable text (default: left out, so 'الحمد' finds 'الحمدُ')")
    p.add_argument("-f", "--force", action="store_true", help="re-OCR every page, even pages that already have text")
    p.add_argument("-r", "--redo", action="store_true", help="replace an old OCR layer, keep real text")
    p.add_argument("-d", "--deskew", action="store_true", help="straighten clearly tilted scans first")
    p.add_argument("-c", "--clean", action="store_true", help="clean the scan before OCR (needs unpaper)")
    p.add_argument("--no-txt", action="store_true", help="don't write the .txt copy")
    p.add_argument("-o", "--open", action="store_true", help="open the result in PdfCraft")
    p.add_argument("-j", "--jobs", type=int, help="pages in parallel (default: all cores)")
    return p


def ocr_one(src: Path, dst: Path, a, cfg: dict, base_cmd: list[str], env: dict) -> bool:
    ext = src.suffix.lower()
    if ext != ".pdf" and ext not in IMAGES:
        print(f"skip (not a PDF or image): {src}", file=sys.stderr)
        return True
    cmd = [*base_cmd]
    if ext == ".pdf":
        cmd.append("--force-ocr" if a.force else "--redo-ocr" if a.redo else "--skip-text")
    else:
        cmd += ["--image-dpi", "300"]
    if not a.no_txt:
        cmd += ["--sidecar", str(dst.with_suffix(".txt"))]
    cmd += [str(src), str(dst)]
    print(f"OCR: {src}")
    rc = subprocess.run(cmd, env=env).returncode
    if rc == 0:
        print(f"  ✓ {dst}")
        if not a.no_txt:
            print(f"  ✓ {dst.with_suffix('.txt')}")
        return True
    if rc == 6:
        print(f"  already has text, skipped (use --force or --redo): {src}", file=sys.stderr)
        return True
    print(f"  ✗ failed ({rc}): {src}", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    config.utf8_output()
    a = build_parser().parse_args(argv)
    cfg = config.load()
    missing = [x for x in a.inputs if not Path(x).expanduser().exists()]
    if missing:
        print(f"arabic-ocr: not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    if a.out and len(a.inputs) > 1:
        print("arabic-ocr: --out works with one input only", file=sys.stderr)
        return 2
    ocrmypdf = find_ocrmypdf()
    if not ocrmypdf:
        print("arabic-ocr: ocrmypdf is missing; run arabic-ocr-doctor", file=sys.stderr)
        return 1
    if not cfg.get("tesseract"):
        print("arabic-ocr: tesseract is missing; run arabic-ocr-doctor", file=sys.stderr)
        return 1
    if a.deskew and a.redo:
        print("arabic-ocr: --deskew can't be combined with --redo", file=sys.stderr)
        return 2
    langs = a.lang or cfg.get("languages") or "ara"
    eng = a.engine or cfg.get("engine") or "auto"
    if eng == "auto":
        eng = engine.choose_engine(cfg)

    env = config.tess_env(cfg)
    env["ARABIC_OCR_ENGINE"] = eng
    env["ARABIC_OCR_KEEP_HARAKAT"] = "1" if (a.keep_harakat or cfg.get("keep_harakat")) else "0"
    # Tesseract's own folder must be findable by ocrmypdf (page orientation).
    env["PATH"] = str(Path(cfg["tesseract"]).parent) + os.pathsep + env.get("PATH", "")
    plugin = Path(__file__).with_name("plugin.py")
    base = [*ocrmypdf, "--plugin", str(plugin), "-l", langs, "--rotate-pages",
            "--output-type", "pdf", "--optimize", "1"]
    if a.jobs:
        base += ["--jobs", str(a.jobs)]
    if a.clean:
        base.append("--clean")
    if a.deskew:
        base.append("--deskew")

    ok = True
    for raw in a.inputs:
        src = Path(raw).expanduser()
        if src.is_dir():
            out = Path(a.out).expanduser() if a.out else src.with_name(src.name + "-ocr")
            out.mkdir(parents=True, exist_ok=True)
            files = sorted(p for p in src.iterdir() if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGES)
            if not files:
                print(f"arabic-ocr: no PDFs or images in {src}", file=sys.stderr)
                ok = False
                continue
            this = all([ocr_one(f, out / (f.stem + ".pdf"), a, cfg, base, env) for f in files])
        else:
            out = Path(a.out).expanduser() if a.out else src.with_name(src.stem + ".ocr.pdf")
            if out.suffix.lower() != ".pdf":
                out = out.with_name(out.name + ".pdf")
            this = ocr_one(src, out, a, cfg, base, env)
        ok &= this
        if a.open and this and out.is_file():
            open_in_pdfcraft(out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
