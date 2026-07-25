"""File selection.

A native file dialog, because the people this tool is for should not have to
type a Windows path. tkinter ships with the python.org installer, so this costs
no dependency - but it is imported lazily and degrades to a typed prompt,
because some Linux distributions package Python without tk.
"""

from __future__ import annotations

from pathlib import Path


def _dialog_available() -> bool:
    try:
        import tkinter  # noqa: F401
        from tkinter import filedialog  # noqa: F401
    except Exception:
        return False
    return True


def _pick_with_dialog(title: str, initial_dir: Path | None) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()          # no empty window alongside the dialog
    root.attributes("-topmost", True)  # keep it above the terminal
    try:
        chosen = filedialog.askopenfilename(
            title=title,
            initialdir=str(initial_dir) if initial_dir else None,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
    finally:
        root.destroy()
    return chosen or None


def _pick_with_prompt(title: str) -> str | None:
    print(f"\n{title}")
    print("  Paste the full path to the file (or press Enter to cancel).")
    raw = input("  > ").strip().strip('"').strip("'")
    return raw or None


def choose_csv(title: str, initial_dir: Path | None = None) -> Path:
    """Ask the user for one CSV. Raises SystemExit if they cancel.

    Cancelling is a decision, not an error - so it exits cleanly rather than
    dumping a traceback on someone who simply changed their mind.
    """
    picker = _pick_with_dialog if _dialog_available() else _pick_with_prompt
    chosen = (
        picker(title, initial_dir) if picker is _pick_with_dialog else picker(title)
    )

    if not chosen:
        raise SystemExit("No file selected - nothing to reconcile.")

    path = Path(chosen).expanduser()
    if not path.is_file():
        raise SystemExit(f"Not a file: {path}")
    return path
