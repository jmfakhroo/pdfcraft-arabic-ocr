"""Read one page image into lines of words.

Engines, best first:
  vision    macOS only: Apple's Vision text recognition (the Live Text engine), through the
            vision-ocr helper, which already fills its gaps with Tesseract.
  rapidocr  Windows/Linux (and macOS if installed): RapidOCR's PP-OCRv5 Arabic model.
            Lines it reads badly (score < WEAK) or misses are filled with Tesseract's reading.
  tesseract Tesseract's Arabic model alone.
  surya     opt-in (set "engine": "surya" in config.json): Surya 2.5 through a local
            llama.cpp server, see surya.py. Much more accurate on old and vocalized print,
            but needs a graphics card. Tesseract supplies the line positions.

Everything here returns lines in reading order with word boxes in image pixels.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config

WEAK = 0.85  # RapidOCR line score below which Tesseract may replace the line
TESS_MIN_CONF = 55  # Tesseract line mean confidence needed to be used at all

HARAKAT = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
BIDI_MARKS = re.compile("[‎‏‪-‮⁦-⁩]")
RTL_LETTER = re.compile("[֐-׿ؠ-يٮ-ۓۺ-ۿݐ-ࣿיִ-﷿ﹰ-﻿]")
ARABIC_LETTER = re.compile("[ؠ-يٮ-ۓ]")
JUNK = set("%!#$&*@^_=<>|~\\")

VISION_LANGS = {
    "ara": "ar-SA", "eng": "en-US", "fra": "fr-FR", "deu": "de-DE", "spa": "es-ES",
    "ita": "it-IT", "por": "pt-BR", "rus": "ru-RU", "tur": "tr-TR", "ind": "id-ID",
    "msa": "ms-MY", "hin": "hi-IN", "urd": "ar-SA", "fas": "ar-SA",
}


@dataclass
class Word:
    text: str
    box: tuple[int, int, int, int]  # left, top, width, height
    conf: int


@dataclass
class Line:
    box: tuple[int, int, int, int]
    words: list[Word] = field(default_factory=list)
    score: float = 1.0  # 0..1
    source: str = ""

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


class EngineError(RuntimeError):
    pass


# --- helpers ---------------------------------------------------------------------------


def _junk_count(s: str) -> int:
    return sum(c in JUNK for c in s)


def _is_junk_word(s: str) -> bool:
    j = _junk_count(s)
    return j > 0 and j * 2 >= len(s)


def same_line(a, b) -> bool:
    """Mostly overlapping vertically and touching horizontally."""
    top, bottom = max(a[1], b[1]), min(a[1] + a[3], b[1] + b[3])
    left, right = max(a[0], b[0]), min(a[0] + a[2], b[0] + b[2])
    if bottom <= top or right <= left:
        return False
    return bottom - top >= 0.5 * max(1, min(a[3], b[3]))


def _split_words(text: str, box, score: float) -> list[Word]:
    """Words of a line, with boxes shared out by length (right-to-left for Arabic)."""
    words = text.split()
    if not words:
        return []
    l, t, w, h = box
    rtl = bool(RTL_LETTER.search(text))
    total = sum(len(x) for x in words) + len(words) - 1
    out, pos = [], 0
    for x in words:
        a, b = pos / total, (pos + len(x)) / total
        left = l + w * (1 - b) if rtl else l + w * a
        out.append(Word(x, (round(left), t, max(1, round(w * (b - a))), h), round(score * 100)))
        pos += len(x) + 1
    return out


def image_size(image: Path) -> tuple[int, int]:
    from PIL import Image  # installed with ocrmypdf / rapidocr

    with Image.open(image) as im:
        return im.size


# --- Tesseract ---------------------------------------------------------------------------


def tesseract_page(image: Path, cfg: dict, langs: str) -> tuple[int, int, list[Line]]:
    exe = cfg.get("tesseract")
    if not exe:
        raise EngineError("tesseract not found")
    res = subprocess.run(
        [exe, str(image), "stdout", "-l", langs, "tsv"],
        capture_output=True, env=config.tess_env(cfg), timeout=300, **config.no_window(),
    )
    if res.returncode != 0:
        raise EngineError(res.stderr.decode("utf-8", "replace").strip()[-300:])
    W = H = 0
    order: list[str] = []
    lines: dict[str, Line] = {}
    for row in res.stdout.decode("utf-8", "replace").splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12:
            continue
        try:
            l, t, w, h = (int(x) for x in f[6:10])
            conf = float(f[10])
        except ValueError:
            continue
        key = ".".join(f[2:5])
        if f[0] == "1":
            W, H = w, h
        elif f[0] == "4":
            lines[key] = Line((l, t, w, h), source="tesseract")
            order.append(key)
        elif f[0] == "5" and conf >= 0 and f[11].strip() and key in lines:
            lines[key].words.append(Word(f[11].strip(), (l, t, w, h), round(conf)))
    out = []
    for k in order:
        ln = lines[k]
        if ln.words:
            ln.score = sum(w.conf for w in ln.words) / len(ln.words) / 100
            out.append(ln)
    return W, H, out


def _usable_tesseract(lines: list[Line]) -> list[Line]:
    """Tesseract lines worth trusting: Arabic text, decent confidence (drops its noise in
    calligraphy, ornaments and pictures)."""
    keep = []
    for ln in lines:
        arabic = [w for w in ln.words if ARABIC_LETTER.search(w.text)]
        if arabic and ln.score * 100 >= TESS_MIN_CONF and len(arabic) * 2 >= len(ln.words):
            keep.append(ln)
    return keep


# --- Apple Vision (macOS) ------------------------------------------------------------------


def vision_page(image: Path, cfg: dict, langs: str) -> tuple[int, int, list[Line]]:
    exe = cfg.get("vision_ocr")
    if not exe or not Path(exe).is_file():
        raise EngineError("vision-ocr not installed")
    env = config.tess_env(cfg)
    vl = [VISION_LANGS[c] for c in langs.split("+") if c in VISION_LANGS]
    env["VISION_OCR_LANGS"] = ",".join(dict.fromkeys(vl)) or "ar-SA"
    env["VISION_OCR_TESS_LANGS"] = langs
    res = subprocess.run([exe, str(image), "tsv"], capture_output=True, env=env, timeout=600, **config.no_window())
    if res.returncode != 0:
        raise EngineError(res.stderr.decode("utf-8", "replace").strip()[-300:])
    W = H = 0
    lines: dict[int, Line] = {}
    for row in res.stdout.decode("utf-8").splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12:
            continue
        l, t, w, h = (int(x) for x in f[6:10])
        if f[0] == "1":
            W, H = w, h
        elif f[0] == "4":
            lines[int(f[4])] = Line((l, t, w, h), source="vision")
        elif f[0] == "5" and f[11]:
            lines.setdefault(int(f[4]), Line((l, t, w, h), source="vision")).words.append(
                Word(f[11], (l, t, w, h), int(float(f[10])))
            )
    return W, H, [lines[k] for k in sorted(lines) if lines[k].words]


# --- RapidOCR ----------------------------------------------------------------------------

_rapid = None


def rapid_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _rapid_engine():
    global _rapid
    if _rapid is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        _rapid = RapidOCR(params={
            "Rec.lang_type": LangRec.ARABIC,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Global.log_level": "error",
        })
    return _rapid


def rapid_page(image: Path, cfg: dict, langs: str) -> tuple[int, int, list[Line]]:
    W, H = image_size(image)
    r = _rapid_engine()(str(image))
    lines = []
    for quad, text, score in zip(r.boxes if r.boxes is not None else [], r.txts or [], r.scores or []):
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        box = (round(min(xs)), round(min(ys)), round(max(xs) - min(xs)), round(max(ys) - min(ys)))
        ln = Line(box, _split_words(BIDI_MARKS.sub("", text), box, float(score)), float(score), "rapidocr")
        if ln.words:
            lines.append(ln)
    lines.sort(key=lambda x: x.box[1])
    return W, H, lines


def merge(primary: list[Line], tess: list[Line]) -> list[Line]:
    """Keep the primary engine's lines; let Tesseract fill missing lines and replace weak or
    garbled ones when it is more confident there."""

    def bad(ln: Line) -> bool:
        return _junk_count(ln.text) >= 2 or ln.score < WEAK

    good = [p for p in primary if not bad(p)]
    weak = [p for p in primary if bad(p)]
    added = []
    for t in _usable_tesseract(tess):
        if any(same_line(g.box, t.box) for g in good):
            continue
        rivals = [w for w in weak if same_line(w.box, t.box)]
        if rivals and max(r.score for r in rivals) >= t.score and not any(_junk_count(r.text) >= 2 for r in rivals):
            continue  # the weak primary line is still the better reading
        weak = [w for w in weak if w not in rivals]
        added.append(t)
    out = good + weak + added
    out.sort(key=lambda x: x.box[1])
    return out


# --- Surya (llama.cpp) ---------------------------------------------------------------------


def _rows(lines: list[Line]) -> list[tuple[tuple[int, int, int, int], int]]:
    """Group line boxes that sit side by side (two hemistichs, say) into rows, top to bottom.
    Each row is (box, weight), the weight being how many letters Tesseract saw on it."""
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda x: x.box[1] + x.box[3] / 2):
        for row in rows:
            top = max(r.box[1] for r in row)
            bottom = min(r.box[1] + r.box[3] for r in row)
            if min(bottom, ln.box[1] + ln.box[3]) - max(top, ln.box[1]) >= 0.5 * min(bottom - top, ln.box[3]):
                row.append(ln)
                break
        else:
            rows.append([ln])
    out = []
    for row in rows:
        left, top = min(r.box[0] for r in row), min(r.box[1] for r in row)
        right, bottom = max(r.box[0] + r.box[2] for r in row), max(r.box[1] + r.box[3] for r in row)
        weight = sum(len(w.text) for r in row for w in r.words)
        out.append(((left, top, right - left, bottom - top), max(1, weight)))
    return out


def place_blocks(blocks, tess: list[Line]) -> list[Line]:
    """Surya gives the text of each block with one box around the block. A searchable PDF
    needs every word near its place, so the block's words are shared out over the text lines
    Tesseract found inside that box, in proportion to how much Tesseract saw on each line.
    Tesseract's reading is thrown away; only its line positions are used."""
    heights = sorted(t.box[3] for t in tess)
    typical = heights[len(heights) // 2] if heights else 0
    free = list(tess)
    out: list[Line] = []
    for _label, (l, t, w, h), text in blocks:
        words = text.split()
        if not words:
            continue
        inside = [x for x in free if l - 5 <= x.box[0] + x.box[2] / 2 <= l + w + 5
                  and t - 5 <= x.box[1] + x.box[3] / 2 <= t + h + 5]
        free = [x for x in free if x not in inside]
        rows = _rows(inside)
        if not rows:  # Tesseract saw nothing here: cut the block into even rows
            n = max(1, min(len(words), round(h / typical))) if typical else 1
            rows = [((l, round(t + i * h / n), w, max(1, round(h / n))), 1) for i in range(n)]
        total, done, seen = sum(wt for _, wt in rows), 0, 0
        for box, wt in rows:
            seen += wt
            upto = len(words) if seen >= total else round(len(words) * seen / total)
            part = words[done:upto]
            done = max(done, upto)
            if part:
                out.append(Line(box, _split_words(" ".join(part), box, 0.95), 0.95, "surya"))
    out.sort(key=lambda x: x.box[1])
    return out


def surya_page(image: Path, cfg: dict, langs: str) -> tuple[int, int, list[Line]]:
    from . import surya

    W, H, blocks = surya.ocr(image, cfg)
    try:
        _, _, tess = tesseract_page(image, cfg, langs)
    except Exception:  # noqa: BLE001 - positions are a nicety; the text is what matters
        tess = []
    return W, H, place_blocks(blocks, tess)


# --- entry point ---------------------------------------------------------------------------


def choose_engine(cfg: dict) -> str:
    e = cfg.get("engine", "auto")
    if e != "auto":
        return e
    if config.SYSTEM == "Darwin" and cfg.get("vision_ocr") and Path(cfg["vision_ocr"]).is_file():
        return "vision"
    if rapid_available():
        return "rapidocr"
    return "tesseract"


def read_page(image, cfg: dict | None = None, langs: str | None = None, engine: str | None = None):
    """(width, height, lines) for one page image. Falls back to Tesseract if the chosen
    engine fails."""
    cfg = cfg or config.load()
    langs = langs or cfg.get("languages") or "ara"
    image = Path(image)
    engine = engine or choose_engine(cfg)
    try:
        if engine == "vision":
            return vision_page(image, cfg, langs)
        if engine == "surya":
            return surya_page(image, cfg, langs)
        if engine == "rapidocr":
            W, H, lines = rapid_page(image, cfg, langs)
            try:
                _, _, tess = tesseract_page(image, cfg, langs)
            except EngineError:
                tess = []
            return W, H, merge(lines, tess)
    except Exception:  # noqa: BLE001 - any engine failure falls back to Tesseract
        if engine == "tesseract":
            raise
    return tesseract_page(image, cfg, langs)


def clean_lines(lines: list[Line], keep_harakat: bool) -> list[Line]:
    """Text as it should be stored: no bidi marks, no junk words, harakat optional."""
    out = []
    for ln in lines:
        words = []
        for w in ln.words:
            t = BIDI_MARKS.sub("", w.text)
            if not keep_harakat:
                t = HARAKAT.sub("", t)
            if t.strip() and not _is_junk_word(t):
                words.append(Word(t, w.box, w.conf))
        if words:
            out.append(Line(ln.box, words, ln.score, ln.source))
    return out
