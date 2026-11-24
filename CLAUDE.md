# Installing pdfcraft-arabic-ocr for a user

This repo adds Arabic OCR to PdfCraft on macOS, Linux and Windows. When a user asks you to install it, follow these steps. Talk to the user in the language they wrote in (often Arabic).

## 1. Check the system

- macOS: needs macOS 14 or newer (`sw_vers -productVersion`), Homebrew (`brew`), and Apple's Command Line Tools (`xcrun --find swiftc`). If Homebrew is missing, point the user to https://brew.sh; don't install it for them without asking. If the Command Line Tools are missing, `xcode-select --install` opens Apple's installer, and the user has to click through it.
- Linux: the installer uses apt, dnf, pacman or zypper with sudo. Tell the user it will ask for their password.
- Windows: needs winget. The Windows path is experimental (not yet tested on real Windows); say so before installing.
- PdfCraft is optional for the `arabic-ocr` command but needed for the in-app part. It's usually in /Applications on macOS.

## 2. Run the installer

From a clone of this repo:

- macOS and Linux: `bash install.sh`
- Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File install.ps1`

It takes a few minutes: it installs Tesseract (and ocrmypdf on macOS) through the system's package manager, creates a Python venv, downloads Tesseract's Arabic model, builds Apple's recognizer on macOS (or installs RapidOCR elsewhere), and ends with `arabic-ocr-doctor --setup`. Run it in the background if your tool times out on long commands.

## 3. Verify

Run `arabic-ocr-doctor`. Every line should be a check mark and it should end with "All good." If something fails, read its message: it names the broken piece (Tesseract, model, engine, helper, command, PDFCRAFT_TESSERACT, PdfCraft). Fix that piece and run the doctor again. The doctor's log is `doctor.log` in the data folder (`~/.local/share/arabic-ocr` or `%LOCALAPPDATA%\arabic-ocr`).

## 4. Tell the user the manual steps

These can't be automated reliably:

1. Quit and reopen PdfCraft (on Linux, log out and in once) so it picks up `PDFCRAFT_TESSERACT`.
2. In PdfCraft: Scan & OCR, In this file, Engine = Tesseract (that is now the Arabic engine), Recognize text, then save. Document language stays "English"; that's expected.
3. macOS only, once: right-click a PDF, Quick Actions, Customize, switch on "Arabic OCR (PdfCraft)". macOS hides new Quick Actions until they're switched on there.

## Notes

- Don't change the user's System Settings, PdfCraft preferences or shell profile beyond what the installer does unless they ask.
- To check the in-app route without the GUI: `tesseract-for-pdfcraft <image> stdout -l eng tsv` should print rows whose Arabic words are letter-reversed (that's intended: PdfCraft reverses them back).
- Uninstall: `bash uninstall.sh` or `uninstall.ps1`. Ask before running it.
