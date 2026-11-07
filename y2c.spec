# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the window: one file, no Python needed to run it.

    pyinstaller y2c.spec          (see tools/build_app.py for the wrapper)

PyInstaller cannot cross-compile.  It freezes the interpreter it is RUN by,
so the machine that builds decides what the result runs on: a Windows .exe
has to be built by a Windows Python, and an x86-64 .exe by an x86-64 one.
That is the whole reason the Windows build here goes through wine.

This whole repository is pure standard library -- no numpy, no scipy -- so the
only native dependency is Tk, which ships with Python.  The audio-analysis
scripts that used to need scipy now live in the audio2style repository, for
exactly this reason among others: they are for transcribing audio, not for
converting styles, and pulling scipy in would multiply the size of a bundle
the window never calls it from.  The excludes below stay as a guard, so that
a stray import can never quietly add 60 MB to the build.

The published tables in maps/ are bundled when they are present.  They are
not committed -- they are extracted from Casio's and Yamaha's own manuals --
so a build made without them produces a working program that falls back to
the template's kits and tones, which is a quieter failure than it sounds.
tools/build_app.py warns before that happens.
"""
import os

datas = []
for folder in ("maps", "samples"):
    if os.path.isdir(folder):
        datas.append((folder, folder))

a = Analysis(
    ["y2c_gui.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    # `from y2c import cli` sits inside a function so that a missing table
    # reports in the window rather than at import; naming is imported for
    # both front ends.  Named here so neither depends on how deep
    # PyInstaller's analysis goes.
    hiddenimports=["y2c.cli", "y2c.naming", "y2c.ac7", "y2c.convert",
                   "y2c.drummap", "y2c.ir", "y2c.mega", "y2c.smf",
                   "y2c.tonemap", "y2c.yamaha", "y2c.capture"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "scipy", "matplotlib", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="y2c",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # No console window on Windows: this is a window, and a terminal opening
    # behind it looks like something went wrong.  The log pane already shows
    # everything the command line prints.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
