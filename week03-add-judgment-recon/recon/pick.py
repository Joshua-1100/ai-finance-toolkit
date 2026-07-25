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


def choose_save_path(default: Path) -> Path:
    """Ask where to save the workbook, defaulting to the suggested path.

    Falls back to the default without asking when there is no dialog available,
    since the run has already done its work by this point and losing it to a
    missing tk install would be absurd.
    """
    if not _dialog_available():
        return default

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.asksaveasfilename(
            title="Save the reconciliation workbook",
            initialdir=str(default.parent),
            initialfile=default.name,
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
    finally:
        root.destroy()

    return Path(chosen).expanduser() if chosen else default
