#!/usr/bin/env python3
"""A window for the converter, for when you just want the rhythms.

    python3 y2c_gui.py

Everything here is already in `y2c.py convert`; this only saves typing it.
Pick a style file or a whole folder, press Convert, then Copy to keyboard.

Two things shape the code more than they look like they should.

It calls `y2c.main()` IN-PROCESS rather than spawning `y2c.py`.  A frozen
build has no `python3` to spawn and no `y2c.py` on disk to point it at, so a
subprocess would work from a checkout and fail as an .exe -- which is exactly
the kind of difference that only shows up after shipping.  Running in-process
also means the log you see is the log the converter prints, with no second
code path to keep in step.

Only tkinter is used, and tkinter ships with Python.  A GUI toolkit that
needs installing would make the window the hardest part of the project to
get running, which is the wrong way round.
"""
from __future__ import annotations

import io
import os
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, getattr(sys, "_MEIPASS", None)
                or os.path.dirname(os.path.abspath(__file__)))
from y2c.naming import STYLE_TYPES, name_in_context, names, style_files  # noqa

# Casio drum kits worth offering, by program number, from the Tone List.
# Percussion first, then the kit for the drum part.  Arabic over Standard is
# the default because it is the pairing the Iranian styles were measured
# against: it took their wrong-family notes from 46% to under 5%.
KIT_CHOICES = [
    ("Arabic percussion + Standard drums  (Persian, Arabic)", "by-sound:52/0"),
    ("Latin percussion + Standard drums  (pop, rock, dance)", "by-sound:49/0"),
    ("Latin percussion + Room drums", "by-sound:49/8"),
    ("Latin percussion + Rock drums", "by-sound:49/17"),
    ("Indian percussion + Standard drums", "by-sound:54/0"),
    ("Arabic percussion + Dance drums", "by-sound:52/26"),
]


def here(*parts):
    """A path inside the program, whether run from source or frozen."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _import_cli():
    """The converter's command layer, as a normal import.

    `y2c/cli.py` rather than the top-level `y2c.py`: a script cannot be
    imported when a package shares its name, and a frozen build has no script
    on disk to load by path.
    """
    base = here()
    if base not in sys.path:
        sys.path.insert(0, base)
    from y2c import cli                                      # noqa: E402
    return cli


def removable_targets():
    """Folders that look like a keyboard's media: a MUSICDAT on a volume.

    The CT-X reads rhythms from \\MUSICDAT on a FAT volume.  Looking for that
    folder rather than for a drive letter or a mount point keeps the same
    code right on Linux, where the stick lands under /media/<user>/<label>,
    and on Windows, where it gets a letter.
    """
    roots = []
    if os.name == "nt":
        import string
        roots = [f"{d}:\\" for d in string.ascii_uppercase
                 if os.path.exists(f"{d}:\\")]
    else:
        for parent in ("/media", "/run/media", "/mnt", "/Volumes"):
            if not os.path.isdir(parent):
                continue
            for a in sorted(os.listdir(parent)):
                p = os.path.join(parent, a)
                roots.append(p)
                if os.path.isdir(p):
                    roots += [os.path.join(p, b) for b in sorted(os.listdir(p))]
    out = []
    for r in roots:
        d = os.path.join(r, "MUSICDAT")
        if os.path.isdir(d):
            out.append(d)
    return out


class Tee(io.TextIOBase):
    """Send the converter's printing to the log pane, a line at a time."""

    def __init__(self, sink):
        self.sink = sink
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, _, self.buf = self.buf.partition("\n")
            self.sink(line)
        return len(s)

    def flush(self):
        if self.buf:
            self.sink(self.buf)
            self.buf = ""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Yamaha style → Casio CT-X rhythm")
        self.minsize(820, 560)
        self.q = queue.Queue()
        self.busy = False
        self.written = []

        self.styles = tk.StringVar()
        self.outdir = tk.StringVar(value=os.path.join(here(), "converted"))
        self.template = tk.StringVar(value=self._default_template())
        self.kit = tk.StringVar(value=KIT_CHOICES[0][0])
        self.name = tk.StringVar()
        self.do_tones = tk.BooleanVar(value=True)
        self.do_mega = tk.BooleanVar(value=True)
        self.do_clamp = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Pick a style file, or a folder of them.")

        self._build()
        self.after(80, self._drain)
        self._check_tables()

    # -- layout ---------------------------------------------------------
    def _build(self):
        pad = {"padx": 6, "pady": 4}
        form = ttk.LabelFrame(self, text=" What to convert ")
        form.pack(fill="x", padx=8, pady=(8, 4))
        form.columnconfigure(1, weight=1)

        def row(r, label, var, *buttons):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(form, textvariable=var).grid(row=r, column=1,
                                                   sticky="ew", **pad)
            box = ttk.Frame(form)
            box.grid(row=r, column=2, sticky="e", **pad)
            for text, fn in buttons:
                ttk.Button(box, text=text, command=fn, width=8).pack(side="left")

        row(0, "Styles", self.styles,
            ("File…", self._pick_style), ("Folder…", self._pick_folder))
        row(1, "Save to", self.outdir, ("Browse…", self._pick_out))
        row(2, "Template", self.template, ("Browse…", self._pick_template))

        ttk.Label(form, text="Kits").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(form, textvariable=self.kit, state="readonly",
                     values=[c[0] for c in KIT_CHOICES]).grid(
            row=3, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(form, text="Name on keyboard").grid(row=4, column=0,
                                                      sticky="w", **pad)
        ttk.Entry(form, textvariable=self.name, width=16).grid(row=4, column=1,
                                                               sticky="w", **pad)
        ttk.Label(form, text="12 characters; a folder names each rhythm after "
                             "its file", foreground="#666").grid(
            row=4, column=2, sticky="w", **pad)

        opts = ttk.LabelFrame(self, text=" Fixes applied on the way ")
        opts.pack(fill="x", padx=8, pady=4)
        for text, var, tip in (
                ("Map tones from the style", self.do_tones,
                 "otherwise every part plays the template's tone"),
                ("Flatten MegaVoice parts", self.do_mega,
                 "drops Yamaha's noise keys and un-inverts the dynamics"),
                ("Clamp element lengths", self.do_clamp,
                 "a fill-in may be 1 or 2 bars"),
        ):
            c = ttk.Checkbutton(opts, text=text, variable=var)
            c.pack(side="left", padx=8, pady=6)
            _tip(c, tip)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.go = ttk.Button(bar, text="Convert", command=self._convert)
        self.go.pack(side="left")
        self.copy = ttk.Button(bar, text="Copy to keyboard…",
                               command=self._copy, state="disabled")
        self.copy.pack(side="left", padx=6)
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=10)

        frame = ttk.LabelFrame(self, text=" What the converter did ")
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.log = tk.Text(frame, wrap="none", height=18, borderwidth=0,
                           font=("TkFixedFont", 9))
        sb = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        for tag, colour in (("bad", "#b00020"), ("good", "#006400"),
                            ("head", "#00457c")):
            self.log.tag_configure(tag, foreground=colour)

    def _default_template(self):
        """The most complete donor to hand, which is not an arbitrary choice.

        original_waltz.AC7 is the only factory rhythm here with all seven
        parts in all ten used elements, so no part has to be dropped for want
        of a track.  Its 3/4 does not matter: convert writes the meter.
        """
        for name in ("original_waltz.AC7", "original_6_8.AC7",
                     "original_sample.AC7"):
            p = here("samples", name)
            if os.path.exists(p):
                return p
        return ""

    def _check_tables(self):
        missing = [n for n in ("ctx-tones.json", "yamaha-voices.json",
                               "yamaha-megavoice.json", "ctx-drum-assignments.json",
                               "yamaha-drum-kits.json")
                   if not os.path.exists(here("maps", n))]
        if not missing:
            return
        self._say("The published tables these need are not in maps/ yet:",
                  "bad")
        for n in missing:
            self._say(f"    maps/{n}", "bad")
        self._say("docs/README.md has the one command each. Without them the "
                  "kits and tones fall back to the template's.", "bad")

    # -- pickers --------------------------------------------------------
    def _pick_style(self):
        p = filedialog.askopenfilename(
            title="Yamaha style",
            filetypes=[("Yamaha styles", " ".join("*" + e for e in STYLE_TYPES)),
                       ("All files", "*.*")])
        if p:
            self.styles.set(p)
            if not self.name.get():
                self.name.set(os.path.splitext(os.path.basename(p))[0][:12].upper())

    def _pick_folder(self):
        p = filedialog.askdirectory(title="Folder of Yamaha styles")
        if p:
            self.styles.set(p)

    def _pick_out(self):
        p = filedialog.askdirectory(title="Where to write the .AC7 files")
        if p:
            self.outdir.set(p)

    def _pick_template(self):
        p = filedialog.askopenfilename(title="A rhythm exported from the CT-X",
                                       filetypes=[("Casio rhythm", "*.AC7"),
                                                  ("All files", "*.*")])
        if p:
            self.template.set(p)

    # -- the work -------------------------------------------------------
    def _say(self, line, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    tag = None
                    low = payload.lower()
                    if "fail" in low or "error" in low or "cannot" in low:
                        tag = "bad"
                    elif payload.startswith(("megavoice", "part folding",
                                             "kits", "tone", "element length")):
                        tag = "head"
                    self._say(payload, tag)
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "done":
                    self.busy = False
                    self.go.configure(state="normal")
                    self.copy.configure(
                        state="normal" if self.written else "disabled")
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _settings(self):
        """Every widget value, read once, on the thread tkinter allows.

        A tkinter variable may only be touched from the thread running the
        event loop; reading one from the worker raises "main thread is not in
        main loop".  So the job is frozen into plain data here and the worker
        sees nothing but that.
        """
        return {
            "src": self.styles.get().strip(),
            "out": self.outdir.get().strip(),
            "template": self.template.get().strip(),
            "kit": dict(KIT_CHOICES)[self.kit.get()],
            "name": self.name.get().strip(),
            "tones": self.do_tones.get(),
            "mega": self.do_mega.get(),
            "clamp": self.do_clamp.get(),
        }

    @staticmethod
    def _args_for(job, path, out, name):
        argv = ["convert", path, "-o", out, "--map", job["kit"],
                "--template", job["template"], "--name", name]
        if not job["tones"]:
            argv.append("--no-tones")
        if not job["mega"]:
            argv.append("--no-mega")
        if not job["clamp"]:
            argv.append("--no-clamp")
        return argv

    def _convert(self):
        if self.busy:
            return
        src = self.styles.get().strip()
        out = self.outdir.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showerror("No styles", "Pick a style file or a folder.")
            return
        if not self.template.get() or not os.path.exists(self.template.get()):
            messagebox.showerror("No template",
                                 "Pick a rhythm exported from your CT-X to use "
                                 "as the container.")
            return
        if not out:
            messagebox.showerror("Nowhere to write", "Pick an output folder.")
            return
        os.makedirs(out, exist_ok=True)
        job = self._settings()
        self.busy = True
        self.written = []
        self.go.configure(state="disabled")
        self.copy.configure(state="disabled")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._worker, args=(job,), daemon=True).start()

    def _worker(self, job):
        src, out = job["src"], job["out"]
        push = lambda line: self.q.put(("line", line))       # noqa: E731
        try:
            cli = _import_cli()
            jobs = self._plan(job)
            self.q.put(("status", f"converting {len(jobs)} …"))
            ok = 0
            for i, (path, short, show) in enumerate(jobs, 1):
                dest = os.path.join(out, short + ".AC7")
                push("")
                push(f"=== [{i}/{len(jobs)}] {os.path.basename(path)} "
                     f"→ {short}.AC7  ({show})")
                tee = Tee(push)
                try:
                    import contextlib
                    with contextlib.redirect_stdout(tee):
                        rc = cli.main(self._args_for(job, path, dest, show))
                    tee.flush()
                except Exception:
                    tee.flush()
                    for ln in traceback.format_exc().strip().split("\n"):
                        push("    " + ln)
                    rc = 1
                if rc == 0 and os.path.exists(dest):
                    ok += 1
                    self.written.append(dest)
                else:
                    push(f"    FAILED: {short}")
                self.q.put(("status", f"{ok} of {len(jobs)} done"))
            push("")
            self.q.put(("line", f"--- {ok} of {len(jobs)} converted into {out}"))
            self.q.put(("status", f"{ok} of {len(jobs)} converted"
                                  + ("  — now Copy to keyboard" if ok else "")))
        except Exception:
            for ln in traceback.format_exc().strip().split("\n"):
                self.q.put(("line", ln))
            self.q.put(("status", "failed — see the log"))
        finally:
            self.q.put(("done", None))

    @staticmethod
    def _plan(job):
        """[(path, file stem, display name)] for one file or a whole folder."""
        src = job["src"]
        if os.path.isdir(src):
            paths = style_files(src)
            if not paths:
                raise SystemExit(f"no Yamaha styles in {src}")
            return names(paths)
        path, short, show = name_in_context(src)
        return [(path, short, job["name"][:12].upper() if job["name"] else show)]

    # -- copying --------------------------------------------------------
    def _copy(self):
        import hashlib
        import shutil
        targets = removable_targets()
        dest = targets[0] if targets else filedialog.askdirectory(
            title="The MUSICDAT folder on the keyboard's USB stick")
        if not dest:
            return
        if not messagebox.askokcancel(
                "Copy to keyboard",
                f"Copy {len(self.written)} rhythm(s) to\n{dest}\n\n"
                "Files of the same name there will be replaced."):
            return
        digest = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()  # noqa
        good, bad = 0, []
        self._say("")
        self._say(f"=== copying {len(self.written)} to {dest}", "head")
        for p in self.written:
            try:
                shutil.copy2(p, dest)
                target = os.path.join(dest, os.path.basename(p))
                if digest(p) == digest(target):
                    good += 1
                else:
                    bad.append(os.path.basename(p))
            except Exception as exc:
                bad.append(f"{os.path.basename(p)}: {exc}")
        try:
            os.sync()
        except AttributeError:
            pass
        for b in bad:
            self._say("    MISMATCH " + b, "bad")
        self._say(f"{good} copied and verified byte for byte"
                  + (f", {len(bad)} failed" if bad else ""),
                  "bad" if bad else "good")
        self._say("Eject the stick before unplugging it.", "good")
        self.status.set(f"{good} copied to {dest}")


def _tip(widget, text):
    """A one-line hover label.  Plain tkinter has no tooltip of its own."""
    win = {"w": None}

    def show(_):
        if win["w"] or not text:
            return
        x = widget.winfo_rootx() + 12
        y = widget.winfo_rooty() + widget.winfo_height() + 2
        w = tk.Toplevel(widget)
        w.wm_overrideredirect(True)
        w.wm_geometry(f"+{x}+{y}")
        tk.Label(w, text=text, background="#ffffe0", relief="solid",
                 borderwidth=1, padx=4).pack()
        win["w"] = w

    def hide(_):
        if win["w"]:
            win["w"].destroy()
            win["w"] = None

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)


def selftest():
    """Prove a frozen build can still find everything it needs.

    A bundled program fails differently from a script: the code is fine and
    the DATA is missing, because PyInstaller unpacks it to a temporary
    directory and anything that looked itself up relative to the source tree
    now looks in the wrong place.  That shows up as kits and tones silently
    falling back to the template -- a rhythm that plays, and plays wrong.

    Run it from a terminal when the window misbehaves: `y2c --selftest`.
    """
    ok = True
    print(f"running from : {here()}")
    print(f"frozen       : {bool(getattr(sys, '_MEIPASS', None))}")
    for folder, wanted in (
            ("maps", ("ctx-tones.json", "yamaha-voices.json",
                      "yamaha-megavoice.json", "ctx-drum-assignments.json",
                      "yamaha-drum-kits.json")),
            ("samples", ("original_waltz.AC7",))):
        for name in wanted:
            path = here(folder, name)
            good = os.path.exists(path)
            ok &= good
            print(f"  {'found  ' if good else 'MISSING'}  {folder}/{name}")
    try:
        cli = _import_cli()
        print(f"  found    y2c.cli.main  ({cli.main})")
        from y2c import tonemap
        tm = tonemap.load()
        if tm is None:
            print("  MISSING  the tone tables did not load")
            ok = False
        else:
            got = tm.choose(0, 113, 107)          # Kanoun, a cross-family case
            print(f"  loaded   {len(tm.tones)} CT-X tones; "
                  f"Kanoun -> {got[2]}")
            ok &= got[2].startswith("KANUN")
    except Exception as exc:
        print(f"  FAILED   {exc!r}")
        ok = False
    print("self-test passed" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    App().mainloop()
