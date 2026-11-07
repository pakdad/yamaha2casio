"""Freeze the window into one runnable file for the machine you are on.

    python3 tools/build_app.py              # build for this machine
    python3 tools/build_app.py --check      # just say what a build would be

The result needs no Python installed: `dist/y2c` on Linux and macOS,
`dist\\y2c.exe` on Windows.

The thing to know before running it is that **PyInstaller cannot
cross-compile.**  It works by bundling the interpreter that runs it together
with your code, so the building machine decides what the result runs on,
in two independent ways:

  - the operating system.  A Windows .exe must be built by a Windows Python.
  - the processor.  An x86-64 .exe must be built by an x86-64 Python; an
    ARM one produces an ARM binary.

There is no flag for either.  On Linux the way round the first is wine, which
runs a real Windows Python; see tools/build_windows_exe.sh.  There is no way
round the second except building on, or emulating, that processor.

So on an ARM machine such as a Raspberry Pi, a plain wine build yields an
ARM64 Windows .exe, which runs on Windows-on-ARM laptops and not on an
ordinary PC.  The script says so rather than letting it be a surprise later.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Machine names that mean the same processor, as the various reporting
# layers spell them.
X86_64 = {"x86_64", "amd64", "x64"}
ARM64 = {"aarch64", "arm64"}


def describe():
    """(what this build targets, whether it is the usual Windows PC)."""
    system = platform.system()
    machine = platform.machine().lower()
    if machine in X86_64:
        cpu = "x86-64"
    elif machine in ARM64:
        cpu = "ARM64"
    else:
        cpu = machine
    runs_on = {"Windows": "Windows", "Linux": "Linux", "Darwin": "macOS"}.get(
        system, system)
    ordinary = system == "Windows" and cpu == "x86-64"
    return f"{runs_on} on {cpu}", ordinary


def missing_tables():
    want = ("ctx-tones.json", "yamaha-voices.json", "yamaha-megavoice.json",
            "ctx-drum-assignments.json", "yamaha-drum-kits.json")
    return [n for n in want
            if not os.path.exists(os.path.join(ROOT, "maps", n))]


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true",
                   help="report what a build here would produce, and stop")
    p.add_argument("--clean", action="store_true", help="discard build/ first")
    a = p.parse_args()

    target, ordinary = describe()
    print(f"building on   : {platform.python_implementation()} "
          f"{platform.python_version()}")
    print(f"would produce : a program for {target}")
    if platform.system() == "Windows" and not ordinary:
        print("                NOTE: that is Windows on ARM. It will not run "
              "on an ordinary\n                x86-64 PC -- see the module "
              "docstring for why.")

    gone = missing_tables()
    if gone:
        print("\nmaps/ is missing the published tables:")
        for n in gone:
            print(f"  {n}")
        print("The program will build and run, but kits and tones will fall "
              "back to the\ntemplate's. docs/README.md has the one command "
              "each.")

    if a.check:
        return 0

    try:
        import PyInstaller                                    # noqa: F401
    except ImportError:
        print("\nPyInstaller is not installed. Install it with:")
        print(f"  {sys.executable} -m pip install pyinstaller")
        return 2

    if a.clean:
        for d in ("build", "dist"):
            shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "y2c.spec"]
    print("\n" + " ".join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode:
        return r.returncode

    name = "y2c.exe" if platform.system() == "Windows" else "y2c"
    out = os.path.join(ROOT, "dist", name)
    if not os.path.exists(out):
        print(f"\nPyInstaller reported success but {out} is not there.")
        return 1
    mb = os.path.getsize(out) / (1024 * 1024)
    print(f"\nwrote dist/{name}  ({mb:.1f} MB), for {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
