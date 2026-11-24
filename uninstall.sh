#!/usr/bin/env bash
# pdfcraft-arabic-ocr uninstaller for macOS and Linux. Removes what install.sh added for
# this user. System packages (Homebrew/apt: tesseract, ocrmypdf…) stay installed.

DATA="$HOME/.local/share/arabic-ocr"
BIN="$HOME/.local/bin"

for c in arabic-ocr arabic-ocr-doctor tesseract-for-pdfcraft vision-ocr; do rm -f "$BIN/$c"; done
rm -rf "$DATA" "$HOME/.config/arabic-ocr"

if [[ "$(uname -s)" == Darwin ]]; then
  for label in io.github.jmfakhroo.pdfcraft-arabic-ocr local.pdfcraft.tesseract-path; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null
    rm -f "$HOME/Library/LaunchAgents/$label.plist"
  done
  launchctl unsetenv PDFCRAFT_TESSERACT
  rm -rf "$HOME/Library/Services/Arabic OCR for PdfCraft.workflow"
  /System/Library/CoreServices/pbs -update >/dev/null 2>&1
else
  systemctl --user disable -q arabic-ocr-doctor.service 2>/dev/null
  rm -f "$HOME/.config/systemd/user/arabic-ocr-doctor.service" \
        "$HOME/.config/environment.d/90-pdfcraft-arabic-ocr.conf" \
        "$HOME/.local/share/applications/arabic-ocr.desktop"
  [[ -f "$HOME/.profile" ]] && sed -i.bak '/# pdfcraft-arabic-ocr$/d' "$HOME/.profile"
fi

echo "pdfcraft-arabic-ocr removed. Restart PdfCraft (on Linux, log out and in) to return it to its own OCR."
echo "Left in place: tesseract/ocrmypdf system packages and the PATH line marked '# pdfcraft-arabic-ocr PATH'."
