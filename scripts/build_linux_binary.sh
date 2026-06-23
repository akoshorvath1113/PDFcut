#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconsole --onefile --name PDFBatchRedactor main.py

echo "Built dist/PDFBatchRedactor"
