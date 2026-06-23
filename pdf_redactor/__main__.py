"""Command line entry point for running the desktop app."""

from __future__ import annotations

import tkinter as tk

from .app_logging import configure_logging
from .ui import PdfRedactorApp


def main() -> None:
    configure_logging()
    root = tk.Tk()
    app = PdfRedactorApp(root)
    app.run()


if __name__ == "__main__":
    main()
