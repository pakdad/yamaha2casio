"""Stable names for converted rhythms: eight for the file, twelve to show.

A CT-X reads its rhythms off a FAT volume, so a file name has eight
characters and no spaces, while the name the instrument SHOWS comes from a
twelve-byte field inside the file.  Both have to be derived from the style's
own name, and the derivation has to be STABLE -- convert the same style today
and next month, alone or with its folder, and it must land on the same file
name, or a reconversion piles up beside the old copy on the stick instead of
replacing it.

This lives in the package rather than beside the batch script because the
window needs it too, and a frozen build cannot follow a `sys.path` insert
into a `tools/` directory that is not there any more.
"""
import os
import re

STYLE_TYPES = (".sty", ".prs", ".bcs", ".pcs", ".sst")
_SUFFIX = re.compile(r"\.(S\d+\.)?(sty|prs|bcs|pcs|sst)$", re.I)


def names(paths):
    """[(path, file stem, display name)] -- unique 8- and 12-character names.

    The meter goes in front of both because a collection can hold an
    Iranian-2-4-Azari 1 and an Iranian-6-8-Azari 1, which are different
    rhythms.  The display field is twelve bytes, which "68 BANDARI 01"
    overruns -- and all seven Bandaris then truncate to the same
    "68 BANDARI 0" -- so a leading zero is dropped to buy the character back.
    """
    out, taken, shown = [], set(), set()
    for p in paths:
        stem = _SUFFIX.sub("", os.path.basename(p))
        stem = re.sub(r"^Iranian[-_ ]*", "", stem, flags=re.I)
        m = re.match(r"(\d)[-_](\d)[-_ ]*(.*)$", stem)
        meter, rest = (m.group(1) + m.group(2), m.group(3)) if m else ("", stem)
        body = re.sub(r"[^A-Za-z0-9]", "", rest).upper()
        pretty = re.sub(r"\b0(\d)\b", r"\1", rest).strip().upper()
        show = f"{meter} {pretty}"[:12].strip()
        if show in shown:
            show = f"{meter}{pretty}"[:12].strip()
        shown.add(show)
        base = meter + body
        short = base[:8]
        if short in taken and body and body[-1].isdigit():
            short = base[:7] + body[-1]
        n = 2
        while short in taken:
            short = base[:7] + str(n)
            n += 1
        taken.add(short)
        out.append((p, short, show))
    return out


def style_files(folder):
    """Every Yamaha style in a folder, sorted, so names() is deterministic."""
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(STYLE_TYPES))


def name_in_context(path):
    """One style's row, computed as if its whole folder were converted.

    The short name is made unique within a batch, so "Bandari 05" converted
    alone becomes 68BANDAR -- the name "Bandari 01" takes when the folder is
    done together, because it gets there first.  Converting one style would
    then quietly overwrite a different rhythm on the stick.
    """
    folder = os.path.dirname(os.path.abspath(path)) or "."
    try:
        siblings = style_files(folder)
    except OSError:
        siblings = []
    want = os.path.abspath(path)
    if want not in (os.path.abspath(s) for s in siblings):
        siblings = [path]
    for row in names(siblings):
        if os.path.abspath(row[0]) == want:
            return row
    return names([path])[0]
