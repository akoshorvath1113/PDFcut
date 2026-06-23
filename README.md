# PDFcut

PDFcut is a small Python desktop application for batch-removing sensitive regions from standardized PDF documents.

The first working version supports:

- selecting one PDF file or one folder of PDF files
- previewing the first page of the selected PDF
- dragging a rectangle on the preview or entering coordinates manually
- applying the removal to all pages or selected pages such as `1,3-5`
- writing modified copies to a separate output folder with a configurable suffix
- batch progress and a processing summary/error log

## Privacy behavior

The default mode is **Collapse vertical gap after removal**. It removes the horizontal band covered by the rectangle's top and bottom coordinates, then moves the content below the removed band upward on the output page.

For stronger privacy in this adjusted mode, the kept page regions are rasterized into the new PDF. This means removed content is not retained as hidden text behind a clipping mask, but text in the kept regions will no longer be selectable.

If you disable collapse mode, PDFcut applies a normal PyMuPDF redaction annotation to the selected rectangle and keeps the page layout unchanged.

Original PDFs are never saved in place. The app refuses to write into the same folder as the selected source PDF and generates unique output filenames if a target file already exists.

## Install and run

Python 3.10+ is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pdf_redactor
```

On Windows, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pdf_redactor
```

Tkinter is part of most standard Python installers. On some Linux distributions it is packaged separately as `python3-tk`.

## Coordinate system

Rectangle coordinates are PDF points with a top-left origin:

- `x0`, `y0`: top-left corner
- `x1`, `y1`: bottom-right corner

A4 defaults to approximately `595 x 842` points. The starter rectangle removes the middle band of an A4 page.

## Build a sendable Windows package

Windows `.exe` files must be built on Windows. From a Windows PowerShell prompt in the project folder:

```powershell
.\scripts\build_windows_exe.ps1
```

The script creates a portable zip file:

```text
dist\PDFBatchRedactor-Windows.zip
```

Send that zip file to the receiver. They should extract it and double-click:

```text
PDFBatchRedactor.exe
```

If Windows SmartScreen appears, they can choose **More info** and then **Run anyway**.

### Build the sendable zip with GitHub Actions

This repository also includes a workflow that builds the Windows package on a Windows runner.

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Choose **Build Windows EXE**.
4. Click **Run workflow**.
5. When it finishes, download the **PDFBatchRedactor-Windows** artifact.

The artifact contains:

```text
PDFBatchRedactor-Windows.zip
```

On Linux, you can build a Linux executable instead:

```bash
bash scripts/build_linux_binary.sh
```

## Project structure

```text
pdf_redactor/
  app_logging.py     logging setup
  batch.py           file/folder discovery and safe output handling
  config.py          settings dataclasses and page selection parsing
  pdf_processor.py   PDF redaction/removal logic
  ui.py              Tkinter desktop UI
  __main__.py        application entry point
tests/
  test_pdf_redactor.py
scripts/
  build_windows_exe.ps1
  build_linux_binary.sh
.github/workflows/
  build-windows-exe.yml
```

## Tests

```bash
python3 -m unittest discover -s tests
```
