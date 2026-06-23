"""Tkinter desktop user interface for the PDF redactor."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import fitz

from .app_logging import configure_logging, get_logger
from .batch import BatchResult, find_pdf_files, process_batch
from .config import PAGE_SIZES, ProcessingConfig, RectConfig


class PdfRedactorApp:
    """Simple desktop app for selecting and processing PDFs."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PDF Batch Redactor")
        self.root.geometry("1120x780")

        self.input_path_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.page_size_var = tk.StringVar(value="A4")
        self.suffix_var = tk.StringVar(value="_redacted")
        self.all_pages_var = tk.BooleanVar(value=True)
        self.selected_pages_var = tk.StringVar()
        self.collapse_var = tk.BooleanVar(value=True)
        self.x0_var = tk.StringVar(value="0")
        self.y0_var = tk.StringVar(value="280")
        self.x1_var = tk.StringVar(value="595.276")
        self.y1_var = tk.StringVar(value="560")
        self.progress_var = tk.DoubleVar(value=0)

        self.preview_doc: fitz.Document | None = None
        self.preview_pdf_path: Path | None = None
        self.preview_page_rect: fitz.Rect | None = None
        self.preview_scale = 1.0
        self.preview_origin = (0.0, 0.0)
        self.preview_image: tk.PhotoImage | None = None
        self.drag_start_pdf: tuple[float, float] | None = None
        self.worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        self._build_layout()
        self._toggle_page_selection()
        self._draw_selection_from_fields()

    def run(self) -> None:
        self.root.mainloop()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.root, padding=10)
        controls.grid(row=0, column=0, sticky="ns")

        preview_area = ttk.Frame(self.root, padding=(0, 10, 10, 10))
        preview_area.grid(row=0, column=1, sticky="nsew")
        preview_area.columnconfigure(0, weight=1)
        preview_area.rowconfigure(0, weight=1)

        self._build_input_controls(controls)
        self._build_settings_controls(controls)
        self._build_coordinate_controls(controls)
        self._build_processing_controls(controls)
        self._build_preview(preview_area)

    def _build_input_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Input and output", padding=10)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="PDF or folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.input_path_var, width=42).grid(row=1, column=0, columnspan=3, sticky="ew")
        ttk.Button(frame, text="Select PDF", command=self._choose_pdf).grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(frame, text="Select Folder", command=self._choose_folder).grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=6)
        ttk.Button(frame, text="Load Preview", command=self._load_preview_from_input).grid(row=2, column=2, sticky="ew", pady=(6, 0))

        ttk.Label(frame, text="Output folder").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.output_folder_var, width=42).grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(frame, text="Browse", command=self._choose_output_folder).grid(row=4, column=2, sticky="ew", padx=(6, 0))

    def _build_settings_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Settings", padding=10)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Page size").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.page_size_var,
            values=list(PAGE_SIZES.keys()),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(frame, text="Filename suffix").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.suffix_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(
            frame,
            text="Apply to all pages",
            variable=self.all_pages_var,
            command=self._toggle_page_selection,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(frame, text="Selected pages").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.selected_pages_entry = ttk.Entry(frame, textvariable=self.selected_pages_var)
        self.selected_pages_entry.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(frame, text="Example: 1,3-5").grid(row=4, column=1, sticky="w")

        ttk.Checkbutton(
            frame,
            text="Collapse vertical gap after removal",
            variable=self.collapse_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_coordinate_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Removal rectangle (PDF points)", padding=10)
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            frame.columnconfigure(column, weight=1)

        entries = (
            ("x0", self.x0_var),
            ("y0", self.y0_var),
            ("x1", self.x1_var),
            ("y1", self.y1_var),
        )
        for index, (label, variable) in enumerate(entries):
            ttk.Label(frame, text=label).grid(row=0, column=index, sticky="w")
            ttk.Entry(frame, textvariable=variable, width=10).grid(row=1, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))

        ttk.Button(frame, text="Update preview rectangle", command=self._draw_selection_from_fields).grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(10, 0),
        )
        ttk.Label(
            frame,
            text="Drag on the preview to set these coordinates. PDF coordinates use top-left origin.",
            wraplength=330,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_processing_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Process", padding=10)
        frame.grid(row=3, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)

        self.start_button = ttk.Button(frame, text="Process PDFs", command=self._start_processing)
        self.start_button.grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(frame, variable=self.progress_var, maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.log_text = tk.Text(frame, width=44, height=15, state="disabled", wrap="word")
        self.log_text.grid(row=2, column=0, sticky="ew", pady=(10, 0))

    def _build_preview(self, parent: ttk.Frame) -> None:
        self.canvas = tk.Canvas(parent, background="#f4f4f4", highlightthickness=1, highlightbackground="#c0c0c0")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

    def _choose_pdf(self) -> None:
        path = filedialog.askopenfilename(title="Select PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            self.input_path_var.set(path)
            self._set_default_output_folder(Path(path).parent)
            self._load_preview(Path(path))

    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(title="Select folder containing PDFs")
        if path:
            self.input_path_var.set(path)
            self._set_default_output_folder(Path(path) / "redacted_output")
            self._load_preview_from_input()

    def _choose_output_folder(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_folder_var.set(path)

    def _set_default_output_folder(self, folder: Path) -> None:
        if not self.output_folder_var.get().strip():
            self.output_folder_var.set(str(folder / "redacted_output"))

    def _load_preview_from_input(self) -> None:
        input_text = self.input_path_var.get().strip()
        if not input_text:
            messagebox.showwarning("No input selected", "Choose a PDF or folder first.")
            return
        try:
            first_pdf = find_pdf_files(Path(input_text))[0]
        except Exception as exc:  # noqa: BLE001 - UI should show friendly errors.
            messagebox.showerror("Preview error", str(exc))
            return
        self._load_preview(first_pdf)

    def _load_preview(self, pdf_path: Path) -> None:
        try:
            if self.preview_doc is not None:
                self.preview_doc.close()
            self.preview_doc = fitz.open(pdf_path)
            self.preview_pdf_path = pdf_path
            page = self.preview_doc.load_page(0)
            self.preview_page_rect = page.rect
            self._render_preview()
            self._append_log(f"Loaded preview: {pdf_path.name}")
        except Exception as exc:  # noqa: BLE001 - UI should show friendly errors.
            messagebox.showerror("Preview error", f"Could not load preview: {exc}")

    def _render_preview(self) -> None:
        if self.preview_doc is None or self.preview_page_rect is None:
            self.canvas.delete("all")
            self.canvas.create_text(20, 20, anchor="nw", text="Select a PDF to preview.")
            return

        page = self.preview_doc.load_page(0)
        canvas_width = max(self.canvas.winfo_width(), 640)
        canvas_height = max(self.canvas.winfo_height(), 720)
        scale = min((canvas_width - 30) / page.rect.width, (canvas_height - 30) / page.rect.height, 2.0)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        self.preview_image = tk.PhotoImage(data=pixmap.tobytes("png"))
        image_width = self.preview_image.width()
        image_height = self.preview_image.height()
        origin_x = max(15, (canvas_width - image_width) / 2)
        origin_y = max(15, (canvas_height - image_height) / 2)

        self.preview_scale = scale
        self.preview_origin = (origin_x, origin_y)
        self.canvas.delete("all")
        self.canvas.create_image(origin_x, origin_y, anchor="nw", image=self.preview_image)
        self._draw_selection_from_fields()

    def _toggle_page_selection(self) -> None:
        state = "disabled" if self.all_pages_var.get() else "normal"
        if hasattr(self, "selected_pages_entry"):
            self.selected_pages_entry.configure(state=state)

    def _rect_from_fields(self) -> RectConfig:
        try:
            return RectConfig(
                x0=float(self.x0_var.get()),
                y0=float(self.y0_var.get()),
                x1=float(self.x1_var.get()),
                y1=float(self.y1_var.get()),
            ).normalized()
        except ValueError as exc:
            raise ValueError("Rectangle coordinates must be numbers.") from exc

    def _draw_selection_from_fields(self) -> None:
        self.canvas.delete("selection")
        try:
            rect = self._rect_from_fields()
            rect.validate()
        except ValueError:
            return
        if self.preview_page_rect is None:
            return

        x0, y0 = self._pdf_to_canvas(rect.x0, rect.y0)
        x1, y1 = self._pdf_to_canvas(rect.x1, rect.y1)
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="#d40000", width=2, tags="selection")

    def _on_canvas_press(self, event: tk.Event[tk.Misc]) -> None:
        if self.preview_page_rect is None:
            return
        self.drag_start_pdf = self._canvas_to_pdf(event.x, event.y)

    def _on_canvas_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self.drag_start_pdf is None:
            return
        end_pdf = self._canvas_to_pdf(event.x, event.y)
        self._set_rect_fields(self.drag_start_pdf, end_pdf)
        self._draw_selection_from_fields()

    def _on_canvas_release(self, event: tk.Event[tk.Misc]) -> None:
        if self.drag_start_pdf is None:
            return
        end_pdf = self._canvas_to_pdf(event.x, event.y)
        self._set_rect_fields(self.drag_start_pdf, end_pdf)
        self.drag_start_pdf = None
        self._draw_selection_from_fields()

    def _canvas_to_pdf(self, x: float, y: float) -> tuple[float, float]:
        if self.preview_page_rect is None:
            return (0.0, 0.0)
        origin_x, origin_y = self.preview_origin
        pdf_x = (x - origin_x) / self.preview_scale
        pdf_y = (y - origin_y) / self.preview_scale
        pdf_x = min(max(pdf_x, 0.0), self.preview_page_rect.width)
        pdf_y = min(max(pdf_y, 0.0), self.preview_page_rect.height)
        return (pdf_x, pdf_y)

    def _pdf_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y = self.preview_origin
        return (origin_x + x * self.preview_scale, origin_y + y * self.preview_scale)

    def _set_rect_fields(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        x0, y0 = start
        x1, y1 = end
        rect = RectConfig(x0, y0, x1, y1).normalized()
        self.x0_var.set(f"{rect.x0:.2f}")
        self.y0_var.set(f"{rect.y0:.2f}")
        self.x1_var.set(f"{rect.x1:.2f}")
        self.y1_var.set(f"{rect.y1:.2f}")

    def _start_processing(self) -> None:
        try:
            input_path = Path(self.input_path_var.get().strip())
            if not self.input_path_var.get().strip():
                raise ValueError("Choose a PDF or folder first.")
            output_text = self.output_folder_var.get().strip()
            if not output_text:
                raise ValueError("Choose an output folder.")
            config = ProcessingConfig(
                page_size_name=self.page_size_var.get(),
                remove_rect=self._rect_from_fields(),
                apply_to_all_pages=self.all_pages_var.get(),
                selected_pages=self.selected_pages_var.get(),
                output_folder=Path(output_text),
                filename_suffix=self.suffix_var.get().strip(),
                collapse_vertical_gap=self.collapse_var.get(),
            )
            config.validate()
        except Exception as exc:  # noqa: BLE001 - UI should show friendly errors.
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.progress_var.set(0)
        self.start_button.configure(state="disabled")
        self._append_log("Starting processing...")

        thread = threading.Thread(target=self._worker, args=(input_path, config), daemon=True)
        thread.start()
        self.root.after(100, self._poll_worker_queue)

    def _worker(self, input_path: Path, config: ProcessingConfig) -> None:
        logger = configure_logging(config.output_folder)

        def callback(done: int, total: int, path: Path, success: bool, message: str) -> None:
            logger.info("%s: %s", path.name, message)
            self.worker_queue.put(("progress", (done, total, success, message)))

        try:
            result = process_batch(input_path, config, callback)
        except Exception as exc:  # noqa: BLE001 - UI should show friendly errors.
            logger.exception("Batch failed")
            self.worker_queue.put(("error", str(exc)))
        else:
            self.worker_queue.put(("done", result))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                event, payload = self.worker_queue.get_nowait()
                if event == "progress":
                    done, total, success, message = payload
                    self.progress_var.set((done / total) * 100 if total else 0)
                    status = "OK" if success else "ERROR"
                    self._append_log(f"[{status}] {message}")
                elif event == "error":
                    self.start_button.configure(state="normal")
                    self._append_log(f"[ERROR] {payload}")
                    messagebox.showerror("Processing failed", payload)
                    return
                elif event == "done":
                    self.start_button.configure(state="normal")
                    self.progress_var.set(100)
                    self._show_result(payload)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_worker_queue)

    def _show_result(self, result: BatchResult) -> None:
        summary = f"Finished: {result.succeeded}/{result.total} succeeded, {result.failed} failed."
        self._append_log(summary)
        if result.errors:
            for error in result.errors:
                self._append_log(f"[ERROR] {error}")
        messagebox.showinfo("Processing complete", summary)

    def _append_log(self, message: str) -> None:
        get_logger().info(message)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
