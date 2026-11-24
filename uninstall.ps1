# pdfcraft-arabic-ocr uninstaller for Windows. Removes what install.ps1 added for this user.
# Python and Tesseract stay installed (remove them in Settings > Apps if you want).

$Data = Join-Path $env:LOCALAPPDATA 'arabic-ocr'
$Scripts = "$Data\venv\Scripts"

[Environment]::SetEnvironmentVariable('PDFCRAFT_TESSERACT', $null, 'User')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath) {
    [Environment]::SetEnvironmentVariable('Path', (($userPath -split ';' | Where-Object { $_ -and $_ -ne $Scripts }) -join ';'), 'User')
}
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('SendTo')) 'Arabic OCR (PdfCraft).lnk')
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Data

Write-Host 'pdfcraft-arabic-ocr removed. Restart PdfCraft to return it to its own OCR.'
