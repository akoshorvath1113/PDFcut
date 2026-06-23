"""Batch PDF discovery and processing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import ProcessingConfig
from .pdf_processor import PdfProcessingError, process_pdf


ProgressCallback = Callable[[int, int, Path, bool, str], None]


@dataclass(frozen=True)
class BatchResult:
    total: int
    succeeded: int
    failed: int
    output_files: tuple[Path, ...]
    errors: tuple[str, ...]


def find_pdf_files(input_path: Path) -> list[Path]:
    """Return sorted PDF files for a single file or one folder."""

    input_path = input_path.expanduser().resolve()
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"Selected file is not a PDF: {input_path}")
        return [input_path]
    if input_path.is_dir():
        files = sorted(path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
        if not files:
            raise ValueError(f"No PDF files found in folder: {input_path}")
        return files
    raise ValueError(f"Input path does not exist: {input_path}")


def process_batch(
    input_path: Path,
    config: ProcessingConfig,
    progress_callback: ProgressCallback | None = None,
) -> BatchResult:
    """Process a file or folder of PDFs and return a summary."""

    config.validate()
    files = find_pdf_files(input_path)
    output_folder = config.output_folder.expanduser().resolve()
    _ensure_separate_output_folder(files, output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    successes: list[Path] = []
    errors: list[str] = []
    total = len(files)

    for index, pdf_path in enumerate(files, start=1):
        output_path = unique_output_path(pdf_path, output_folder, config.filename_suffix)
        try:
            process_pdf(pdf_path, output_path, config)
        except (PdfProcessingError, OSError, ValueError) as exc:
            message = f"{pdf_path.name}: {exc}"
            errors.append(message)
            if progress_callback:
                progress_callback(index, total, pdf_path, False, message)
        else:
            successes.append(output_path)
            if progress_callback:
                progress_callback(index, total, pdf_path, True, f"Saved {output_path.name}")

    return BatchResult(
        total=total,
        succeeded=len(successes),
        failed=len(errors),
        output_files=tuple(successes),
        errors=tuple(errors),
    )


def unique_output_path(input_pdf: Path, output_folder: Path, suffix: str) -> Path:
    """Build a non-conflicting output path for a processed PDF."""

    if not suffix:
        raise ValueError("The output filename suffix cannot be empty.")

    base_name = f"{input_pdf.stem}{suffix}"
    candidate = output_folder / f"{base_name}{input_pdf.suffix}"
    counter = 1
    while candidate.exists() or candidate.resolve() == input_pdf.resolve():
        candidate = output_folder / f"{base_name}_{counter}{input_pdf.suffix}"
        counter += 1
    return candidate


def _ensure_separate_output_folder(files: list[Path], output_folder: Path) -> None:
    input_folders = {path.parent.resolve() for path in files}
    if output_folder in input_folders:
        raise ValueError("Choose an output folder that is separate from the source PDF folder.")
