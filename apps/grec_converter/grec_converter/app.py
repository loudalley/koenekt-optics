"""Main window: drop zone, queue with per-file checkboxes, output options."""
import logging
import os
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from koenekt_codecs import FORMATS

from . import APP_ID, APP_NAME, VERSION, settings, theme
from .paths import log_file, resource
from .theme import BORDER, GREEN, GREEN_TINT, INK, MUTED, SURFACE, WHITE
from .worker import BatchWorker

log = logging.getLogger(__name__)

CHECKED, UNCHECKED = "\u2611", "\u2610"
FORMAT_HINTS = {
    "mp4": "Recommended. Keeps the recording's original frame timing; plays almost everywhere.",
    "avi": "For older players and editors (Xvid-compatible). Constant 25 fps; files are roughly twice the size.",
}
STATUS_TAGS = {"converted": "ok", "skipped": "muted", "failed": "bad", "cancelled": "muted"}

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # drag and drop is a convenience; the buttons still work
    DND_FILES = TkinterDnD = None


def create_root():
    try:  # crisp text on scaled displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk(), True
        except Exception as error:
            log.warning("Drag and drop unavailable: %s", error)
    return tk.Tk(), False


def human_size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024


class App:
    def __init__(self, root, dnd):
        self.root = root
        self.dnd = dnd
        self.settings = settings.load()
        self.rows = {}           # iid -> {"path", "checked", "state", "message", "output"}
        self.worker = None
        self.events = queue.Queue()
        self.batch_total = 0
        self.batch_done = 0
        self.closing = False

        root.title(APP_NAME)
        root.configure(bg=WHITE)
        self.scale = max(root.winfo_fpixels("1i") / 96, 1.0)
        self._set_icon()
        theme.apply(root, self.scale)
        root.report_callback_exception = self._on_ui_error

        self.format_var = tk.StringVar(value=self.settings.get("format", "mp4"))
        self.output_var = tk.StringVar(value=self.settings.get("output_dir", ""))
        self.subfolders_var = tk.BooleanVar(value=self.settings.get("include_subfolders", True))
        self.all_var = tk.BooleanVar(value=False)

        self._build()
        self._place_window()
        self.output_var.trace_add("write", lambda *_: self._update_controls())
        self.format_var.trace_add("write", lambda *_: self._on_format())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._on_format()
        self._update_controls()
        root.after(100, self._poll)

    # ------------------------------------------------------------------ layout
    def _set_icon(self):
        try:
            self.root.iconbitmap(default=str(resource("brand", "koenekt-cctv.ico")))
        except tk.TclError:
            pass
        try:  # large PNG so Alt-Tab and high-DPI taskbars stay crisp
            self._icon_img = tk.PhotoImage(file=str(resource("brand", "koenekt-cctv-256.png")))
            self.root.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass

    def _place_window(self):
        r = self.root
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w = min(int(1000 * self.scale), sw - 40)
        h = min(int(760 * self.scale), sh - 80)
        r.geometry(f"{w}x{h}+{max((sw - w) // 2, 0)}+{max((sh - h) // 3, 0)}")
        r.minsize(int(760 * self.scale), int(600 * self.scale))

    def _build(self):
        theme.header(self.root, "GREC Converter",
                     "Convert SureCam / CMSV6 .grec recordings to MP4 or AVI")
        self._build_footer()
        body = tk.Frame(self.root, bg=WHITE, padx=22, pady=14)
        body.pack(fill="both", expand=True)
        # Options are packed against the bottom first so a short window
        # squeezes the queue, never the output-folder controls.
        self._build_drop_zone(body)
        self._build_options(body)
        self._build_queue(body)

    def _build_drop_zone(self, parent):
        self.drop = tk.Canvas(parent, height=int(118 * self.scale), bg=SURFACE,
                              highlightthickness=0, bd=0)
        self.drop.pack(fill="x")
        actions = tk.Frame(self.drop, bg=SURFACE)
        for text, command in (("Add files\u2026", self.add_files_dialog),
                              ("Add folder\u2026", self.add_folder_dialog)):
            theme.button(actions, text, command, bg=WHITE).pack(side="left", padx=4)
        self.drop_actions = actions
        self.drop.bind("<Configure>", lambda _e: self._draw_drop_zone())

        opts = tk.Frame(parent, bg=WHITE)
        opts.pack(fill="x", pady=(6, 0))
        theme.checkbox(opts, "Include subfolders when adding a folder",
                       self.subfolders_var, self._save_settings).pack(side="left")
        if not self.dnd:
            tk.Label(opts, text="Drag and drop is unavailable on this PC; use the buttons above.",
                     bg=WHITE, fg=MUTED, font=theme.SMALL).pack(side="right")
        else:
            for widget in (self.drop, self.root):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            self.drop.dnd_bind("<<DropEnter>>", lambda e: self._draw_drop_zone(True) or e.action)
            self.drop.dnd_bind("<<DropLeave>>", lambda e: self._draw_drop_zone(False) or e.action)

    def _draw_drop_zone(self, hover=False):
        c = self.drop
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        c.configure(bg=GREEN_TINT if hover else SURFACE)
        self.drop_actions.configure(bg=GREEN_TINT if hover else SURFACE)
        c.create_rectangle(6, 6, w - 6, h - 6, outline=GREEN if hover else "#B9C9BC",
                           width=2, dash=(7, 5))
        title = "Release to add" if hover else "Drop folders or .grec files here"
        c.create_text(w // 2, int(h * 0.30), text=title, fill=INK, font=(theme.FONT, 13, "bold"))
        c.create_text(w // 2, int(h * 0.30) + int(22 * self.scale),
                      text="or choose them yourself" if self.dnd else "choose recordings to convert",
                      fill=MUTED, font=theme.SMALL)
        c.create_window(w // 2, int(h * 0.76), window=self.drop_actions)

    def _build_queue(self, parent):
        bar = tk.Frame(parent, bg=WHITE)
        bar.pack(fill="x", pady=(14, 6))
        self.all_check = theme.checkbox(bar, "Select all", self.all_var, self._toggle_all)
        self.all_check.pack(side="left")
        self.count_label = tk.Label(bar, text="", bg=WHITE, fg=MUTED, font=theme.SMALL)
        self.count_label.pack(side="left", padx=(14, 0))
        self.clear_btn = theme.button(bar, "Clear list", self.clear_list)
        self.clear_btn.pack(side="right")
        self.remove_btn = theme.button(bar, "Remove ticked", self.remove_checked)
        self.remove_btn.pack(side="right", padx=(0, 6))

        self.details = tk.Label(parent, text="", bg=WHITE, fg=MUTED, font=theme.SMALL,
                                anchor="w", justify="left")
        self.details.pack(fill="x", side="bottom", pady=(4, 0))
        self.details.bind("<Configure>", lambda e: self.details.configure(wraplength=e.width))

        frame = tk.Frame(parent, bg=BORDER, bd=0)
        frame.pack(fill="both", expand=True)
        cols = ("sel", "name", "folder", "size", "status")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended",
                                 height=6)
        s = self.scale
        for col, text, width, stretch, anchor in (
                ("sel", CHECKED, 40, False, "center"),
                ("name", "Recording", 250, True, "w"),
                ("folder", "Folder", 230, True, "w"),
                ("size", "Size", 80, False, "e"),
                ("status", "Status", 230, True, "w")):
            self.tree.heading(col, text=text, anchor=anchor,
                              command=self._toggle_all_from_heading if col == "sel" else "")
            self.tree.column(col, width=int(width * s), minwidth=int(min(width, 60) * s),
                             stretch=stretch, anchor=anchor)
        self.tree.tag_configure("ok", foreground="#3F7A05")
        self.tree.tag_configure("bad", foreground=theme.DANGER)
        self.tree.tag_configure("muted", foreground=MUTED)
        self.tree.tag_configure("running", foreground=INK, background=GREEN_TINT)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Delete>", lambda _e: self.remove_highlighted())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_details())
        self.tree.bind("<Double-1>", self._on_double_click)

        self.empty_hint = tk.Label(self.tree, text="No recordings added yet.",
                                   bg=WHITE, fg=MUTED, font=theme.BODY)

    def _build_options(self, parent):
        box = tk.Frame(parent, bg=WHITE)
        box.pack(fill="x", side="bottom", pady=(10, 0))
        box.columnconfigure(1, weight=1)

        tk.Label(box, text="Convert to", bg=WHITE, fg=INK, font=theme.BOLD).grid(
            row=0, column=0, sticky="w", pady=4)
        fmt = tk.Frame(box, bg=WHITE)
        fmt.grid(row=0, column=1, columnspan=2, sticky="w", padx=(14, 0))
        self.format_radios = []
        for key, spec in FORMATS.items():
            rb = theme.radio(fmt, spec["label"], self.format_var, key)
            rb.pack(side="left", padx=(0, 16))
            self.format_radios.append(rb)
        self.format_hint = tk.Label(box, text="", bg=WHITE, fg=MUTED, font=theme.SMALL, anchor="w")
        self.format_hint.grid(row=1, column=1, columnspan=2, sticky="w", padx=(14, 0))

        tk.Label(box, text="Save to", bg=WHITE, fg=INK, font=theme.BOLD).grid(
            row=2, column=0, sticky="w", pady=(12, 4))
        self.output_entry = tk.Entry(box, textvariable=self.output_var, relief="flat", bd=4,
                                     font=theme.BODY, fg=INK, highlightthickness=1,
                                     highlightbackground=BORDER, highlightcolor=GREEN,
                                     insertbackground=INK)
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=(14, 6), pady=(12, 4))
        self.browse_btn = theme.button(box, "Browse\u2026", self.choose_output)
        self.browse_btn.grid(row=2, column=2, sticky="e", pady=(12, 4))
        self.output_hint = tk.Label(box, text="Choose where the converted files are saved. "
                                    "Originals are never changed.",
                                    bg=WHITE, fg=MUTED, font=theme.SMALL, anchor="w")
        self.output_hint.grid(row=3, column=1, columnspan=2, sticky="w", padx=(14, 0))

    def _build_footer(self):
        foot = tk.Frame(self.root, bg=SURFACE, padx=22, pady=12)
        foot.pack(fill="x", side="bottom")
        tk.Frame(self.root, height=1, bg=BORDER).pack(fill="x", side="bottom")

        prog = tk.Frame(foot, bg=SURFACE)
        prog.pack(fill="x")
        prog.columnconfigure(1, weight=1)
        self.file_label = tk.Label(prog, text="Current file", bg=SURFACE, fg=MUTED,
                                   font=theme.SMALL, anchor="w", width=14)
        self.file_label.grid(row=0, column=0, sticky="w")
        self.file_bar = ttk.Progressbar(prog, style="KoenektFile.Horizontal.TProgressbar",
                                        maximum=1.0)
        self.file_bar.grid(row=0, column=1, sticky="ew", pady=2)
        tk.Label(prog, text="All files", bg=SURFACE, fg=MUTED, font=theme.SMALL,
                 anchor="w", width=14).grid(row=1, column=0, sticky="w")
        self.total_bar = ttk.Progressbar(prog, style="Koenekt.Horizontal.TProgressbar",
                                         maximum=1.0)
        self.total_bar.grid(row=1, column=1, sticky="ew", pady=2)

        row = tk.Frame(foot, bg=SURFACE)
        row.pack(fill="x", pady=(10, 0))
        self.status = tk.Label(row, text="Ready.", bg=SURFACE, fg=INK, font=theme.BODY,
                               anchor="w", justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        self.report_link = theme.link(row, "View report", self.open_report, bg=SURFACE)
        self.report_path = None
        self.convert_btn = theme.button(row, "Convert", self.start, primary=True)
        self.convert_btn.pack(side="right")
        self.cancel_btn = theme.button(row, "Cancel", self.cancel)
        self.cancel_btn.pack(side="right", padx=(0, 6))
        self.open_btn = theme.button(row, "Open output folder", self.open_output)
        self.open_btn.pack(side="right", padx=(0, 6))
        tk.Label(foot, text=f"Version {VERSION}  \u00b7  Koenekt Optics", bg=SURFACE,
                 fg="#8A968E", font=(theme.FONT, 8)).pack(anchor="w", pady=(8, 0))

    # ------------------------------------------------------------- queue
    def _on_drop(self, event):
        self._draw_drop_zone(False)
        if self.busy:
            self._set_status("Wait for the current conversion to finish before adding files.")
            return event.action
        self.add_paths(self.root.tk.splitlist(event.data))
        return event.action

    def add_files_dialog(self):
        files = filedialog.askopenfilenames(parent=self.root, title="Choose GREC recordings",
                                            filetypes=[("GREC recordings", "*.grec"),
                                                       ("All files", "*.*")])
        if files:
            self.add_paths(files)

    def add_folder_dialog(self):
        folder = filedialog.askdirectory(parent=self.root, title="Choose a folder of recordings",
                                         mustexist=True)
        if folder:
            self.add_paths([folder])

    def _scan(self, folder):
        pattern = folder.rglob if self.subfolders_var.get() else folder.glob
        try:
            return sorted((p for p in pattern("*.grec") if p.is_file()),
                          key=lambda p: str(p).lower())
        except OSError as error:
            log.warning("Could not scan %s: %s", folder, error)
            return []

    def add_paths(self, values):
        if self.busy:
            return
        added = ignored = 0
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            for value in values:
                path = Path(value)
                if path.is_dir():
                    candidates = self._scan(path)
                elif path.suffix.lower() == ".grec" and path.is_file():
                    candidates = [path]
                else:
                    ignored += 1
                    continue
                for file in candidates:
                    iid = os.path.normcase(str(file.resolve()))
                    if iid in self.rows:
                        continue
                    try:
                        size = file.stat().st_size
                    except OSError:
                        size = 0
                    self.rows[iid] = {"path": file, "checked": True, "state": "queued",
                                      "message": "", "output": ""}
                    self.tree.insert("", "end", iid=iid, values=(
                        CHECKED, file.name, str(file.parent), human_size(size), "Waiting"))
                    added += 1
        finally:
            self.root.configure(cursor="")
        note = f"Added {added} recording{'s' if added != 1 else ''}."
        if not added:
            note = "No new .grec recordings found."
        if ignored:
            note += f" {ignored} item{'s' if ignored != 1 else ''} ignored (not .grec)."
        self._set_status(note)
        self._update_controls()

    def _set_checked(self, iid, value):
        row = self.rows[iid]
        row["checked"] = value
        self.tree.set(iid, "sel", CHECKED if value else UNCHECKED)

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.tree.identify_column(event.x) != "#1":
            return None
        iid = self.tree.identify_row(event.y)
        if iid and not self.busy:
            self._set_checked(iid, not self.rows[iid]["checked"])
            self._update_controls()
        return "break"

    def _on_space(self, _event):
        if self.busy:
            return "break"
        selection = self.tree.selection()
        if selection:
            value = not all(self.rows[i]["checked"] for i in selection)
            for iid in selection:
                self._set_checked(iid, value)
            self._update_controls()
        return "break"

    def _toggle_all(self):
        for iid in self.rows:
            self._set_checked(iid, self.all_var.get())
        self._update_controls()

    def _toggle_all_from_heading(self):
        if self.busy or not self.rows:
            return
        self.all_var.set(not all(r["checked"] for r in self.rows.values()))
        self._toggle_all()

    def remove_checked(self):
        for iid in [i for i, r in self.rows.items() if r["checked"]]:
            self.tree.delete(iid)
            del self.rows[iid]
        self._show_details()
        self._update_controls()

    def remove_highlighted(self):
        if self.busy:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.rows.pop(iid, None)
        self._update_controls()

    def clear_list(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.file_bar["value"] = self.total_bar["value"] = 0
        self._show_details()
        self._update_controls()

    def _show_details(self):
        focus = self.tree.focus()
        row = self.rows.get(focus)
        if not row:
            self.details.configure(text="")
            return
        text = str(row["path"])
        if row["message"] and row["state"] != "queued":
            text += "\n" + row["message"]
        self.details.configure(text=text, fg=theme.DANGER if row["state"] == "failed" else MUTED)

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        row = self.rows.get(iid)
        if row and row["state"] == "converted" and Path(row["output"]).exists():
            os.startfile(row["output"])

    # ------------------------------------------------------------- options
    def _on_format(self):
        self.format_hint.configure(text=FORMAT_HINTS.get(self.format_var.get(), ""))
        self._save_settings()

    def choose_output(self):
        folder = filedialog.askdirectory(parent=self.root, title="Save converted files to",
                                         initialdir=self.output_var.get() or None)
        if folder:
            self.output_var.set(str(Path(folder)))
            self._save_settings()

    def _save_settings(self):
        self.settings.update(format=self.format_var.get(), output_dir=self.output_var.get().strip(),
                             include_subfolders=bool(self.subfolders_var.get()))
        settings.save(self.settings)

    def open_output(self):
        folder = self.output_var.get().strip()
        if folder and Path(folder).is_dir():
            os.startfile(folder)
        else:
            messagebox.showinfo(APP_NAME, "The output folder does not exist yet.", parent=self.root)

    def open_report(self):
        if self.report_path and Path(self.report_path).exists():
            os.startfile(self.report_path)

    # ------------------------------------------------------------- run
    @property
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def _checked_items(self):
        return [(iid, r["path"]) for iid in self.tree.get_children()
                for r in [self.rows[iid]] if r["checked"]]

    def _update_controls(self):
        total = len(self.rows)
        ticked = sum(r["checked"] for r in self.rows.values())
        self.count_label.configure(
            text=f"{total} recording{'s' if total != 1 else ''}  \u00b7  {ticked} ticked" if total else "")
        self.all_var.set(bool(total) and ticked == total)
        if total:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
        busy = self.busy
        has_output = bool(self.output_var.get().strip())
        idle = "disabled" if busy else "normal"
        if ticked == total and total > 1:
            label = f"Convert all ({ticked})"
        elif ticked:
            label = f"Convert {ticked} ticked" if ticked > 1 else "Convert 1 file"
        else:
            label = "Convert"
        self.convert_btn.configure(text=label,
                                   state="normal" if (not busy and ticked and has_output) else "disabled")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        for widget in [self.remove_btn, self.clear_btn, self.browse_btn, self.output_entry,
                       self.all_check,
                       *self.format_radios, *self.drop_actions.winfo_children()]:
            widget.configure(state=idle)
        self.remove_btn.configure(state="normal" if (not busy and ticked) else "disabled")
        self.clear_btn.configure(state="normal" if (not busy and total) else "disabled")
        if not busy and total and not has_output:
            self.output_hint.configure(text="Choose an output folder to start converting.",
                                       fg=theme.DANGER)
        else:
            self.output_hint.configure(text="Choose where the converted files are saved. "
                                       "Originals are never changed.", fg=MUTED)

    def start(self):
        items = self._checked_items()
        if not items or self.busy:
            return
        output = Path(self.output_var.get().strip())
        if not output.is_absolute():
            messagebox.showerror(APP_NAME, "Choose a full output folder path, for example "
                                 "D:\\Converted recordings.", parent=self.root)
            return
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Cannot use the output folder:\n{error}", parent=self.root)
            return
        self._save_settings()
        fmt = self.format_var.get()
        for iid, _ in items:
            self.rows[iid].update(state="queued", message="", output="")
            self.tree.set(iid, "status", "Waiting")
            self.tree.item(iid, tags=())
        self.batch_total, self.batch_done = len(items), 0
        self.file_bar["value"] = self.total_bar["value"] = 0
        self.report_link.pack_forget()
        self.worker = BatchWorker(items, output, fmt, self.events)
        self.worker.start()
        self._set_status(f"Converting {len(items)} recording{'s' if len(items) != 1 else ''} "
                         f"to {fmt.upper()}\u2026")
        self._update_controls()

    def cancel(self):
        if self.busy:
            self.worker.cancel.set()
            self.cancel_btn.configure(state="disabled")
            self._set_status("Stopping\u2026 the current file is being cleaned up.")

    def _poll(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, event):
        kind, *args = event
        if kind == "start":
            iid = args[0]
            self.rows[iid]["state"] = "running"
            self.tree.set(iid, "status", "Starting\u2026")
            self.tree.item(iid, tags=("running",))
            self.tree.see(iid)
            self.file_bar["value"] = 0
            self.file_label.configure(text=f"File {self.batch_done + 1} of {self.batch_total}")
        elif kind == "progress":
            iid, fraction, text = args
            self.tree.set(iid, "status", f"{text}  \u00b7  {fraction:.0%}")
            self.file_bar["value"] = fraction
            self.total_bar["value"] = (self.batch_done + fraction) / max(self.batch_total, 1)
        elif kind == "done":
            iid, result = args
            self.batch_done += 1
            row = self.rows[iid]
            status = result["status"]
            row.update(state=status, output=result["output"],
                       message=" ".join([result["message"]] + result["warnings"]))
            label = {
                "converted": "\u2713 Converted" + ("  \u26a0 see details" if result["warnings"] else ""),
                "skipped": "Skipped \u2013 already exists",
                "cancelled": "Cancelled",
            }.get(status, "\u2717 " + result["message"].splitlines()[0][:120])
            self.tree.set(iid, "status", label)
            self.tree.item(iid, tags=(STATUS_TAGS.get(status, ""),))
            if status == "converted":
                self._set_checked(iid, False)
            self.total_bar["value"] = self.batch_done / max(self.batch_total, 1)
            if iid == self.tree.focus():
                self._show_details()
        elif kind == "finished":
            self._finish(args[0])

    def _finish(self, summary):
        self.worker = None
        c = summary["counts"]
        parts = [f"{c['converted']} converted"]
        if c["skipped"]:
            parts.append(f"{c['skipped']} skipped")
        if c["failed"]:
            parts.append(f"{c['failed']} failed")
        text = ("Stopped. " if summary["cancelled"] else "Finished. ") + ", ".join(parts) + "."
        if c["warnings"]:
            text += f" {c['warnings']} with warnings (select a row for details)."
        self._set_status(text)
        self.file_label.configure(text="Current file")
        self.report_path = summary["report"]
        if self.report_path:
            self.report_link.pack(side="right", padx=(0, 12))
        self._update_controls()
        if self.closing:
            self.root.destroy()
            return
        if not summary["cancelled"]:
            if c["failed"]:
                messagebox.showwarning(APP_NAME, text + "\n\nSelect a failed row to see why.",
                                       parent=self.root)
            else:
                self.root.bell()

    def _set_status(self, text):
        self.status.configure(text=text)

    # ------------------------------------------------------------- lifecycle
    def on_close(self):
        if self.busy:
            if not messagebox.askyesno(APP_NAME, "A conversion is still running.\n\n"
                                       "Stop it and close? Files already converted are kept.",
                                       parent=self.root):
                return
            self.closing = True
            self.cancel()
            return  # _finish destroys the window once the worker has cleaned up
        self._save_settings()
        self.root.destroy()

    def _on_ui_error(self, exc_type, exc, tb):
        log.error("Unhandled UI error", exc_info=(exc_type, exc, tb))
        messagebox.showerror(APP_NAME, f"Something went wrong:\n{exc}\n\n"
                             f"Details were saved to {log_file()}", parent=self.root)


def run():
    root, dnd = create_root()
    App(root, dnd)
    root.mainloop()
