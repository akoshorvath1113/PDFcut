from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from pdf_redactor.batch import process_batch, unique_output_path
from pdf_redactor.config import ProcessingConfig, RectConfig
from pdf_redactor.pdf_merger import PdfMergeError, merge_pdfs
from pdf_redactor.pdf_processor import process_pdf


A4_WIDTH = 595.276
A4_HEIGHT = 841.89


class PdfRedactorTests(unittest.TestCase):
    def test_collapse_processing_removes_selected_band_from_text_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            output_pdf = temp_path / "out" / "input_redacted.pdf"
            _make_pdf(input_pdf, page_count=1)

            process_pdf(
                input_pdf,
                output_pdf,
                ProcessingConfig(
                    remove_rect=RectConfig(0, 280, A4_WIDTH, 500),
                    output_folder=output_pdf.parent,
                    collapse_vertical_gap=True,
                ),
            )

            self.assertTrue(input_pdf.exists())
            self.assertTrue(output_pdf.exists())
            with fitz.open(output_pdf) as doc:
                self.assertEqual(doc.page_count, 1)
                self.assertNotIn("SECRET", doc[0].get_text())

    def test_redaction_without_collapse_removes_secret_and_keeps_other_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            output_pdf = temp_path / "out" / "input_redacted.pdf"
            _make_pdf(input_pdf, page_count=1)

            process_pdf(
                input_pdf,
                output_pdf,
                ProcessingConfig(
                    remove_rect=RectConfig(0, 300, A4_WIDTH, 390),
                    output_folder=output_pdf.parent,
                    collapse_vertical_gap=False,
                ),
            )

            with fitz.open(output_pdf) as doc:
                text = doc[0].get_text()

            self.assertIn("TOP", text)
            self.assertIn("BOTTOM", text)
            self.assertNotIn("SECRET", text)

    def test_multiple_redaction_rectangles_remove_multiple_regions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            output_pdf = temp_path / "out" / "input_redacted.pdf"
            _make_pdf(input_pdf, page_count=1)

            process_pdf(
                input_pdf,
                output_pdf,
                ProcessingConfig(
                    remove_rects=(
                        RectConfig(0, 80, A4_WIDTH, 140),
                        RectConfig(0, 300, A4_WIDTH, 390),
                    ),
                    output_folder=output_pdf.parent,
                    collapse_vertical_gap=False,
                ),
            )

            with fitz.open(output_pdf) as doc:
                text = doc[0].get_text()

            self.assertNotIn("TOP", text)
            self.assertNotIn("SECRET", text)
            self.assertIn("BOTTOM", text)

    def test_multiple_collapse_rectangles_remove_multiple_bands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            output_pdf = temp_path / "out" / "input_redacted.pdf"
            _make_pdf(input_pdf, page_count=1)

            process_pdf(
                input_pdf,
                output_pdf,
                ProcessingConfig(
                    remove_rects=(
                        RectConfig(0, 80, A4_WIDTH, 140),
                        RectConfig(0, 300, A4_WIDTH, 390),
                    ),
                    output_folder=output_pdf.parent,
                    collapse_vertical_gap=True,
                ),
            )

            with fitz.open(output_pdf) as doc:
                text = doc[0].get_text()

            self.assertNotIn("TOP", text)
            self.assertNotIn("SECRET", text)

    def test_selected_pages_only_processes_requested_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            output_pdf = temp_path / "out" / "input_redacted.pdf"
            _make_pdf(input_pdf, page_count=2)

            process_pdf(
                input_pdf,
                output_pdf,
                ProcessingConfig(
                    remove_rect=RectConfig(0, 300, A4_WIDTH, 390),
                    apply_to_all_pages=False,
                    selected_pages="2",
                    output_folder=output_pdf.parent,
                    collapse_vertical_gap=False,
                ),
            )

            with fitz.open(output_pdf) as doc:
                self.assertIn("SECRET PAGE 1", doc[0].get_text())
                self.assertNotIn("SECRET PAGE 2", doc[1].get_text())

    def test_batch_rejects_same_source_and_output_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            _make_pdf(input_pdf, page_count=1)

            with self.assertRaisesRegex(ValueError, "separate"):
                process_batch(input_pdf, ProcessingConfig(output_folder=temp_path))

    def test_unique_output_path_avoids_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "input.pdf"
            output_folder = temp_path / "out"
            output_folder.mkdir()
            existing = output_folder / "input_redacted.pdf"
            existing.touch()

            output_path = unique_output_path(input_pdf, output_folder, "_redacted")

            self.assertEqual(output_folder / "input_redacted_1.pdf", output_path)

    def test_merge_pdfs_combines_files_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_pdf = temp_path / "first.pdf"
            second_pdf = temp_path / "second.pdf"
            output_pdf = temp_path / "merged.pdf"
            _make_pdf(first_pdf, page_count=1, label="FIRST")
            _make_pdf(second_pdf, page_count=2, label="SECOND")

            merge_pdfs([first_pdf, second_pdf], output_pdf)

            with fitz.open(output_pdf) as doc:
                self.assertEqual(doc.page_count, 3)
                self.assertIn("FIRST TOP PAGE 1", doc[0].get_text())
                self.assertIn("SECOND TOP PAGE 1", doc[1].get_text())
                self.assertIn("SECOND TOP PAGE 2", doc[2].get_text())

    def test_merge_refuses_to_overwrite_source_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_pdf = temp_path / "first.pdf"
            second_pdf = temp_path / "second.pdf"
            _make_pdf(first_pdf, page_count=1)
            _make_pdf(second_pdf, page_count=1)

            with self.assertRaisesRegex(PdfMergeError, "overwrite"):
                merge_pdfs([first_pdf, second_pdf], first_pdf)


def _make_pdf(path: Path, page_count: int, label: str = "") -> None:
    doc = fitz.open()
    try:
        prefix = f"{label} " if label else ""
        for index in range(page_count):
            page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
            page.insert_text((72, 100), f"{prefix}TOP PAGE {index + 1}", fontsize=14)
            page.insert_text((72, 345), f"{prefix}SECRET PAGE {index + 1}", fontsize=14)
            page.insert_text((72, 650), f"{prefix}BOTTOM PAGE {index + 1}", fontsize=14)
        doc.save(path)
    finally:
        doc.close()


if __name__ == "__main__":
    unittest.main()
