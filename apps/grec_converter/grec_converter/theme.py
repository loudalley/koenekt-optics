"""Koenekt house style (matches Koenekt Reporter)."""
import tkinter as tk
from tkinter import ttk

from .paths import resource

INK = "#17251F"
GREEN = "#73C509"
GREEN_HOVER = "#8BDD25"
GREEN_TINT = "#EAF5DE"
MUTED = "#596A60"
SURFACE = "#F3F6F3"
BORDER = "#DCE5DD"
DANGER = "#C0392B"
WHITE = "#FFFFFF"

FONT = "Segoe UI"
BODY = (FONT, 10)
SMALL = (FONT, 9)
BOLD = (FONT, 10, "bold")


def _image(master, name, height, width=240):
    try:
        from PIL import Image, ImageTk
        with Image.open(resource("brand", name)) as original:
            image = original.convert("RGBA")
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image, master=master)
    except Exception:
        return None


def header(parent, title, subtitle=""):
    bar = tk.Frame(parent, bg=INK, padx=24, pady=16)
    bar.pack(fill="x", side="top")
    brand = _image(parent, "header_logo.png", 34)
    if brand is not None:
        label = tk.Label(bar, image=brand, bg=INK)
        label.image = brand
        label.pack(side="right", padx=(20, 0))
    mark = _image(parent, "koenekt-cctv-256.png", 54, 54)
    if mark is not None:
        label = tk.Label(bar, image=mark, bg=INK)
        label.image = mark
        label.pack(side="left", padx=(0, 14))
    left = tk.Frame(bar, bg=INK)
    left.pack(side="left", fill="x", expand=True)
    tk.Label(left, text=title, bg=INK, fg=WHITE, anchor="w",
             font=(FONT, 18, "bold")).pack(anchor="w")
    if subtitle:
        tk.Label(left, text=subtitle, bg=INK, fg="#C8D7CE", anchor="w",
                 font=SMALL).pack(anchor="w", pady=(3, 0))
    tk.Frame(parent, height=3, bg=GREEN).pack(fill="x", side="top")
    return bar


def button(parent, text, command, primary=False, **kw):
    options = dict(relief="flat", bd=0, cursor="hand2", padx=16 if primary else 12, pady=6,
                   font=BOLD if primary else BODY,
                   bg=GREEN if primary else SURFACE, fg=INK,
                   activebackground=GREEN_HOVER if primary else "#E4EDE5",
                   activeforeground=INK, disabledforeground="#9AA59E",
                   highlightthickness=1, highlightbackground=BORDER)
    options.update(kw)
    return tk.Button(parent, text=text, command=command, **options)


def link(parent, text, command, bg=WHITE):
    label = tk.Label(parent, text=text, fg="#4E8A07", bg=bg, cursor="hand2",
                     font=(FONT, 10, "underline"))
    label.bind("<Button-1>", lambda _e: command())
    return label


def checkbox(parent, text, variable, command=None, bg=WHITE):
    return tk.Checkbutton(parent, text=text, variable=variable, command=command,
                          bg=bg, fg=INK, font=BODY, activebackground=bg,
                          selectcolor=GREEN_TINT, highlightthickness=0,
                          cursor="hand2", anchor="w")


def radio(parent, text, variable, value, bg=WHITE):
    return tk.Radiobutton(parent, text=text, variable=variable, value=value,
                          bg=bg, fg=INK, font=BODY, activebackground=bg,
                          selectcolor=GREEN_TINT, highlightthickness=0,
                          cursor="hand2")


def apply(window, scale=1.0):
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("Treeview", rowheight=int(26 * scale), font=SMALL,
                    background=WHITE, fieldbackground=WHITE, foreground=INK,
                    bordercolor=BORDER, borderwidth=1)
    style.map("Treeview", background=[("selected", GREEN_TINT)],
              foreground=[("selected", INK)])
    style.configure("Treeview.Heading", padding=6, font=(FONT, 9, "bold"),
                    background=SURFACE, foreground=MUTED, relief="flat")
    style.map("Treeview.Heading", background=[("active", "#E4EDE5")])
    for name, color in (("Koenekt.Horizontal.TProgressbar", GREEN),
                        ("KoenektFile.Horizontal.TProgressbar", "#A6D96A")):
        style.configure(name, troughcolor=SURFACE, background=color,
                        bordercolor=BORDER, lightcolor=color, darkcolor=color,
                        thickness=int(10 * scale))
    style.configure("Vertical.TScrollbar", background=SURFACE, troughcolor=WHITE,
                    bordercolor=WHITE, arrowcolor=MUTED)
