# pdfcraft-arabic-ocr installer for Windows 10/11 (EXPERIMENTAL: not yet tested on Windows).
#
#   powershell -ExecutionPolicy Bypass -File install.ps1          (from a clone of the repo)
#   irm https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/install.ps1 | iex
#
# Installs for the current user: %LOCALAPPDATA%\arabic-ocr (Python venv, models, config),
# the PDFCRAFT_TESSERACT user variable, and a "Send to > Arabic OCR (PdfCraft)" entry.
# Uses winget for Python 3.12 and Tesseract (UB Mannheim build) if they're missing.

$ErrorActionPreference = 'Stop'
$Repo = 'jmfakhroo/pdfcraft-arabic-ocr'
$Data = Join-Path $env:LOCALAPPDATA 'arabic-ocr'

function Say($m) { Write-Host "`n$m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "  + $m" }
function Fail($m) { Write-Host "`nX $m" -ForegroundColor Red; exit 1 }

# --- Repo files: this checkout, or a download when run through irm | iex.
$Src = $PSScriptRoot
if (-not $Src -or -not (Test-Path (Join-Path $Src 'pyproject.toml'))) {
    Say "Downloading $Repo"
    $tmp = Join-Path $env:TEMP ("pdfcraft-arabic-ocr-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile "$tmp\src.zip" -UseBasicParsing
    Expand-Archive "$tmp\src.zip" -DestinationPath $tmp
    $Src = Join-Path $tmp 'pdfcraft-arabic-ocr-main'
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Find-Python {
    # onnxruntime (RapidOCR) has wheels for 3.10-3.13.
    foreach ($v in '3.13', '3.12', '3.11', '3.10') {
        try {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
        } catch {}
    }
    foreach ($v in '313', '312', '311', '310') {
        $c = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Find-Tesseract {
    @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
      "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
      "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}

Say 'Checking requirements'
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail 'winget is needed (Windows 10/11 "App Installer" from the Microsoft Store).'
}
Ok "Windows $([Environment]::OSVersion.Version)"

$Py = Find-Python
if (-not $Py) {
    Say 'Installing Python 3.12 (winget)'
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $Py = Find-Python
    if (-not $Py) { Fail 'Python 3.12 was installed but not found. Open a new PowerShell and run this again.' }
}
Ok "Python: $Py"

$Tess = Find-Tesseract
if (-not $Tess) {
    Say 'Installing Tesseract OCR (winget, UB Mannheim build; Windows may ask for permission)'
    winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
    $Tess = Find-Tesseract
    if (-not $Tess) { Fail 'Tesseract was installed but not found. Run this again.' }
}
Ok "Tesseract: $Tess"

Say 'Installing the Python package (this downloads RapidOCR; it can take a few minutes)'
New-Item -ItemType Directory -Force -Path $Data | Out-Null
& $Py -m venv --clear "$Data\venv"
if ($LASTEXITCODE) { Fail 'Creating the Python environment failed.' }
& "$Data\venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Data\venv\Scripts\python.exe" -m pip install -q ($Src + '[full]')
if ($LASTEXITCODE) { Fail 'Installing the package failed.' }
$Scripts = "$Data\venv\Scripts"
Ok "arabic-ocr, arabic-ocr-doctor, tesseract-for-pdfcraft in $Scripts"

# Commands on PATH for new terminals.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ($userPath -split ';' | Where-Object { $_ -eq $Scripts })) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $Scripts), 'User')
    Ok 'added to your PATH (new terminals)'
}

# Explorer: right-click a PDF > Send to > Arabic OCR (PdfCraft)
$sendTo = [Environment]::GetFolderPath('SendTo')
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $sendTo 'Arabic OCR (PdfCraft).lnk'))
$lnk.TargetPath = "$Scripts\arabic-ocr.exe"
$lnk.Arguments = '-o'
$lnk.Description = 'Make a scanned Arabic PDF searchable and open it in PdfCraft'
$lnk.Save()
Ok 'Send to > Arabic OCR (PdfCraft)'

Say 'Setup and self-test (downloads the Arabic models; the first OCR run can take a minute)'
& "$Scripts\arabic-ocr-doctor.exe" --setup
if ($LASTEXITCODE) { Fail 'The self-test found a problem (see above). Run arabic-ocr-doctor after fixing it.' }

Write-Host @'

Done.
 * PdfCraft: close and reopen it. Then Scan & OCR > In this file, set Engine = Tesseract
   (that's the Arabic engine now), Recognize text, and save.
 * Explorer: right-click a PDF > Send to > Arabic OCR (PdfCraft)
 * Terminal (new window):  arabic-ocr book.pdf   -> book.ocr.pdf + book.ocr.txt
 * Check or repair any time:  arabic-ocr-doctor
'@
