#!/bin/sh
# Build a Windows y2c.exe from Linux, by running a real Windows Python
# under wine.
#
#   tools/build_windows_exe.sh            # pick the Python wine can run
#   tools/build_windows_exe.sh 3.12.8     # pin the Python version
#
# PyInstaller cannot cross-compile: it bundles the interpreter that runs it,
# so a Windows .exe has to be produced by a Windows Python.  wine supplies
# one.  What wine CANNOT supply is a different processor, and that is the
# catch on an ARM machine:
#
#   * On an x86-64 Linux box this produces the ordinary x86-64 y2c.exe that
#     runs on any Windows PC.
#
#   * On ARM (a Raspberry Pi, an Apple-silicon VM) Debian's wine ships only
#     the ARM Windows libraries -- its x86_64-windows directory is empty and
#     there is no wowbox64.dll to bridge to box64 -- so it can run ARM64
#     Windows binaries and nothing else.  The .exe this builds there is an
#     ARM64 Windows binary: fine on a Snapdragon/Surface laptop, and it will
#     not start on a normal PC.
#
# The script detects which case it is in and says so before it spends half an
# hour on it.  To get an x86-64 .exe from an ARM machine you need an x86-64
# machine, or full x86 emulation (FEX or box64 with wowbox64), which is a
# much larger undertaking than this script.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PYVER=${1:-3.13.1}
WINEPREFIX=${WINEPREFIX:-$HOME/.y2c-wine}
WORK=${WORK:-$ROOT/build/wine}
export WINEPREFIX WINEDEBUG=${WINEDEBUG:--all}

command -v wine >/dev/null || { echo "wine is not installed"; exit 1; }

# Wine needs 4 KiB memory pages and refuses to start without them, with
# "wineserver: page size is 16k but Wine requires 4k pages" followed by a
# cascade of unrelated-looking errors.  A Raspberry Pi 5 running the rpi-2712
# kernel has 16 KiB pages by default, so this is the first thing to check --
# otherwise half an hour of downloading and installing ends in a confusing
# failure that has nothing to do with Python or PyInstaller.
PAGESIZE=$(getconf PAGE_SIZE 2>/dev/null || echo 4096)
if [ "$PAGESIZE" -ne 4096 ]; then
    cat <<EOF
This kernel uses ${PAGESIZE}-byte memory pages. Wine requires 4096 and will
not start, whatever it is asked to run.

On a Raspberry Pi 5 the fix is to boot the 4 KiB-page kernel: add

    kernel=kernel8.img

to /boot/firmware/config.txt and reboot. That is a boot-level change and it
affects everything on the machine, so it is left to you.

Note that it would still only get you an ARM64 .exe here -- see the comment
at the top of this script.
EOF
    exit 1
fi

# Which Windows architectures does this wine actually carry?  An empty
# x86_64-windows directory means the packages are ARM-only.
WINEARCH=arm64
for d in /usr/lib/*/wine/x86_64-windows /usr/lib/wine/x86_64-windows; do
    [ -d "$d" ] || continue
    if [ -n "$(ls -A "$d" 2>/dev/null)" ]; then WINEARCH=amd64; fi
done

echo "wine        : $(wine --version)"
echo "prefix      : $WINEPREFIX"
echo "target      : Windows $WINEARCH"
if [ "$WINEARCH" = arm64 ]; then
    cat <<'WARN'

  NOTE  This wine can only run ARM64 Windows binaries, so the .exe it builds
        runs on Windows-on-ARM laptops and NOT on an ordinary x86-64 PC.
        For that, build on an x86-64 machine -- the same script, unchanged.

WARN
fi

mkdir -p "$WORK"
cd "$WORK"

INSTALLER="python-$PYVER-$WINEARCH.exe"
[ "$WINEARCH" = amd64 ] && INSTALLER="python-$PYVER-amd64.exe"
if [ ! -f "$INSTALLER" ]; then
    echo "downloading $INSTALLER"
    curl -fL -o "$INSTALLER" \
        "https://www.python.org/ftp/python/$PYVER/$INSTALLER"
fi

PYDIR='C:\y2cpy'
PYEXE="$WINEPREFIX/drive_c/y2cpy/python.exe"
if [ ! -f "$PYEXE" ]; then
    echo "installing Python $PYVER into the wine prefix (several minutes)"
    # Include_tcltk is the one that matters: this is a tkinter program, and
    # the default install leaves tkinter out of nothing -- but a trimmed
    # install would, and the failure only appears when the window is opened.
    wine "$INSTALLER" /quiet TargetDir="$PYDIR" InstallAllUsers=0 \
        Include_tcltk=1 Include_pip=1 Include_test=0 \
        AssociateFiles=0 Shortcuts=0 PrependPath=0 || true
    wineserver -w || true
fi
[ -f "$PYEXE" ] || { echo "Python did not install into $PYEXE"; exit 1; }

echo "python      : $(wine "$PYEXE" --version 2>&1 | tr -d '\r')"
wine "$PYEXE" -c "import tkinter, sys; print('tkinter ok', tkinter.TkVersion)" \
    || { echo "tkinter is missing from the wine Python -- rerun with a clean \
WINEPREFIX"; exit 1; }

wine "$PYEXE" -m pip install --quiet --upgrade pip pyinstaller
wineserver -w || true

cd "$ROOT"
echo "building    : y2c.spec"
wine "$PYEXE" -m PyInstaller --noconfirm --distpath dist-windows \
    --workpath build/windows y2c.spec
wineserver -w || true

OUT="$ROOT/dist-windows/y2c.exe"
if [ -f "$OUT" ]; then
    echo
    echo "wrote dist-windows/y2c.exe ($(du -h "$OUT" | cut -f1)), \
Windows $WINEARCH"
    file "$OUT" || true
else
    echo "PyInstaller finished but $OUT is not there"
    exit 1
fi
