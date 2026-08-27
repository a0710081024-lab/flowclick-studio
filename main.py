from __future__ import annotations

import tkinter as tk

from flowclick.automation import enable_dpi_awareness
from flowclick.gui import FlowClickApp


def main() -> None:
    enable_dpi_awareness()
    root = tk.Tk()
    FlowClickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
