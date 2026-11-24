#!/usr/bin/env bash
# pdfcraft-arabic-ocr installer for macOS and Linux (Windows: install.ps1).
#
#   ./install.sh                     from a clone of the repo
#   curl -fsSL https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/install.sh | bash
#
# Per-user install (sudo only for Linux system packages):
#   ~/.local/share/arabic-ocr/   venv, config, Tesseract models, (macOS) vision-ocr
#   ~/.local/bin/                arabic-ocr, arabic-ocr-doctor, tesseract-for-pdfcraft (links)
#   macOS: Finder Quick Action + login item  |  Linux: "Open With" entry + login check

set -euo pipefail

REPO="jmfakhroo/pdfcraft-arabic-ocr"
DATA="$HOME/.local/share/arabic-ocr"
BIN="$HOME/.local/bin"
OS=$(uname -s)

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# --- The repo files: this checkout, or a download when piped from curl.
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ ! -f "$SRC/pyproject.toml" ]]; then
  TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
  say "Downloading $REPO"
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP" || die "Couldn't download the repository."
  SRC="$TMP/pdfcraft-arabic-ocr-main"
fi

say "Checking requirements"
case "$OS" in
  Darwin)
    MACOS=$(sw_vers -productVersion)
    (( ${MACOS%%.*} >= 14 )) || die "macOS 14 (Sonoma) or newer is needed for Apple's Arabic text recognition (this Mac: $MACOS)."
    ok "macOS $MACOS"
    if ! command -v brew >/dev/null; then
      for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [[ -x $b ]] && eval "$($b shellenv)" && break; done
    fi
    command -v brew >/dev/null || die "Homebrew is needed. Install it from https://brew.sh, then run this again."
    ok "Homebrew ($(brew --prefix))"
    if ! xcrun --find swiftc >/dev/null 2>&1; then
      xcode-select --install 2>/dev/null || true
      die "Apple's Command Line Tools are needed (an install window should have opened). Run this again afterwards."
    fi
    ok "Command Line Tools"
    say "Homebrew packages: tesseract, ocrmypdf"
    for f in tesseract ocrmypdf; do
      brew list --formula "$f" >/dev/null 2>&1 && ok "$f" || { brew install "$f" && ok "$f installed"; }
    done
    PY=$(command -v python3)
    EXTRAS=""
    ;;
  Linux)
    ok "Linux ($(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}"))"
    SUDO=""; [[ $(id -u) -ne 0 ]] && SUDO="sudo"
    say "System packages (Tesseract, Python venv, libraries RapidOCR needs)"
    if command -v apt-get >/dev/null; then
      $SUDO apt-get update -qq
      $SUDO apt-get install -y -qq tesseract-ocr ghostscript python3-venv python3-pip libgl1 libglib2.0-0 >/dev/null
    elif command -v dnf >/dev/null; then
      $SUDO dnf install -y -q tesseract ghostscript python3 python3-pip mesa-libGL glib2
    elif command -v pacman >/dev/null; then
      $SUDO pacman -S --needed --noconfirm tesseract ghostscript python python-pip mesa glib2
    elif command -v zypper >/dev/null; then
      $SUDO zypper -n install tesseract-ocr ghostscript python3 python3-pip Mesa-libGL1 glib2
    else
      die "Unknown package manager. Install Tesseract, Ghostscript and Python 3.10 to 3.13 yourself, then run this again."
    fi
    ok "tesseract $(tesseract --version 2>&1 | head -1 | awk '{print $2}')"
    # onnxruntime (RapidOCR) has wheels for these Python versions.
    PY=""
    for v in 3.13 3.12 3.11 3.10; do command -v "python$v" >/dev/null && PY=$(command -v "python$v") && break; done
    [[ -n "$PY" ]] || PY=$(command -v python3)
    "$PY" -c 'import sys; sys.exit(not (3,10) <= sys.version_info[:2] <= (3,13))' \
      || echo "  ! $("$PY" -V) may be too new for RapidOCR; if it fails, install Python 3.12 and run this again."
    EXTRAS="[full]"
    ;;
  *) die "Unsupported system: $OS (on Windows, use install.ps1)." ;;
esac

say "Installing the Python package"
mkdir -p "$DATA" "$BIN"
"$PY" -m venv --clear "$DATA/venv"
"$DATA/venv/bin/python" -m pip install -q --upgrade pip
"$DATA/venv/bin/python" -m pip install -q "$SRC$EXTRAS"
for c in arabic-ocr arabic-ocr-doctor tesseract-for-pdfcraft; do
  rm -f "$BIN/$c"; ln -s "$DATA/venv/bin/$c" "$BIN/$c"
done
ok "arabic-ocr, arabic-ocr-doctor, tesseract-for-pdfcraft in $BIN"

if [[ "$OS" == Darwin ]]; then
  say "macOS extras"
  cp "$SRC/macos/vision-ocr.swift" "$DATA/"
  rm -f "$BIN/vision-ocr"   # older layout
  SERVICES="$HOME/Library/Services"; mkdir -p "$SERVICES"
  rm -rf "$SERVICES/Arabic OCR for PdfCraft.workflow"
  cp -R "$SRC/macos/Arabic OCR for PdfCraft.workflow" "$SERVICES/"
  /System/Library/CoreServices/pbs -update >/dev/null 2>&1 || true
  ok "Finder Quick Action: Arabic OCR (PdfCraft)"

  LABEL="io.github.jmfakhroo.pdfcraft-arabic-ocr"
  AGENTS="$HOME/Library/LaunchAgents"; mkdir -p "$AGENTS"
  for old in local.pdfcraft.tesseract-path; do   # earlier hand-made version
    launchctl bootout "gui/$(id -u)/$old" 2>/dev/null || true; rm -f "$AGENTS/$old.plist"
  done
  BREW=$(brew --prefix)
  cat >"$AGENTS/$LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- pdfcraft-arabic-ocr: at login, and when PdfCraft, Tesseract or ocrmypdf is updated,
     re-point PdfCraft at the Arabic helper and repair the setup. -->
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$DATA/venv/bin/arabic-ocr-doctor</string><string>--quiet</string></array>
  <key>RunAtLoad</key><true/>
  <key>WatchPaths</key>
  <array>
    <string>/Applications/PdfCraft.app/Contents/Info.plist</string>
    <string>$BREW/opt/tesseract</string>
    <string>$BREW/opt/ocrmypdf</string>
  </array>
  <key>ThrottleInterval</key><integer>60</integer>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$LABEL.plist" 2>/dev/null || echo "  ! the login item starts at your next login"
  ok "login item $LABEL"
else
  say "Linux extras"
  APPS="$HOME/.local/share/applications"; mkdir -p "$APPS"
  cat >"$APPS/arabic-ocr.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arabic OCR (PdfCraft)
Name[ar]=التعرف الضوئي العربي (PdfCraft)
Comment=Make a scanned Arabic PDF searchable and open it in PdfCraft
Exec=$DATA/venv/bin/arabic-ocr -o %F
MimeType=application/pdf;image/png;image/jpeg;image/tiff;
Terminal=false
NoDisplay=true
Categories=Office;
EOF
  command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
  ok "Open With > Arabic OCR (PdfCraft)"
  if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
    UNIT="$HOME/.config/systemd/user"; mkdir -p "$UNIT"
    cat >"$UNIT/arabic-ocr-doctor.service" <<EOF
[Unit]
Description=Check and repair Arabic OCR for PdfCraft

[Service]
Type=oneshot
ExecStart=$DATA/venv/bin/arabic-ocr-doctor --quiet

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload && systemctl --user enable -q arabic-ocr-doctor.service && ok "login check (systemd user service)"
  fi
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) PROFILE="$HOME/.profile"; [[ "$OS" == Darwin ]] && PROFILE="$HOME/.zprofile"
     grep -qs '# pdfcraft-arabic-ocr PATH' "$PROFILE" || printf '\nexport PATH="$HOME/.local/bin:$PATH"  # pdfcraft-arabic-ocr PATH\n' >>"$PROFILE"
     echo "  ! added ~/.local/bin to PATH in $PROFILE (open a new terminal to use arabic-ocr)" ;;
esac

say "Setup and self-test (downloads Tesseract's Arabic model; the first OCR run can take a minute)"
"$DATA/venv/bin/arabic-ocr-doctor" --setup || die "The self-test found a problem (see above). Run arabic-ocr-doctor after fixing it."

cat <<'EOF'

Done.
 • PdfCraft: quit and reopen it (on Linux, log out and in once). Then Scan & OCR > In this file,
   set Engine = Tesseract (that's the Arabic engine now), Recognize text, and save.
 • Terminal:  arabic-ocr book.pdf   (writes book.ocr.pdf and book.ocr.txt)
EOF
[[ "$OS" == Darwin ]] && echo ' • Finder: right-click a PDF > Quick Actions > Customize… and switch on "Arabic OCR (PdfCraft)" once.'
[[ "$OS" == Linux ]] && echo ' • Files: right-click a PDF > Open With > Arabic OCR (PdfCraft).'
echo ' • Check or repair any time:  arabic-ocr-doctor'
