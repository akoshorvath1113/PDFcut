$ErrorActionPreference = "Stop"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconsole --onefile --name PDFBatchRedactor main.py

Write-Host "Built dist\PDFBatchRedactor.exe"
