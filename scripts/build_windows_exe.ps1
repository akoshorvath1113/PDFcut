param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$AppName = "PDFBatchRedactor"
$PortableFolder = "dist\$AppName-Windows"
$ZipPath = "dist\$AppName-Windows.zip"

Write-Host "Using Python:"
& $Python --version

if (Test-Path ".venv") {
    Write-Host "Removing existing .venv so the package build starts cleanly"
    Remove-Item -Recurse -Force ".venv"
}

& $Python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-build.txt

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

& ".\.venv\Scripts\python.exe" -m PyInstaller --clean --noconsole --onefile --name $AppName main.py

New-Item -ItemType Directory -Force -Path $PortableFolder | Out-Null
Move-Item "dist\$AppName.exe" "$PortableFolder\$AppName.exe"

@"
PDF Batch Redactor
==================

How to run:
1. Extract this zip file.
2. Double-click $AppName.exe.
3. If Windows SmartScreen appears, choose More info, then Run anyway.

Notes:
- Original PDF files are never overwritten.
- Choose an output folder that is separate from your source PDF folder.
- The first startup can take a few seconds because this is a self-contained app.
"@ | Set-Content -Path "$PortableFolder\README.txt" -Encoding UTF8

Compress-Archive -Path "$PortableFolder\*" -DestinationPath $ZipPath -Force

Write-Host "Built $PortableFolder\$AppName.exe"
Write-Host "Send this file to users: $ZipPath"
