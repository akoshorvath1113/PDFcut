"""Configuration models and constants for the PDF redactor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


POINTS_PER_INCH = 72

# Dimensions are PDF points.
PAGE_SIZES: dict[str, tuple[float, float] | None] = {
    "Source page": None,
    "A4": (595.276, 841.89),
    "Letter": (612.0, 792.0),
}


@dataclass(frozen=True)
class RectConfig:
    """Rectangle in PDF points, using a top-left coordinate origin."""

    x0: float
    y0: float
    x1: float
    y1: float

    def normalized(self) -> "RectConfig":
        return RectConfig(
            x0=min(self.x0, self.x1),
            y0=min(self.y0, self.y1),
            x1=max(self.x0, self.x1),
            y1=max(self.y0, self.y1),
        )

    @property
    def width(self) -> float:
        rect = self.normalized()
        return rect.x1 - rect.x0

    @property
    def height(self) -> float:
        rect = self.normalized()
        return rect.y1 - rect.y0

    def validate(self) -> None:
        rect = self.normalized()
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError("The removal rectangle must have a positive width and height.")


@dataclass(frozen=True)
class ProcessingConfig:
    """Settings used for one PDF or a batch of PDFs."""

    page_size_name: str = "A4"
    remove_rect: RectConfig = RectConfig(0, 280, 595.276, 560)
    remove_rects: tuple[RectConfig, ...] = ()
    apply_to_all_pages: bool = True
    selected_pages: str = ""
    output_folder: Path = Path("output")
    filename_suffix: str = "_redacted"
    collapse_vertical_gap: bool = True

    @property
    def page_size(self) -> tuple[float, float] | None:
        try:
            return PAGE_SIZES[self.page_size_name]
        except KeyError as exc:
            raise ValueError(f"Unsupported page size: {self.page_size_name}") from exc

    @property
    def cut_rects(self) -> tuple[RectConfig, ...]:
        """Return all configured cut rectangles.

        ``remove_rect`` is retained for older callers and tests. New UI code passes
        ``remove_rects`` when the user defines one or more cuts.
        """

        return self.remove_rects or (self.remove_rect,)

    def validate(self) -> None:
        if not self.cut_rects:
            raise ValueError("At least one removal rectangle is required.")
        for rect in self.cut_rects:
            rect.validate()
        if not self.filename_suffix:
            raise ValueError("The output filename suffix cannot be empty.")
        if self.page_size_name not in PAGE_SIZES:
            raise ValueError(f"Unsupported page size: {self.page_size_name}")
        if not self.apply_to_all_pages:
            parse_page_selection(self.selected_pages)


def parse_page_selection(selection: str) -> set[int]:
    """Parse a human page selection string into zero-based page indexes.

    Examples:
        "1,3-5" -> {0, 2, 3, 4}
    """

    selection = selection.strip()
    if not selection:
        raise ValueError("Enter page numbers such as 1,3-5 or choose all pages.")

    pages: set[int] = set()
    for token in selection.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = _parse_positive_page(start_text)
            end = _parse_positive_page(end_text)
            if end < start:
                raise ValueError(f"Invalid page range: {token}")
            pages.update(range(start - 1, end))
        else:
            pages.add(_parse_positive_page(token) - 1)

    if not pages:
        raise ValueError("No pages were selected.")
    return pages


def selected_page_indexes(config: ProcessingConfig) -> set[int] | None:
    """Return zero-based selected page indexes, or None for all pages."""

    if config.apply_to_all_pages:
        return None
    return parse_page_selection(config.selected_pages)


def _parse_positive_page(value: str) -> int:
    try:
        page = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid page number: {value!r}") from exc
    if page < 1:
        raise ValueError(f"Page numbers start at 1: {value!r}")
    return page


def format_pages(indexes: Iterable[int]) -> str:
    """Format zero-based page indexes for logs."""

    return ", ".join(str(index + 1) for index in sorted(indexes))
