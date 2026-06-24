"""PDF merge helpers."""

from __future__ import annotations

from pathlib import Path

import fitz


class PdfMergeError(RuntimeError):
    """Raised when PDFs cannot be merged safely."""


def merge_pdfs(input_paths: list[Path], output_path: Path) -> None:
    """Merge PDFs in the given order into ``output_path``.

    The source files are opened read-only and the output path may not match any source file.
    """

    if len(input_paths) < 2:
        raise PdfMergeError("Choose at least two PDF files to merge.")

    resolved_inputs = [_validate_pdf_path(path) for path in input_paths]
    output_path = output_path.expanduser().resolve()

    if output_path.suffix.lower() != ".pdf":
        raise PdfMergeError("The merged output file must use a .pdf extension.")
    if output_path in resolved_inputs:
        raise PdfMergeError("Refusing to overwrite one of the source PDFs.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    merged = fitz.open()
    try:
        for input_path in resolved_inputs:
            with fitz.open(input_path) as source:
                merged.insert_pdf(source)
        merged.save(output_path, garbage=4, deflate=True)
    except Exception as exc:  # noqa: BLE001 - callers need a consistent application exception.
        if isinstance(exc, PdfMergeError):
            raise
        raise PdfMergeError(f"Failed to merge PDFs: {exc}") from exc
    finally:
        merged.close()


def _validate_pdf_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PdfMergeError(f"PDF file does not exist: {resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise PdfMergeError(f"Selected file is not a PDF: {resolved}")
    return resolved
