"""PDF processing primitives for removing sensitive regions."""

from __future__ import annotations

from pathlib import Path

import fitz

from .config import ProcessingConfig, RectConfig, selected_page_indexes


class PdfProcessingError(RuntimeError):
    """Raised when a PDF cannot be processed safely."""


def process_pdf(input_path: Path, output_path: Path, config: ProcessingConfig) -> None:
    """Create a redacted copy of ``input_path`` at ``output_path``.

    The source file is opened read-only and never saved in place.
    """

    input_path = input_path.resolve()
    output_path = output_path.resolve()

    if input_path == output_path:
        raise PdfProcessingError("Refusing to overwrite the original PDF.")

    config.validate()
    pages_to_process = selected_page_indexes(config)

    try:
        with fitz.open(input_path) as source:
            output = fitz.open()
            try:
                for page_index in range(source.page_count):
                    page = source.load_page(page_index)
                    should_process = pages_to_process is None or page_index in pages_to_process
                    if should_process:
                        _append_processed_page(output, source, page_index, page, config)
                    else:
                        _append_unmodified_page(output, source, page_index, page, config)

                output_path.parent.mkdir(parents=True, exist_ok=True)
                output.save(output_path, garbage=4, deflate=True)
            finally:
                output.close()
    except Exception as exc:  # noqa: BLE001 - callers need a consistent application exception.
        if isinstance(exc, PdfProcessingError):
            raise
        raise PdfProcessingError(f"Failed to process {input_path.name}: {exc}") from exc


def _append_processed_page(
    output: fitz.Document,
    source: fitz.Document,
    page_index: int,
    page: fitz.Page,
    config: ProcessingConfig,
) -> None:
    source_rect = page.rect
    output_width, output_height = _output_size(source_rect, config)
    output_page = output.new_page(width=output_width, height=output_height)

    target_rect = _clamped_rect(config.remove_rect, output_width, output_height)
    source_remove_rect = _scale_rect_to_source(target_rect, source_rect, output_width, output_height)

    if config.collapse_vertical_gap:
        _draw_collapsed_page(
            output_page=output_page,
            source_page=page,
            source_rect=source_rect,
            output_width=output_width,
            output_height=output_height,
            target_rect=target_rect,
            source_remove_rect=source_remove_rect,
        )
    else:
        _draw_redacted_page(
            output_page=output_page,
            source=source,
            page_index=page_index,
            source_rect=source_rect,
            output_width=output_width,
            output_height=output_height,
            target_rect=target_rect,
            source_remove_rect=source_remove_rect,
        )


def _append_unmodified_page(
    output: fitz.Document,
    source: fitz.Document,
    page_index: int,
    page: fitz.Page,
    config: ProcessingConfig,
) -> None:
    output_width, output_height = _output_size(page.rect, config)
    output_page = output.new_page(width=output_width, height=output_height)
    output_page.show_pdf_page(
        fitz.Rect(0, 0, output_width, output_height),
        source,
        page_index,
        clip=page.rect,
    )


def _draw_collapsed_page(
    output_page: fitz.Page,
    source_page: fitz.Page,
    source_rect: fitz.Rect,
    output_width: float,
    output_height: float,
    target_rect: fitz.Rect,
    source_remove_rect: fitz.Rect,
) -> None:
    """Remove a horizontal band and move lower content upward.

    PDF content streams are not a layout tree, so there is no universal way to reflow arbitrary
    page content. This approach rasterizes only the source content above and below the selected
    band into a new page. The rasterization is deliberate: it avoids carrying hidden text or vector
    objects from the removed band into the output copy.
    """

    top_height = target_rect.y0
    bottom_height = max(0, output_height - target_rect.y1)

    if top_height > 0:
        _insert_clip_as_image(
            output_page,
            source_page,
            clip=fitz.Rect(source_rect.x0, source_rect.y0, source_rect.x1, source_remove_rect.y0),
            dest=fitz.Rect(0, 0, output_width, top_height),
        )

    if bottom_height > 0:
        _insert_clip_as_image(
            output_page,
            source_page,
            clip=fitz.Rect(source_rect.x0, source_remove_rect.y1, source_rect.x1, source_rect.y1),
            dest=fitz.Rect(0, top_height, output_width, top_height + bottom_height),
        )


def _draw_redacted_page(
    output_page: fitz.Page,
    source: fitz.Document,
    page_index: int,
    source_rect: fitz.Rect,
    output_width: float,
    output_height: float,
    target_rect: fitz.Rect,
    source_remove_rect: fitz.Rect,
) -> None:
    """Copy the page and remove the selected rectangle without layout collapse."""

    temp = fitz.open()
    try:
        temp.insert_pdf(source, from_page=page_index, to_page=page_index)
        temp_page = temp.load_page(0)
        temp_page.add_redact_annot(source_remove_rect, fill=(1, 1, 1))
        temp_page.apply_redactions()
        output_page.show_pdf_page(
            fitz.Rect(0, 0, output_width, output_height),
            temp,
            0,
            clip=source_rect,
        )
    finally:
        temp.close()


def _insert_clip_as_image(output_page: fitz.Page, source_page: fitz.Page, clip: fitz.Rect, dest: fitz.Rect) -> None:
    if clip.is_empty or dest.is_empty:
        return
    zoom = 150 / 72
    pixmap = source_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    output_page.insert_image(dest, stream=pixmap.tobytes("png"))


def _output_size(source_rect: fitz.Rect, config: ProcessingConfig) -> tuple[float, float]:
    if config.page_size is None:
        return source_rect.width, source_rect.height
    return config.page_size


def _clamped_rect(rect_config: RectConfig, width: float, height: float) -> fitz.Rect:
    rect = rect_config.normalized()
    x0 = min(max(rect.x0, 0), width)
    y0 = min(max(rect.y0, 0), height)
    x1 = min(max(rect.x1, 0), width)
    y1 = min(max(rect.y1, 0), height)
    clamped = fitz.Rect(x0, y0, x1, y1)
    if clamped.is_empty:
        raise PdfProcessingError("The removal rectangle is outside the page.")
    return clamped


def _scale_rect_to_source(
    target_rect: fitz.Rect,
    source_rect: fitz.Rect,
    output_width: float,
    output_height: float,
) -> fitz.Rect:
    scale_x = source_rect.width / output_width
    scale_y = source_rect.height / output_height
    return fitz.Rect(
        source_rect.x0 + target_rect.x0 * scale_x,
        source_rect.y0 + target_rect.y0 * scale_y,
        source_rect.x0 + target_rect.x1 * scale_x,
        source_rect.y0 + target_rect.y1 * scale_y,
    )
