"""Surya 2.5 OCR (datalab-to/surya-ocr-2.5) through a local llama.cpp server.

Surya is a small vision-language model. It reads old and vocalized Arabic print far better
than RapidOCR or Tesseract, but needs a graphics card to be fast. On an RTX 5070 Ti with the
CUDA build of llama.cpp: about 4.5 s a page one page at a time (PdfCraft's own OCR) and about
1.2 s a page over a whole file (arabic-ocr). This module needs only two things on disk: the
`llama-server` program from llama.cpp, and Surya's two GGUF model files in <DATA>/models. It
talks to the server over 127.0.0.1 with the standard library, so the surya-ocr Python package
is not required.

The server is started on first use and left running; a small watcher stops it after it has
been idle for a few minutes, so PdfCraft's page-by-page calls don't reload the model each time.

The prompt and the image sizing rule are Surya's own (surya/inference, Apache 2.0): the model
was trained with exactly that wording. The model weights have their own licence (free for
personal use and research; see the model card).
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

MODEL_ALIAS = "datalab-to/surya-ocr-2.5"
MODEL_FILES = ("surya-2.5.gguf", "surya-2.5-mmproj.gguf")
MODEL_URL = "https://huggingface.co/datalab-to/surya-ocr-2.5-gguf/resolve/main/"
PROMPT = ("OCR this image to HTML. Each block is a div with data-label and data-bbox "
          "(x0 y0 x1 y1, normalized 0-1000).")
FAST_MODEL = "surya-2.5-Q8_0.gguf"  # made locally by llama-quantize; same accuracy in our test, faster
MAX_TOKENS = 12288
CTX_PER_SLOT = 12288
# Measured on an RTX 5070 Ti over 24 pages: 4 slots was the fastest and steadiest (more slots
# were slower), and 3000 image tokens read as well as the default 4096 but 15% faster.
SLOTS = 4  # pages read at once
IMAGE_TOKENS = 3000  # upper limit on how finely the page image is cut up
IDLE_SECONDS = 300  # stop the server this long after the last page

_HEADER = re.compile(r"<\|([A-Za-z][A-Za-z-]*)\|>" + r"<\|(\d{1,4})\|>" * 4)
_SPECIAL = re.compile(r"<\|[^|<>]*[|!]>")
_BREAK = re.compile(r"<br\s*/?>|</(?:p|div|li|tr|h[1-6]|pre|caption)>", re.I)
_TAG = re.compile(r"<[^<>]+>")
_SKIP = {"Figure", "Image", "Diagram", "Blank-Page"}
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# --- files -------------------------------------------------------------------------------


def model_dir() -> Path:
    return config.data_dir() / "models"


def _present(p: Path) -> bool:
    return p.is_file() and p.stat().st_size > 10_000_000


def model_paths() -> tuple[Path, Path] | None:
    """(model, image projector); the faster Q8 copy of the model when it has been made."""
    model, mmproj = (model_dir() / name for name in MODEL_FILES)
    fast = model_dir() / FAST_MODEL
    if _present(fast) and _present(mmproj):
        return fast, mmproj
    return (model, mmproj) if _present(model) and _present(mmproj) else None


def make_fast_model(cfg: dict) -> bool:
    """Make the Q8 copy with llama.cpp's own llama-quantize (a few seconds, 600 MB)."""
    fast, source = model_dir() / FAST_MODEL, model_dir() / MODEL_FILES[0]
    if _present(fast):
        return True
    server = Path(cfg.get("llama_server") or "")
    tool = server.with_name(server.name.replace("llama-server", "llama-quantize"))
    if not tool.is_file() or not _present(source):
        return False
    tmp = fast.with_suffix(".part")
    res = subprocess.run([str(tool), str(source), str(tmp), "Q8_0"], capture_output=True, env=_child_env(),
                         **config.no_window())
    if res.returncode != 0 or not _present(tmp):
        return False
    tmp.replace(fast)
    return True


def download_models(progress=print) -> None:
    """Fetch the two GGUF files (about 1.3 GB) into <DATA>/models."""
    model_dir().mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        dst = model_dir() / name
        if _present(dst):
            continue
        progress(f"    downloading {name}…")
        tmp = dst.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL + name, tmp)  # noqa: S310 - fixed https URL
        tmp.replace(dst)


def available(cfg: dict) -> bool:
    return bool(cfg.get("llama_server")) and Path(cfg["llama_server"]).is_file() and model_paths() is not None


# --- server ------------------------------------------------------------------------------


def _base(cfg: dict) -> str:
    return f"http://127.0.0.1:{int(cfg.get('surya_port') or 8765)}"


def _get(url: str, timeout: float = 1.5):
    with _NO_PROXY.open(url, timeout=timeout) as r:
        return json.load(r)


def healthy(cfg: dict) -> bool:
    """True when our model is loaded and answering on the port (not some other program)."""
    try:
        _get(_base(cfg) + "/health")
        models = _get(_base(cfg) + "/v1/models")
        return any(m.get("id") == MODEL_ALIAS for m in models.get("data", []))
    except (OSError, ValueError):
        return False


def _detached() -> dict:
    """Popen kwargs so the child outlives us and shows no window."""
    if config.SYSTEM == "Windows":
        return {"creationflags": 0x08000000 | 0x00000200}  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def _popen(cmd: list[str], **kw) -> subprocess.Popen:
    kw = {"stdin": subprocess.DEVNULL, "close_fds": True, **_detached(), **kw}
    if config.SYSTEM == "Windows":
        try:  # leave the caller's job object if it would kill us with it
            return subprocess.Popen(cmd, **{**kw, "creationflags": kw["creationflags"] | 0x01000000})
        except OSError:
            pass
    return subprocess.Popen(cmd, **kw)


def _child_env() -> dict:
    """PdfCraft runs its helper with an almost empty environment; the server and the
    graphics driver need the basic Windows variables back."""
    env = dict(os.environ)
    if config.SYSTEM == "Windows":
        root = env.get("SystemRoot") or env.get("windir") or r"C:\Windows"
        env.setdefault("SystemRoot", root)
        env.setdefault("windir", root)
        env["PATH"] = os.pathsep.join(filter(None, [env.get("PATH"), rf"{root}\System32", root]))
        tmp = config.data_dir() / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env.setdefault("TEMP", str(tmp))
        env.setdefault("TMP", str(tmp))
    return env


def _spawn(cfg: dict) -> subprocess.Popen:
    paths = model_paths()
    if not paths or not cfg.get("llama_server"):
        raise RuntimeError("Surya isn't installed (llama-server or its model files are missing); run arabic-ocr-doctor")
    d = config.data_dir()
    cmd = [cfg["llama_server"], "-m", str(paths[0]), "--mmproj", str(paths[1]), "-ngl", "99",
           "--host", "127.0.0.1", "--port", str(int(cfg.get("surya_port") or 8765)),
           "--parallel", str(SLOTS), "--ctx-size", str(SLOTS * CTX_PER_SLOT),
           "--image-max-tokens", str(IMAGE_TOKENS), "--alias", MODEL_ALIAS, "--jinja", "--special"]
    with open(d / "surya-server.log", "wb") as log:
        proc = _popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=_child_env(), cwd=str(d))
    (d / "surya-server.pid").write_text(str(proc.pid))
    touch()
    _popen([sys.executable, "-m", "pdfcraft_arabic_ocr.surya", "--watch", str(proc.pid)],
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_child_env(), cwd=str(d))
    return proc


def touch() -> None:
    try:
        (config.data_dir() / "surya-last-used").write_text(str(time.time()))
    except OSError:
        pass


def ensure(cfg: dict, wait: float = 240) -> None:
    """Make sure the server is up. Safe to call from many processes at once."""
    if healthy(cfg):
        return
    lock = config.data_dir() / "surya-server.lock"
    deadline = time.time() + wait
    while time.time() < deadline:
        if healthy(cfg):
            return
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:  # another process is starting it
            try:
                if time.time() - lock.stat().st_mtime > wait:
                    lock.unlink()
            except OSError:
                pass
            time.sleep(1)
            continue
        try:
            if not healthy(cfg):
                proc = _spawn(cfg)
                while time.time() < deadline and proc.poll() is None and not healthy(cfg):
                    time.sleep(0.5)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass
        break
    if not healthy(cfg):
        raise RuntimeError(f"Surya's model server didn't start; see {config.data_dir() / 'surya-server.log'}")


def stop(cfg: dict | None = None) -> bool:
    """Stop the server we started. Returns True if one was stopped."""
    pid_file = config.data_dir() / "surya-server.pid"
    try:
        pid = int(pid_file.read_text())
        if not healthy(cfg or config.load()):  # already gone; the pid may belong to something else now
            pid_file.unlink()
            return False
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()
        return True
    except (OSError, ValueError):
        return False


def _watch(pid: int) -> None:
    """Stop the server once nothing has used it for IDLE_SECONDS."""
    d = config.data_dir()
    while True:
        time.sleep(20)
        try:
            if int((d / "surya-server.pid").read_text()) != pid:
                return  # a newer server has its own watcher
            idle = time.time() - float((d / "surya-last-used").read_text())
        except (OSError, ValueError):
            return
        if idle > IDLE_SECONDS:
            stop()
            return


# --- reading a page ------------------------------------------------------------------------


def _fit(im):
    """Surya's sizing rule: at most 3072x2048 pixels of area, sides a multiple of 28."""
    from PIL import Image

    w, h = im.size
    grid, most, least = 28, 3072 * 2048, 1792 * 28
    scale = (most / (w * h)) ** 0.5 if w * h > most else (least / (w * h)) ** 0.5 if w * h < least else 1.0
    wb, hb = max(1, round(w * scale / grid)), max(1, round(h * scale / grid))
    while wb * hb * grid * grid > most and (wb > 1 or hb > 1):
        if hb == 1 or (wb > 1 and abs((wb - 1) / hb - w / h) < abs(wb / (hb - 1) - w / h)):
            wb -= 1
        else:
            hb -= 1
    size = (wb * grid, hb * grid)
    return im if size == (w, h) else im.resize(size, Image.Resampling.LANCZOS)


def _ask(cfg: dict, image_b64: str, temperature: float, top_p: float) -> tuple[str, str]:
    body = {
        "model": MODEL_ALIAS, "max_tokens": MAX_TOKENS, "temperature": temperature, "top_p": top_p,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
            {"type": "text", "text": PROMPT},
        ]}],
    }
    req = urllib.request.Request(_base(cfg) + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with _NO_PROXY.open(req, timeout=900) as r:
        choice = json.load(r)["choices"][0]
    return choice["message"].get("content") or "", choice.get("finish_reason") or ""


def html_to_text(fragment: str) -> str:
    text = _TAG.sub("", _SPECIAL.sub("", _BREAK.sub("\n", fragment)))
    return "\n".join(ln.strip() for ln in html.unescape(text).splitlines() if ln.strip())


def parse(raw: str, width: int, height: int) -> list[tuple[str, tuple[int, int, int, int], str]]:
    """Model output -> [(label, (left, top, width, height) in image pixels, text)]."""
    heads = list(_HEADER.finditer(raw))
    if not heads:
        text = html_to_text(raw)
        return [("Text", (0, 0, width, height), text)] if text else []
    out = []
    for i, m in enumerate(heads):
        label = m.group(1)
        x0, y0, x1, y1 = (min(1000, int(g)) for g in m.groups()[1:])
        text = html_to_text(raw[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(raw)])
        if label in _SKIP or not text or x1 <= x0 or y1 <= y0:
            continue
        box = (round(x0 * width / 1000), round(y0 * height / 1000),
               max(1, round((x1 - x0) * width / 1000)), max(1, round((y1 - y0) * height / 1000)))
        out.append((label, box, text))
    return out


def ocr(image, cfg: dict):
    """(width, height, blocks) for one page image; blocks as returned by parse()."""
    from PIL import Image

    ensure(cfg)
    with Image.open(image) as im:
        width, height = im.size
        buf = io.BytesIO()
        _fit(im.convert("RGB")).save(buf, format="PNG", compress_level=1)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    touch()
    raw, why = _ask(cfg, b64, 0.0, 0.1)
    if why == "length":  # ran to the token limit: almost always a repetition loop, so try once more
        raw2, why2 = _ask(cfg, b64, 0.3, 0.95)
        if why2 != "length":
            raw = raw2
    touch()
    return width, height, parse(raw, width, height)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--watch":
        _watch(int(sys.argv[2]))
    elif len(sys.argv) == 2 and sys.argv[1] == "--stop":
        print("stopped" if stop() else "no server running")
