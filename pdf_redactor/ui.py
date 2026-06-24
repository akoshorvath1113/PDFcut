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
from .pdf_merger import merge_pdfs


DEFAULT_RECT = RectConfig(0, 280, 595.276, 560)


class PdfRedactorApp:
    """Desktop app for batch redacting and merging PDFs."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PDF Batch Redactor")
        self.root.geometry("1100x720")
        self.root.minsize(820, 520)

        self.input_path_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.page_size_var = tk.StringVar(value="A4")
        self.suffix_var = tk.StringVar(value="_redacted")
        self.all_pages_var = tk.BooleanVar(value=True)
        self.selected_pages_var = tk.StringVar()
        self.collapse_var = tk.BooleanVar(value=True)
        self.x0_var = tk.StringVar(value=f"{DEFAULT_RECT.x0:g}")
        self.y0_var = tk.StringVar(value=f"{DEFAULT_RECT.y0:g}")
        self.x1_var = tk.StringVar(value=f"{DEFAULT_RECT.x1:g}")
        self.y1_var = tk.StringVar(value=f"{DEFAULT_RECT.y1:g}")
        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="Ready")
        self.merge_output_var = tk.StringVar()
        self.preview_zoom_label_var = tk.StringVar(value="Fit width")

        self.cut_rects: list[RectConfig] = [DEFAULT_RECT]
        self.merge_paths: list[Path] = []

        self.preview_doc: fitz.Document | None = None
        self.preview_pdf_path: Path | None = None
        self.preview_page_rect: fitz.Rect | None = None
        self.preview_scale = 1.0
        self.preview_origin = (0.0, 0.0)
        self.preview_image: tk.PhotoImage | None = None
        self.preview_zoom_mode = "fit_width"
        self.preview_manual_scale = 1.25
        self.drag_start_pdf: tuple[float, float] | None = None
        self.worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        self._configure_style()
        self._build_layout()
        self._toggle_page_selection()
        self._refresh_cut_list()
        self._render_preview()

    def run(self) -> None:
        self.root.mainloop()

    def _configure_style(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.root.configure(background="#eef2f7")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#eef2f7")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Header.TLabel", background="#1f2937", foreground="#ffffff", font=("Segoe UI", 18, "bold"))
        style.configure("Subheader.TLabel", background="#1f2937", foreground="#d1d5db", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#111827", font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#6b7280")
        style.configure("TLabel", background="#eef2f7", foreground="#111827")
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#1d4ed8")], foreground=[("active", "#ffffff")])

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, style="TFrame")
        header.grid(row=0, column=0, sticky="ew")
        self._build_header(header)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(10, 12))

        redact_tab = ttk.Frame(self.notebook)
        merge_tab = ttk.Frame(self.notebook)
        activity_tab = ttk.Frame(self.notebook)
        self.notebook.add(redact_tab, text="Redact / Cut PDFs")
        self.notebook.add(merge_tab, text="Merge PDFs")
        self.notebook.add(activity_tab, text="Activity")

        self._build_redact_tab(redact_tab)
        self._build_merge_tab(merge_tab)
        self._build_activity_tab(activity_tab)

        footer = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Progressbar(footer, variable=self.progress_var, maximum=100, length=180).grid(row=0, column=1, sticky="e")

    def _build_header(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        banner = tk.Frame(parent, background="#1f2937", padx=18, pady=16)
        banner.grid(row=0, column=0, sticky="ew")
        banner.columnconfigure(0, weight=1)
        ttk.Label(banner, text="PDF Batch Redactor", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            banner,
            text="Remove one or more sensitive areas, batch process standardized PDFs, or merge files in order.",
            style="Subheader.TLabel",
            wraplength=900,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_redact_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        splitter = ttk.PanedWindow(parent, orient="horizontal")
        splitter.grid(row=0, column=0, sticky="nsew")
        self.redact_splitter = splitter

        controls_area = ttk.Frame(splitter)
        controls_area.configure(width=440)
        controls_area.columnconfigure(0, weight=1)
        controls_area.rowconfigure(0, weight=1)
        preview_area = ttk.Frame(splitter, padding=(8, 10, 10, 10))
        preview_area.columnconfigure(0, weight=1)
        preview_area.rowconfigure(1, weight=1)

        splitter.add(controls_area, weight=0)
        splitter.add(preview_area, weight=1)
        self.root.after(200, lambda: splitter.sashpos(0, 440))

        controls = self._build_scrollable_controls(controls_area)
        self._build_input_card(controls)
        self._build_settings_card(controls)
        self._build_cuts_card(controls)
        self._build_preview_card(preview_area)

    def _build_scrollable_controls(self, parent: ttk.Frame) -> ttk.Frame:
        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        canvas = tk.Canvas(container, width=420, background="#eef2f7", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        controls = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=controls, anchor="nw")

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        controls.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.bind("<Enter>", lambda _event: self._bind_mousewheel(canvas))
        canvas.bind("<Leave>", lambda _event: self._unbind_mousewheel(canvas))
        return controls

    def _bind_mousewheel(self, canvas: tk.Canvas) -> None:
        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        canvas.bind_all("<Button-4>", lambda _event: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda _event: canvas.yview_scroll(1, "units"))

    def _unbind_mousewheel(self, canvas: tk.Canvas) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    def _build_input_card(self, parent: ttk.Frame) -> None:
        frame = self._card(parent, "1. Choose input and output", row=0)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="PDF file or folder", style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Entry(frame, textvariable=self.input_path_var, width=34).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        ttk.Button(frame, text="Select PDF", command=self._choose_pdf).grid(row=3, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(frame, text="Select Folder", command=self._choose_folder).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))
        ttk.Button(frame, text="Load selected preview", command=self._load_preview_from_input).grid(row=4, column=0, columnspan=2, sticky="ew")

        ttk.Label(frame, text="Output folder", style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Entry(frame, textvariable=self.output_folder_var, width=34).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        ttk.Button(frame, text="Choose output folder", command=self._choose_output_folder).grid(row=7, column=0, columnspan=2, sticky="ew")

    def _build_settings_card(self, parent: ttk.Frame) -> None:
        frame = self._card(parent, "2. Configure processing", row=1)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Page size", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.page_size_var,
            values=list(PAGE_SIZES.keys()),
            state="readonly",
            width=18,
        ).grid(row=1, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(frame, text="Filename suffix", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.suffix_var).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(
            frame,
            text="Apply to all pages",
            variable=self.all_pages_var,
            command=self._toggle_page_selection,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(frame, text="Selected pages", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.selected_pages_entry = ttk.Entry(frame, textvariable=self.selected_pages_var)
        self.selected_pages_entry.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(frame, text="Example: 1,3-5", style="Muted.TLabel").grid(row=5, column=1, sticky="w")

        ttk.Checkbutton(
            frame,
            text="Collapse vertical gaps after removal",
            variable=self.collapse_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_cuts_card(self, parent: ttk.Frame) -> None:
        frame = self._card(parent, "3. Add one or more cuts", row=2)
        for column in range(2):
            frame.columnconfigure(column, weight=1)

        entries = (
            ("x0", self.x0_var),
            ("y0", self.y0_var),
            ("x1", self.x1_var),
            ("y1", self.y1_var),
        )
        for index, (label, variable) in enumerate(entries):
            row = 1 + (index // 2) * 2
            column = index % 2
            ttk.Label(frame, text=label, style="Muted.TLabel").grid(row=row, column=column, sticky="w", padx=(0 if column == 0 else 8, 0))
            ttk.Entry(frame, textvariable=variable, width=10).grid(
                row=row + 1,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 8, 0),
                pady=(0, 6),
            )

        ttk.Button(frame, text="Add cut", command=self._add_cut).grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(frame, text="Update selected", command=self._update_selected_cut).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Button(frame, text="Remove selected", command=self._remove_selected_cut).grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(frame, text="Clear cuts", command=self._clear_cuts).grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        self.cut_listbox = tk.Listbox(frame, height=5, exportselection=False)
        self.cut_listbox.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.cut_listbox.bind("<<ListboxSelect>>", self._on_cut_selected)

        ttk.Label(
            frame,
            text="Tip: drag on the preview to fill the coordinate boxes, then click Add cut.",
            style="Muted.TLabel",
            wraplength=360,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.start_button = ttk.Button(frame, text="Start redaction batch", style="Accent.TButton", command=self._start_processing)
        self.start_button.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def _build_preview_card(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, text="Preview and visual selector", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(toolbar, text="Fit page", command=self._fit_preview_page).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(toolbar, text="Fit width", command=self._fit_preview_width).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(toolbar, text="100%", command=self._set_preview_actual_size).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(toolbar, text="-", width=3, command=lambda: self._zoom_preview(0.85)).grid(row=0, column=4, padx=(6, 0))
        ttk.Label(toolbar, textvariable=self.preview_zoom_label_var, width=10, anchor="center").grid(row=0, column=5, padx=(6, 0))
        ttk.Button(toolbar, text="+", width=3, command=lambda: self._zoom_preview(1.18)).grid(row=0, column=6, padx=(6, 0))

        canvas_frame = ttk.Frame(parent)
        canvas_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, background="#f8fafc", highlightthickness=1, highlightbackground="#cbd5e1")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        x_scrollbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        y_scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        x_scrollbar.grid(row=1, column=0, sticky="ew")
        y_scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=x_scrollbar.set, yscrollcommand=y_scrollbar.set)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<MouseWheel>", self._on_preview_mousewheel)
        self.canvas.bind("<Button-4>", lambda _event: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda _event: self.canvas.yview_scroll(3, "units"))
        self.canvas.bind("<Configure>", lambda _event: self._render_preview())

    def _build_merge_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Merge PDFs", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            top,
            text="Add PDFs, arrange them in the exact order you want, then create one merged copy.",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        body = ttk.Frame(parent, padding=(12, 0, 12, 12))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.merge_listbox = tk.Listbox(body, height=16, exportselection=False)
        self.merge_listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.merge_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.merge_listbox.configure(yscrollcommand=scrollbar.set)

        buttons = ttk.Frame(body)
        buttons.grid(row=0, column=2, sticky="ns", padx=(10, 0))
        ttk.Button(buttons, text="Add PDFs", command=self._add_merge_pdfs).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(buttons, text="Remove", command=self._remove_merge_pdf).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(buttons, text="Move up", command=lambda: self._move_merge_pdf(-1)).grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(buttons, text="Move down", command=lambda: self._move_merge_pdf(1)).grid(row=3, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(buttons, text="Clear", command=self._clear_merge_pdfs).grid(row=4, column=0, sticky="ew")

        output = ttk.Frame(body)
        output.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        output.columnconfigure(0, weight=1)
        ttk.Label(output, text="Merged output file").grid(row=0, column=0, sticky="w")
        ttk.Entry(output, textvariable=self.merge_output_var).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(output, text="Browse", command=self._choose_merge_output).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(4, 0))
        ttk.Button(output, text="Merge PDFs", style="Accent.TButton", command=self._start_merge).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def _build_activity_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log_text = tk.Text(parent, state="disabled", wrap="word", background="#0f172a", foreground="#e5e7eb")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=12)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _card(self, parent: ttk.Frame, title: str, row: int) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=12)
        outer.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)
        ttk.Label(outer, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        return outer

    def _choose_pdf(self) -> None:
        path = filedialog.askopenfilename(title="Select PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            self.input_path_var.set(path)
            self._set_default_output_folder(Path(path).parent / "redacted_output")
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
            self.output_folder_var.set(str(folder))

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

    def _fit_preview_page(self) -> None:
        self.preview_zoom_mode = "fit_page"
        self._render_preview()

    def _fit_preview_width(self) -> None:
        self.preview_zoom_mode = "fit_width"
        self._render_preview()

    def _set_preview_actual_size(self) -> None:
        self.preview_zoom_mode = "manual"
        self.preview_manual_scale = 1.0
        self._render_preview()

    def _zoom_preview(self, factor: float) -> None:
        if self.preview_zoom_mode != "manual":
            self.preview_manual_scale = self.preview_scale
            self.preview_zoom_mode = "manual"
        self.preview_manual_scale = min(max(self.preview_manual_scale * factor, 0.25), 4.0)
        self._render_preview()

    def _on_preview_mousewheel(self, event: tk.Event[tk.Misc]) -> str | None:
        if event.state & 0x0004:
            self._zoom_preview(1.12 if event.delta > 0 else 0.89)
            return "break"
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)) * 3, "units")
        return "break"

    def _render_preview(self) -> None:
        if not hasattr(self, "canvas"):
            return
        if self.preview_doc is None or self.preview_page_rect is None:
            self.canvas.delete("all")
            self.canvas.create_text(24, 24, anchor="nw", text="Select a PDF to preview and draw cut rectangles.", fill="#475569")
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            return

        page = self.preview_doc.load_page(0)
        canvas_width = max(self.canvas.winfo_width(), 220)
        canvas_height = max(self.canvas.winfo_height(), 260)
        available_width = max(canvas_width - 36, 120)
        available_height = max(canvas_height - 36, 120)
        if self.preview_zoom_mode == "fit_page":
            scale = min(available_width / page.rect.width, available_height / page.rect.height, 2.0)
            self.preview_zoom_label_var.set("Fit page")
        elif self.preview_zoom_mode == "fit_width":
            scale = min(available_width / page.rect.width, 3.0)
            self.preview_zoom_label_var.set("Fit width")
        else:
            scale = self.preview_manual_scale
            self.preview_zoom_label_var.set(f"{scale * 100:.0f}%")

        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        self.preview_image = tk.PhotoImage(data=pixmap.tobytes("png"))
        image_width = self.preview_image.width()
        image_height = self.preview_image.height()
        origin_x = max(18, (canvas_width - image_width) / 2)
        origin_y = max(18, (canvas_height - image_height) / 2)

        self.preview_scale = scale
        self.preview_origin = (origin_x, origin_y)
        self.canvas.delete("all")
        self.canvas.create_image(origin_x, origin_y, anchor="nw", image=self.preview_image)
        self._draw_all_cuts()
        self._update_preview_scrollregion()

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

    def _add_cut(self) -> None:
        try:
            rect = self._rect_from_fields()
            rect.validate()
        except ValueError as exc:
            messagebox.showerror("Invalid cut", str(exc))
            return
        self.cut_rects.append(rect)
        self._refresh_cut_list(select_index=len(self.cut_rects) - 1)

    def _update_selected_cut(self) -> None:
        index = self._selected_cut_index()
        if index is None:
            messagebox.showwarning("No cut selected", "Select a cut from the list first.")
            return
        try:
            rect = self._rect_from_fields()
            rect.validate()
        except ValueError as exc:
            messagebox.showerror("Invalid cut", str(exc))
            return
        self.cut_rects[index] = rect
        self._refresh_cut_list(select_index=index)

    def _remove_selected_cut(self) -> None:
        index = self._selected_cut_index()
        if index is None:
            return
        del self.cut_rects[index]
        self._refresh_cut_list(select_index=max(0, index - 1))

    def _clear_cuts(self) -> None:
        self.cut_rects.clear()
        self._refresh_cut_list()

    def _on_cut_selected(self, _event: tk.Event[tk.Misc]) -> None:
        index = self._selected_cut_index()
        if index is None:
            return
        self._set_rect_fields_from_rect(self.cut_rects[index])
        self._draw_all_cuts()

    def _refresh_cut_list(self, select_index: int | None = None) -> None:
        self.cut_listbox.delete(0, "end")
        for index, rect in enumerate(self.cut_rects, start=1):
            self.cut_listbox.insert("end", f"{index}. {_format_rect(rect)}")
        if self.cut_rects and select_index is not None:
            select_index = min(select_index, len(self.cut_rects) - 1)
            self.cut_listbox.selection_set(select_index)
            self.cut_listbox.see(select_index)
        self._draw_all_cuts()

    def _selected_cut_index(self) -> int | None:
        selection = self.cut_listbox.curselection()
        if not selection:
            return None
        return int(selection[0])

    def _draw_all_cuts(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("selection")
        if self.preview_page_rect is None:
            return
        selected_index = self._selected_cut_index() if hasattr(self, "cut_listbox") else None
        for index, rect in enumerate(self.cut_rects):
            x0, y0 = self._pdf_to_canvas(rect.x0, rect.y0)
            x1, y1 = self._pdf_to_canvas(rect.x1, rect.y1)
            outline = "#dc2626" if index == selected_index else "#2563eb"
            width = 3 if index == selected_index else 2
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=outline, width=width, tags="selection")
            self.canvas.create_text(x0 + 5, y0 + 5, anchor="nw", text=str(index + 1), fill=outline, tags="selection")
        self._update_preview_scrollregion()

    def _update_preview_scrollregion(self) -> None:
        if hasattr(self, "canvas"):
            bbox = self.canvas.bbox("all")
            if bbox is not None:
                self.canvas.configure(scrollregion=(bbox[0] - 20, bbox[1] - 20, bbox[2] + 20, bbox[3] + 20))

    def _on_canvas_press(self, event: tk.Event[tk.Misc]) -> None:
        if self.preview_page_rect is None:
            return
        self.drag_start_pdf = self._canvas_to_pdf(event.x, event.y)

    def _on_canvas_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self.drag_start_pdf is None:
            return
        end_pdf = self._canvas_to_pdf(event.x, event.y)
        self._set_rect_fields(self.drag_start_pdf, end_pdf)
        self._draw_temporary_rect()

    def _on_canvas_release(self, event: tk.Event[tk.Misc]) -> None:
        if self.drag_start_pdf is None:
            return
        end_pdf = self._canvas_to_pdf(event.x, event.y)
        self._set_rect_fields(self.drag_start_pdf, end_pdf)
        self.drag_start_pdf = None
        self._draw_temporary_rect()

    def _draw_temporary_rect(self) -> None:
        self._draw_all_cuts()
        try:
            rect = self._rect_from_fields()
            rect.validate()
        except ValueError:
            return
        if self.preview_page_rect is None:
            return
        x0, y0 = self._pdf_to_canvas(rect.x0, rect.y0)
        x1, y1 = self._pdf_to_canvas(rect.x1, rect.y1)
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="#f97316", width=2, dash=(4, 3), tags="selection")

    def _canvas_to_pdf(self, x: float, y: float) -> tuple[float, float]:
        if self.preview_page_rect is None:
            return (0.0, 0.0)
        canvas_x = self.canvas.canvasx(x)
        canvas_y = self.canvas.canvasy(y)
        origin_x, origin_y = self.preview_origin
        pdf_x = (canvas_x - origin_x) / self.preview_scale
        pdf_y = (canvas_y - origin_y) / self.preview_scale
        pdf_x = min(max(pdf_x, 0.0), self.preview_page_rect.width)
        pdf_y = min(max(pdf_y, 0.0), self.preview_page_rect.height)
        return (pdf_x, pdf_y)

    def _pdf_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y = self.preview_origin
        return (origin_x + x * self.preview_scale, origin_y + y * self.preview_scale)

    def _set_rect_fields(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        rect = RectConfig(start[0], start[1], end[0], end[1]).normalized()
        self._set_rect_fields_from_rect(rect)

    def _set_rect_fields_from_rect(self, rect: RectConfig) -> None:
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
            if not self.cut_rects:
                raise ValueError("Add at least one cut rectangle.")
            config = ProcessingConfig(
                page_size_name=self.page_size_var.get(),
                remove_rects=tuple(self.cut_rects),
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
        self.status_var.set("Redaction batch running...")
        self._append_log("Starting redaction batch...")

        thread = threading.Thread(target=self._redaction_worker, args=(input_path, config), daemon=True)
        thread.start()
        self.root.after(100, self._poll_worker_queue)

    def _redaction_worker(self, input_path: Path, config: ProcessingConfig) -> None:
        logger = configure_logging(config.output_folder)

        def callback(done: int, total: int, path: Path, success: bool, message: str) -> None:
            logger.info("%s: %s", path.name, message)
            self.worker_queue.put(("redact_progress", (done, total, success, message)))

        try:
            result = process_batch(input_path, config, callback)
        except Exception as exc:  # noqa: BLE001 - UI should show friendly errors.
            logger.exception("Redaction batch failed")
            self.worker_queue.put(("redact_error", str(exc)))
        else:
            self.worker_queue.put(("redact_done", result))

    def _add_merge_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(title="Select PDFs to merge", filetypes=[("PDF files", "*.pdf")])
        for path_text in paths:
            path = Path(path_text)
            if path not in self.merge_paths:
                self.merge_paths.append(path)
        self._refresh_merge_list()
        if paths and not self.merge_output_var.get().strip():
            first = Path(paths[0])
            self.merge_output_var.set(str(first.parent / "merged.pdf"))

    def _remove_merge_pdf(self) -> None:
        selection = self.merge_listbox.curselection()
        if not selection:
            return
        index = int(selection[0])
        del self.merge_paths[index]
        self._refresh_merge_list(select_index=max(0, index - 1))

    def _move_merge_pdf(self, direction: int) -> None:
        selection = self.merge_listbox.curselection()
        if not selection:
            return
        index = int(selection[0])
        new_index = index + direction
        if new_index < 0 or new_index >= len(self.merge_paths):
            return
        self.merge_paths[index], self.merge_paths[new_index] = self.merge_paths[new_index], self.merge_paths[index]
        self._refresh_merge_list(select_index=new_index)

    def _clear_merge_pdfs(self) -> None:
        self.merge_paths.clear()
        self._refresh_merge_list()

    def _refresh_merge_list(self, select_index: int | None = None) -> None:
        self.merge_listbox.delete(0, "end")
        for index, path in enumerate(self.merge_paths, start=1):
            self.merge_listbox.insert("end", f"{index}. {path.name}   ({path.parent})")
        if self.merge_paths and select_index is not None:
            select_index = min(select_index, len(self.merge_paths) - 1)
            self.merge_listbox.selection_set(select_index)
            self.merge_listbox.see(select_index)

    def _choose_merge_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save merged PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.merge_output_var.set(path)

    def _start_merge(self) -> None:
        try:
            if len(self.merge_paths) < 2:
                raise ValueError("Add at least two PDFs to merge.")
            output_text = self.merge_output_var.get().strip()
            if not output_text:
                raise ValueError("Choose the merged output PDF path.")
            output_path = Path(output_text)
        except ValueError as exc:
            messagebox.showerror("Invalid merge settings", str(exc))
            return

        self.progress_var.set(0)
        self.status_var.set("Merging PDFs...")
        self._append_log("Starting PDF merge...")
        thread = threading.Thread(target=self._merge_worker, args=(list(self.merge_paths), output_path), daemon=True)
        thread.start()
        self.root.after(100, self._poll_worker_queue)

    def _merge_worker(self, input_paths: list[Path], output_path: Path) -> None:
        try:
            merge_pdfs(input_paths, output_path)
        except Exception as exc:  # noqa: BLE001 - UI should show friendly errors.
            self.worker_queue.put(("merge_error", str(exc)))
        else:
            self.worker_queue.put(("merge_done", output_path))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                event, payload = self.worker_queue.get_nowait()
                if event == "redact_progress":
                    done, total, success, message = payload
                    self.progress_var.set((done / total) * 100 if total else 0)
                    status = "OK" if success else "ERROR"
                    self._append_log(f"[{status}] {message}")
                elif event == "redact_error":
                    self.start_button.configure(state="normal")
                    self.status_var.set("Redaction failed")
                    self._append_log(f"[ERROR] {payload}")
                    messagebox.showerror("Processing failed", payload)
                    return
                elif event == "redact_done":
                    self.start_button.configure(state="normal")
                    self.progress_var.set(100)
                    self._show_redaction_result(payload)
                    return
                elif event == "merge_error":
                    self.progress_var.set(0)
                    self.status_var.set("Merge failed")
                    self._append_log(f"[ERROR] {payload}")
                    messagebox.showerror("Merge failed", payload)
                    return
                elif event == "merge_done":
                    self.progress_var.set(100)
                    self.status_var.set("Merge complete")
                    self._append_log(f"[OK] Saved merged PDF: {payload}")
                    messagebox.showinfo("Merge complete", f"Saved merged PDF:\n{payload}")
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_worker_queue)

    def _show_redaction_result(self, result: BatchResult) -> None:
        summary = f"Finished: {result.succeeded}/{result.total} succeeded, {result.failed} failed."
        self.status_var.set(summary)
        self._append_log(summary)
        if result.errors:
            for error in result.errors:
                self._append_log(f"[ERROR] {error}")
        messagebox.showinfo("Processing complete", summary)

    def _append_log(self, message: str) -> None:
        get_logger().info(message)
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def _format_rect(rect: RectConfig) -> str:
    return f"x0={rect.x0:.2f}, y0={rect.y0:.2f}, x1={rect.x1:.2f}, y1={rect.y1:.2f}"
