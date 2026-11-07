"""Convert a folder of Yamaha styles to CT-X5000 rhythms in one pass.

    python3 tools/convert_all.py STYLEDIR -o OUTDIR \
        --template MY_RHYTHM.AC7 --map by-sound:52/0

Forty-six styles is too many to convert by hand and keep straight, and the
names are the fiddly part; `y2c.naming` works those out, and the window uses
the same function so the two front ends cannot name a file differently.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from y2c.naming import names, style_files                     # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("styledir")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--map", default="by-sound:52/0")
    p.add_argument("--extra", default="", help="more flags for y2c.py convert")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    styles = style_files(a.styledir)
    if not styles:
        raise SystemExit(f"no styles in {a.styledir}")
    os.makedirs(a.out, exist_ok=True)
    rows, bad = [], []
    for path, short, show in names(styles):
        dest = os.path.join(a.out, short + ".AC7")
        if a.dry_run:
            print(f"  {os.path.basename(path):<34} -> {short + '.AC7':<13} "
                  f"shows {show!r}")
            continue
        cmd = [sys.executable, os.path.join(here, "y2c.py"), "convert", path,
               "--template", a.template, "-o", dest, "--name", show,
               "--map", a.map] + a.extra.split()
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode or not os.path.exists(dest):
            bad.append((short, (r.stderr or r.stdout).strip().split("\n")[-1]))
            continue
        log = r.stdout
        def grab(pat, cast=int, default=0):
            m = re.search(pat, log)
            return cast(m.group(1)) if m else default
        rows.append({
            "file": short, "show": show,
            "notes": grab(r"notes written\s*:\s*(\d+)"),
            "noise": grab(r"(\d+) noise-zone notes"),
            "arts": grab(r"and (\d+) unplayable articulations"),
            "folded": grab(r"(\d+) notes kept that had no track"),
            "clamped": len(re.findall(r"element length:", log)),
            "tones": len(re.findall(r"^tone      :", log, re.M)),
        })
    if a.dry_run:
        return 0
    print(f"{'file':<10} {'shows':<13} {'notes':>6} {'tones':>6} "
          f"{'noise':>6} {'artic':>6} {'folded':>7} {'clamp':>6}")
    for r in rows:
        print(f"{r['file']:<10} {r['show']:<13} {r['notes']:>6} "
              f"{r['tones']:>6} {r['noise']:>6} {r['arts']:>6} "
              f"{r['folded']:>7} {r['clamped']:>6}")
    tot = lambda k: sum(r[k] for r in rows)                      # noqa: E731
    print(f"\n{len(rows)} converted, {len(bad)} failed")
    print(f"  notes written          {tot('notes'):>8}")
    print(f"  noise-zone notes cut   {tot('noise'):>8}")
    print(f"  articulations cut      {tot('arts'):>8}")
    print(f"  notes saved by folding {tot('folded'):>8}")
    print(f"  elements clamped       {tot('clamped'):>8}")
    for short, err in bad:
        print(f"  FAILED {short}: {err}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
