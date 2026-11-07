"""Which notes does each CT-X drum kit actually have, by observation?

Casio *does* publish a drum assignment list -- it is in the appendix that
ships with the keyboard, and `tools/drumlist.py` reads it into
`maps/ctx-drum-assignments.json`.  Prefer that: it is authoritative, it names
every sound, and it covers keys no factory rhythm happens to strike.  This
file was written while believing no such list existed.

What this still answers is a different question: which keys the factory
rhythms *use*, which is how to tell an idiomatic choice from a merely legal
one.  Point it at a directory tree of factory `.AC7` rhythms and it reads
every one, pairs each drum track with the kit its MIXR row assigns, and
collects the notes struck.

    python3 tools/kit_table.py '/path/to/CT-X3000 Rhythm Archive'
    python3 tools/kit_table.py ARCHIVE --covers converted/oriental perc

A note many rhythms strike in a kit is certainly there.  A note that never
appears may be absent or merely unused, so read the table as a lower bound --
it tells you what is safe, not what is missing.

With `--covers DIR ROLE` it instead scores every kit by how much of what the
rhythms in DIR play on ROLE that kit is known to cover, which is how you pick
the kit for a conversion: the drum and percussion parts hold different kits,
and the note numbers alone do not decide the sound.
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from y2c import ac7


def ac7_files(root):
    if os.path.isfile(root):
        return [root]
    return sorted(os.path.join(dp, f) for dp, _, fs in os.walk(root)
                  for f in fs if f.lower().endswith(".ac7"))


def kit_vocabulary(files):
    """(program, bank) -> Counter of notes struck, and the rhythms using it."""
    kit = collections.defaultdict(collections.Counter)
    users = collections.defaultdict(set)
    for path in files:
        try:
            obj = ac7.parse(open(path, "rb").read())
        except Exception as exc:                     # a rhythm we cannot read
            print(f"  skipped {os.path.basename(path)}: {exc}", file=sys.stderr)
            continue
        for ei, el in enumerate(obj.elements):
            if ei in ac7.UNUSED_ELEMENTS:            # never played
                continue
            for tr in el.tracks:
                if tr.part not in ac7.DRUM_PARTS:
                    continue
                row = ac7.mixer_row(obj, ei, tr.part)
                if not row or row[1] != ac7.DRUM_BANK:
                    continue
                for f in tr.frames:
                    if f.is_note and f.val:
                        kit[row[0]][f.code] += 1
                        users[row[0]].add(os.path.basename(path))
    return kit, users


def played(dir_or_file, role):
    """Counter of notes a set of rhythms plays on one part role."""
    want = collections.Counter()
    for path in ac7_files(dir_or_file):
        obj = ac7.parse(open(path, "rb").read())
        for el in obj.elements:
            for tr in el.tracks:
                if tr.role == role:
                    for f in tr.frames:
                        if f.is_note and f.val:
                            want[f.code] += 1
    return want


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("archive", help="directory tree of factory .AC7 rhythms")
    p.add_argument("--covers", nargs=2, metavar=("DIR", "ROLE"),
                   help="score each kit against what DIR plays on ROLE")
    p.add_argument("--min-notes", type=int, default=1,
                   help="ignore kits seen with fewer notes than this")
    a = p.parse_args(argv)

    files = ac7_files(a.archive)
    kit, users = kit_vocabulary(files)
    kit = {k: v for k, v in kit.items() if sum(v.values()) >= a.min_notes}
    print(f"{len(files)} rhythms, {len(kit)} drum kit programs "
          f"(all in bank {ac7.DRUM_BANK})\n")

    if not a.covers:
        print(f"{'kit':>4} {'rhythms':>8} {'keys':>5}  notes struck")
        for prog in sorted(kit):
            keys = sorted(kit[prog])
            print(f"{prog:>4} {len(users[prog]):>8} {len(keys):>5}  "
                  + " ".join(str(k) for k in keys))
        return 0

    dir_, role = a.covers
    want = played(dir_, role)
    total = sum(want.values())
    if not total:
        print(f"nothing plays on a {role!r} part in {dir_}")
        return 1
    print(f"{role} part in {dir_}: {total} notes, {len(want)} distinct\n")
    rows = []
    for prog, have in kit.items():
        covered = sum(c for k, c in want.items() if k in have)
        rows.append((100 * covered / total, prog, len(have),
                     sorted(k for k in want if k not in have)))
    rows.sort(reverse=True)
    print(f"{'kit':>4} {'keys':>5} {'covers':>8}   notes it is never struck with")
    for pct, prog, n, missing in rows[:12]:
        print(f"{prog:>4} {n:>5} {pct:>7.1f}%   "
              + (" ".join(str(m) for m in missing[:14]) or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
