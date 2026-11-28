"""arabic-ocr-doctor: set up, check and repair Arabic OCR for PdfCraft.

    arabic-ocr-doctor            full report (repairs what it can)
    arabic-ocr-doctor --setup    first-time setup, used by the installers
    arabic-ocr-doctor --quiet    for login items: repair silently, notify on problems/updates

What it keeps working, on macOS, Linux and Windows:
  1. Tesseract and an Arabic/English/OSD model folder of our own (survives Tesseract updates)
  2. the OCR engine (Apple Vision on macOS, rebuilt from source if needed; RapidOCR elsewhere)
  3. tesseract-for-pdfcraft, tested exactly as PdfCraft runs it (empty environment)
  4. the arabic-ocr command
  5. PDFCRAFT_TESSERACT, the setting that points PdfCraft at the helper
  6. PdfCraft itself: still honours that setting; notices when PdfCraft was updated
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import config, engine

MODELS = {
    "ara": "https://github.com/tesseract-ocr/tessdata_best/raw/main/ara.traineddata",
    "eng": "https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata",
    "osd": "https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata",
}
ENV_NAME = "PDFCRAFT_TESSERACT"


class Report:
    def __init__(self, quiet: bool):
        self.quiet, self.problems, self.fixed = quiet, [], []
        self.log = config.data_dir() / "doctor.log"

    def _out(self, mark: str, msg: str) -> None:
        if not self.quiet:
            print(f"  {mark} {msg}")
        try:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {mark} {msg}\n")
        except OSError:
            pass

    def ok(self, m): self._out("✓", m)
    def fix(self, m): self.fixed.append(m); self._out("↻", m)
    def bad(self, m): self.problems.append(m); self._out("✗", m)
    def note(self, m): self._out("!", m)


def notify(title: str, msg: str) -> None:
    try:
        if config.SYSTEM == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Arabic OCR" subtitle "{title}"'],
                           capture_output=True, timeout=10)
        elif config.SYSTEM == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", f"Arabic OCR: {title}", msg], capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


# --- 1. Tesseract + models ---------------------------------------------------------------


def system_tessdata(tess: str) -> Path | None:
    try:
        first = subprocess.run([tess, "--list-langs"], capture_output=True, text=True, timeout=30)
        line = (first.stdout + first.stderr).splitlines()[0]
        if '"' in line:
            return Path(line.split('"')[1])
    except Exception:  # noqa: BLE001
        pass
    return None


def ensure_models(cfg: dict, r: Report) -> None:
    td = Path(cfg["tessdata"])
    td.mkdir(parents=True, exist_ok=True)
    sysdir = system_tessdata(cfg["tesseract"]) if cfg.get("tesseract") else None
    for lang, url in MODELS.items():
        f = td / f"{lang}.traineddata"
        if f.is_file() and f.stat().st_size > 1_000_000:
            continue
        if sysdir and (sysdir / f.name).is_file() and lang != "ara":
            shutil.copy2(sysdir / f.name, f)
        else:
            if not r.quiet:
                print(f"    downloading {f.name}…")
            tmp = f.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URLs above
            tmp.replace(f)
        r.fix(f"{f.name} installed in {td}")
    # Tesseract looks up its output configs ("tsv", "hocr", "txt") in <tessdata>/configs, so
    # our own folder needs them too, or "tesseract img stdout tsv" prints nothing.
    configs = td / "configs"
    configs.mkdir(exist_ok=True)
    wanted = {"tsv": "tessedit_create_tsv 1\n", "hocr": "tessedit_create_hocr 1\nhocr_font_info 0\n",
              "txt": "tessedit_create_txt 1\n"}
    for name, body in wanted.items():
        f = configs / name
        if not f.is_file():
            src = sysdir / "configs" / name if sysdir else None
            if src and src.is_file():
                shutil.copy2(src, f)
            else:
                f.write_text(body)
            r.fix(f"Tesseract config '{name}' added")
    r.ok(f"Tesseract models (ara, eng, osd) in {td}")


# --- 2. engine ---------------------------------------------------------------------------


def build_vision(cfg: dict, r: Report) -> bool:
    src = config.data_dir() / "vision-ocr.swift"
    out = config.data_dir() / "vision-ocr"
    if not src.is_file() or not shutil.which("xcrun"):
        return False
    res = subprocess.run(["xcrun", "swiftc", "-O", str(src), "-o", str(out)], capture_output=True, text=True)
    if res.returncode == 0:
        cfg["vision_ocr"] = str(out)
        r.fix("vision-ocr built from source")
        return True
    r.note("building vision-ocr failed: " + res.stderr.strip()[-200:])
    return False


def engine_reads(cfg: dict, name: str) -> bool:
    try:
        _, _, lines = engine.read_page(config.SELFTEST, cfg, "ara", name)
        return config.SELFTEST_WORD in " ".join(ln.text for ln in lines)
    except Exception:  # noqa: BLE001
        return False


def check_engine(cfg: dict, r: Report) -> None:
    if config.SYSTEM == "Darwin":
        if not engine_reads(cfg, "vision") and not (build_vision(cfg, r) and engine_reads(cfg, "vision")):
            r.bad("Apple text recognition (vision-ocr) isn't working; needs Xcode Command Line Tools")
        else:
            r.ok("Apple Vision text recognition reads Arabic (Tesseract fills its gaps)")
        return
    if engine.rapid_available() and engine_reads(cfg, "rapidocr"):
        r.ok("RapidOCR reads Arabic (Tesseract fills its gaps)")
    elif engine_reads(cfg, "tesseract"):
        r.bad("RapidOCR isn't working; falling back to Tesseract alone (lower quality)")
    else:
        r.bad("no OCR engine could read the test page")


# --- 3/4. helper and command -------------------------------------------------------------


def check_helper(cfg: dict, r: Report) -> None:
    exe = config.command_path("tesseract-for-pdfcraft")
    if not exe.is_file():
        r.bad(f"{exe} is missing; reinstall")
        return
    # Exactly how PdfCraft runs it: almost no environment.
    env = {"PATH": "/usr/bin:/bin" if config.SYSTEM != "Windows" else os.environ.get("SystemRoot", r"C:\Windows")}
    if config.SYSTEM == "Windows":
        env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    with tempfile.TemporaryDirectory() as tmp:
        env["TMP"] = env["TEMP"] = tmp
        probe = subprocess.run([str(exe), "--list-langs"], capture_output=True, env=env, cwd=tmp, timeout=60)
        res = subprocess.run([str(exe), str(config.SELFTEST), "stdout", "-l", "eng", "tsv"],
                             capture_output=True, env=env, cwd=tmp, timeout=600)
    if b"eng" not in probe.stdout + probe.stderr:
        r.bad("tesseract-for-pdfcraft doesn't answer --list-langs, so PdfCraft would reject it")
    elif "نيملاعلا" in res.stdout.decode("utf-8", "replace"):
        r.ok("PdfCraft's OCR route works (tested with PdfCraft's empty environment)")
    else:
        r.bad("tesseract-for-pdfcraft failed its test: " + res.stderr.decode("utf-8", "replace").strip()[-200:])


def check_command(r: Report) -> None:
    exe = config.command_path("arabic-ocr")
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "t.png"
        shutil.copy2(config.SELFTEST, img)
        res = subprocess.run([str(exe), str(img)], capture_output=True, timeout=900)
        txt = Path(tmp) / "t.ocr.txt"
        if res.returncode == 0 and txt.is_file() and config.SELFTEST_WORD in txt.read_text(encoding="utf-8"):
            r.ok("arabic-ocr command works")
        else:
            r.bad("arabic-ocr failed its test: " + (res.stderr or res.stdout).decode("utf-8", "replace").strip()[-300:])


# --- 5. PDFCRAFT_TESSERACT ---------------------------------------------------------------


def ensure_env(r: Report) -> None:
    helper = str(config.command_path("tesseract-for-pdfcraft"))
    if config.SYSTEM == "Darwin":
        cur = subprocess.run(["launchctl", "getenv", ENV_NAME], capture_output=True, text=True).stdout.strip()
        if cur != helper:
            subprocess.run(["launchctl", "setenv", ENV_NAME, helper])
            r.fix(f"{ENV_NAME} set (restart PdfCraft if it's open)")
        else:
            r.ok("PdfCraft is pointed at the Arabic helper")
    elif config.SYSTEM == "Windows":
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                cur = winreg.QueryValueEx(k, ENV_NAME)[0]
            except FileNotFoundError:
                cur = None
            if cur != helper:
                winreg.SetValueEx(k, ENV_NAME, 0, winreg.REG_SZ, helper)
                ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
                r.fix(f"{ENV_NAME} set for your user (restart PdfCraft if it's open)")
            else:
                r.ok("PdfCraft is pointed at the Arabic helper")
    else:  # Linux: desktop sessions read environment.d; terminals read ~/.profile
        home = Path.home()
        envd = home / ".config/environment.d/90-pdfcraft-arabic-ocr.conf"
        line = f"{ENV_NAME}={helper}\n"
        changed = False
        if not envd.is_file() or envd.read_text() != line:
            envd.parent.mkdir(parents=True, exist_ok=True)
            envd.write_text(line)
            changed = True
        prof = home / ".profile"
        text = prof.read_text() if prof.is_file() else ""
        export = f'export {ENV_NAME}="{helper}"  # pdfcraft-arabic-ocr'
        if export not in text:
            lines = [ln for ln in text.splitlines() if "# pdfcraft-arabic-ocr" not in ln]
            prof.write_text("\n".join(lines + [export]) + "\n")
            changed = True
        if changed:
            r.fix(f"{ENV_NAME} set in {envd} and ~/.profile (log out and in, or start PdfCraft from a new terminal)")
        elif os.environ.get(ENV_NAME) not in (None, helper):
            r.note(f"this session still has an old {ENV_NAME}; log out and in")
        else:
            r.ok("PdfCraft is pointed at the Arabic helper")


# --- 6. PdfCraft ---------------------------------------------------------------------------


def pdfcraft_binary() -> Path | None:
    c: list[Path] = []
    if config.SYSTEM == "Darwin":
        c.append(Path("/Applications/PdfCraft.app/Contents/MacOS/PdfCraft"))
        c.append(Path.home() / "Applications/PdfCraft.app/Contents/MacOS/PdfCraft")
    elif config.SYSTEM == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        c += [local / "Programs/PdfCraft/PdfCraft.exe", Path(r"C:\Program Files\PdfCraft\PdfCraft.exe")]
    else:
        for name in ("pdfcraft", "PdfCraft"):
            w = shutil.which(name)
            if w:
                c.append(Path(w).resolve())
        c += [Path("/usr/bin/pdfcraft"), Path("/opt/PdfCraft/pdfcraft"), Path.home() / ".local/bin/pdfcraft"]
    return next((p for p in c if p.is_file()), None)


def check_pdfcraft(r: Report) -> None:
    exe = pdfcraft_binary()
    if not exe:
        r.note("PdfCraft wasn't found; the arabic-ocr command works without it")
        return
    with exe.open("rb") as f:
        found, tail = False, b""
        while chunk := f.read(8 << 20):
            if ENV_NAME.encode() in tail + chunk:
                found = True
                break
            tail = chunk[-64:]
    st = exe.stat()
    version = f"{st.st_size}-{int(st.st_mtime)}"
    if config.SYSTEM == "Darwin":
        plist = exe.parent.parent / "Info.plist"
        res = subprocess.run(["defaults", "read", str(plist.with_suffix("")), "CFBundleShortVersionString"],
                             capture_output=True, text=True)
        version = res.stdout.strip() or version
    if found:
        r.ok(f"PdfCraft {version if '.' in version else ''} supports {ENV_NAME}".replace("  ", " "))
    else:
        r.bad(f"this PdfCraft no longer mentions {ENV_NAME}: the in-app Arabic route may be gone")
    state = config.data_dir() / "pdfcraft-version"
    last = state.read_text().strip() if state.is_file() else None
    if last and last != version:
        r.note(f"PdfCraft was updated (from {last} to {version})")
        notify("PdfCraft was updated", f"Arabic OCR checked: {len(r.problems)} problem(s). OCR one page and search a word to confirm.")
    state.write_text(version)


# --- main --------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    config.utf8_output()
    p = argparse.ArgumentParser(prog="arabic-ocr-doctor", description="Set up, check and repair Arabic OCR for PdfCraft.")
    p.add_argument("--setup", action="store_true", help="first-time setup (installers run this)")
    p.add_argument("--quiet", action="store_true", help="only log; notify on problems")
    a = p.parse_args(argv)
    r = Report(a.quiet)
    if not a.quiet:
        print("Arabic OCR for PdfCraft: checking…")

    cfg = config.load()
    if not cfg.get("tesseract"):
        r.bad("Tesseract isn't installed (see the README for your system)")
    else:
        r.ok(f"Tesseract: {cfg['tesseract']}")
        try:
            ensure_models(cfg, r)
        except Exception as e:  # noqa: BLE001
            r.bad(f"couldn't get Tesseract's Arabic model: {e}")
    if a.setup and config.SYSTEM == "Darwin":
        build_vision(cfg, r)
    config.save(cfg)
    check_engine(cfg, r)
    config.save(cfg)
    check_helper(cfg, r)
    check_command(r)
    ensure_env(r)
    check_pdfcraft(r)

    if r.problems:
        if not a.quiet:
            print(f"Problems: {len(r.problems)}")
        notify("Needs attention", r.problems[0])
        return 1
    if not a.quiet:
        print("All good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
