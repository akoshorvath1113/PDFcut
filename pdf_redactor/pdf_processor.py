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

    target_rects = [_clamped_rect(rect, output_width, output_height) for rect in config.cut_rects]
    source_remove_rects = [
        _scale_rect_to_source(rect, source_rect, output_width, output_height) for rect in target_rects
    ]

    if config.collapse_vertical_gap:
        _draw_collapsed_page(
            output_page=output_page,
            source_page=page,
            source_rect=source_rect,
            output_width=output_width,
            target_rects=target_rects,
            source_remove_rects=source_remove_rects,
        )
    else:
        _draw_redacted_page(
            output_page=output_page,
            source=source,
            page_index=page_index,
            source_rect=source_rect,
            output_width=output_width,
            output_height=output_height,
            source_remove_rects=source_remove_rects,
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
    target_rects: list[fitz.Rect],
    source_remove_rects: list[fitz.Rect],
) -> None:
    """Remove horizontal bands and move lower content upward.

    PDF content streams are not a layout tree, so there is no universal way to reflow arbitrary
    page content. This approach rasterizes only source content outside the selected bands into a
    new page. The rasterization is deliberate: it avoids carrying hidden text or vector objects from
    removed bands into the output copy.
    """

    target_bands = _merged_vertical_bands(target_rects)
    source_bands = _merged_vertical_bands(source_remove_rects)
    if len(target_bands) != len(source_bands):
        raise PdfProcessingError("Could not map removal rectangles to source page bands.")

    target_segments = _kept_vertical_segments(target_bands, 0.0, output_page.rect.height)
    source_segments = _kept_vertical_segments(source_bands, source_rect.y0, source_rect.y1)

    dest_y = 0.0
    for target_segment, source_segment in zip(target_segments, source_segments):
        target_y0, target_y1 = target_segment
        source_y0, source_y1 = source_segment
        segment_height = max(0.0, target_y1 - target_y0)
        if segment_height <= 0:
            continue
        _insert_clip_as_image(
            output_page,
            source_page,
            clip=fitz.Rect(source_rect.x0, source_y0, source_rect.x1, source_y1),
            dest=fitz.Rect(0, dest_y, output_width, dest_y + segment_height),
        )
        dest_y += segment_height


def _draw_redacted_page(
    output_page: fitz.Page,
    source: fitz.Document,
    page_index: int,
    source_rect: fitz.Rect,
    output_width: float,
    output_height: float,
    source_remove_rects: list[fitz.Rect],
) -> None:
    """Copy the page and remove the selected rectangles without layout collapse."""

    temp = fitz.open()
    try:
        temp.insert_pdf(source, from_page=page_index, to_page=page_index)
        temp_page = temp.load_page(0)
        for source_remove_rect in source_remove_rects:
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


def _merged_vertical_bands(rects: list[fitz.Rect]) -> list[tuple[float, float]]:
    bands = sorted((rect.y0, rect.y1) for rect in rects if not rect.is_empty)
    if not bands:
        return []

    merged: list[tuple[float, float]] = []
    current_y0, current_y1 = bands[0]
    for y0, y1 in bands[1:]:
        if y0 <= current_y1:
            current_y1 = max(current_y1, y1)
        else:
            merged.append((current_y0, current_y1))
            current_y0, current_y1 = y0, y1
    merged.append((current_y0, current_y1))
    return merged


def _kept_vertical_segments(
    removal_bands: list[tuple[float, float]],
    page_y0: float,
    page_y1: float,
) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    current_y = page_y0
    for band_y0, band_y1 in removal_bands:
        if band_y0 > current_y:
            kept.append((current_y, band_y0))
        current_y = max(current_y, band_y1)
    if current_y < page_y1:
        kept.append((current_y, page_y1))
    return kept


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
