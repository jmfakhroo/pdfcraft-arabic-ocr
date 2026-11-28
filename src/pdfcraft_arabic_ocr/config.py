"""Where things live, independent of $HOME.

PdfCraft starts its "tesseract" with an almost empty environment (no HOME, no USERPROFILE),
so every path is derived from this package's own install: the installer puts a virtualenv at
<DATA>/venv, and <DATA> holds config.json, tessdata/ and (macOS) vision-ocr.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path

SYSTEM = platform.system()  # "Darwin", "Linux", "Windows"
SELFTEST = Path(__file__).with_name("selftest.png")
SELFTEST_WORD = "العالمين"  # appears in selftest.png


def utf8_output() -> None:
    """Print ✓ and Arabic file names even when output is piped (Windows would use cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def data_dir() -> Path:
    env = os.environ.get("ARABIC_OCR_HOME")
    if env:
        return Path(env)
    prefix = Path(sys.prefix)
    if prefix.name == "venv":  # the installer's layout: <DATA>/venv
        return prefix.parent
    if SYSTEM == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "arabic-ocr"
    return Path.home() / ".local/share/arabic-ocr"


def scripts_dir() -> Path:
    """Where pip put this package's commands (tesseract-for-pdfcraft, arabic-ocr…)."""
    return Path(sys.prefix) / ("Scripts" if SYSTEM == "Windows" else "bin")


def command_path(name: str) -> Path:
    return scripts_dir() / (name + (".exe" if SYSTEM == "Windows" else ""))


DEFAULTS = {
    "engine": "auto",  # auto | vision (macOS) | rapidocr | tesseract
    "languages": "ara",  # Tesseract-style codes joined with +
    "keep_harakat": False,  # keep harakat in searchable text
    "tesseract": None,  # absolute path to the real tesseract
    "tessdata": None,  # folder with ara/eng/osd .traineddata
    "vision_ocr": None,  # macOS: absolute path to vision-ocr
    "llama_server": None,  # absolute path to llama.cpp's llama-server (for the surya engine)
    "surya_port": 8765,  # local port of Surya's model server
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = data_dir() / "config.json"
    try:
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if not cfg["tessdata"]:
        cfg["tessdata"] = str(data_dir() / "tessdata")
    if not cfg["tesseract"] or not Path(cfg["tesseract"]).is_file():
        cfg["tesseract"] = find_tesseract()
    if SYSTEM == "Darwin" and not cfg["vision_ocr"]:
        p = data_dir() / "vision-ocr"
        cfg["vision_ocr"] = str(p) if p.is_file() else None
    if not cfg["llama_server"] or not Path(cfg["llama_server"]).is_file():
        cfg["llama_server"] = find_llama_server()
    return cfg


def save(cfg: dict) -> None:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    keep = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    (d / "config.json").write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")


def find_tesseract() -> str | None:
    candidates = [
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Programs/Tesseract-OCR/tesseract.exe"))
    for c in candidates:
        if Path(c).is_file():
            return c
    return shutil.which("tesseract")


def find_llama_server() -> str | None:
    """llama.cpp's server, as installed by winget, Homebrew or a package manager."""
    name = "llama-server.exe" if SYSTEM == "Windows" else "llama-server"
    candidates: list[Path] = [data_dir() / "llama-cuda" / name]  # a CUDA build unpacked here wins
    if SYSTEM == "Windows":
        # %LOCALAPPDATA% may be missing from the environment (PdfCraft), so go from our own folder.
        local = Path(os.environ.get("LOCALAPPDATA") or data_dir().parent)
        candidates += sorted((local / "Microsoft/WinGet/Packages").glob("ggml.llamacpp*/" + name))
        candidates.append(local / "Microsoft/WinGet/Links" / name)
    else:
        candidates += [Path("/opt/homebrew/bin") / name, Path("/usr/local/bin") / name, Path("/usr/bin") / name]
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("llama-server")


def tess_env(cfg: dict) -> dict:
    """Environment for running Tesseract with our own Arabic model folder."""
    env = dict(os.environ)
    if cfg.get("tessdata") and Path(cfg["tessdata"]).is_dir():
        env["TESSDATA_PREFIX"] = cfg["tessdata"]
    env.setdefault("OMP_THREAD_LIMIT", "1")
    return env


def no_window() -> dict:
    """subprocess kwargs: on Windows, don't flash a console window for each page."""
    if SYSTEM == "Windows":
        import subprocess

        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}
