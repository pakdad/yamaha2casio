"""Parse the official CT-X Drum Assignment List out of Casio's appendix.

Until this existed, every drum sound in this project was identified by ear or
by spectrum: record a key sweep off the instrument, measure each hit's
fundamental, decay and band energies, and guess a name.  That worked -- it
got the doum, tak and riq right -- but it also mislabelled sounds, and it
could not see a key no probe had struck.

Casio does publish the list, in the appendix that ships with the keyboard
("Tone List / Drum Assignment List", 14M3APPEND).  It names every note of
every kit.  This reads it, so sound choice stops being guesswork.

Known limitation: a cell belongs to the column containing its start, and the
grid is not perfectly ruled -- in some rows a cell begins a few characters
left of its own column and is dropped, so a kit can come back with fewer
notes than it really has.  What comes back is correct; it is not always
complete.  Assigning each cell to its *nearest* column instead recovers those
rows but drags the neighbouring kit's overflow in with it, which is worse --
it reported "Tun Riq 2" and "Ke Davul 1" as sounds of the Arabic kit.  When a
particular kit matters, check its column straight out of the `pdftotext
-layout` output; `pdftotext -bbox-layout`, which carries real coordinates,
would fix this properly.

    pdftotext -layout docs/CTX-appendix-tone-rhythm-lists.pdf out.txt
    python3 tools/drumlist.py out.txt --kit 'ARABIC SET'
    python3 tools/drumlist.py out.txt --json maps/ctx-drum-assignments.json

The table is one wide grid per block: a header row naming each kit as
"<tone number> <KIT NAME>", then one row per MIDI note.  pdftotext -layout
holds the columns at fixed character offsets, so the header's own offsets give
the cell boundaries.  A cell of "»" means "same sound as the kit to the
left", so a row resolves left to right; a genuinely empty cell means the kit
has no sound on that key, which is not the same thing.
"""
import argparse
import collections
import json
import re

KIT = re.compile(r"(\d{3})(?:/(\d{3}))? ([A-Z0-9][A-Z0-9 .&'\-]*?)"
                 r"(?=\s+\d{3} |\s*$)")
# Header cells sit a few characters right of the data beneath them, and the
# first kit's data starts left of its header text; both are absorbed here.
# LEAD is deliberately tight: a wider window reaches past the left edge of
# the column and collects the tail of the neighbouring kit, which is how
# "Standard3 Ride Bell" first came out as "ell  Standard3 Ride Bell".
LEAD, FIRST = 3, 38
DITTO = "»"


def kit_columns(line):
    """[(column, tone number, kit name)] for a header row, left to right.

    The same appendix carries a tone list and a rhythm list laid out the same
    way, and "100 RHUMBA" parses as happily as "792 ARABIC SET".  A drum kit
    header is told apart by its names: every kit in the list is a SET or a
    KIT, so require most of the row to say so.
    """
    out = [(m.start(), int(m.group(2) or m.group(1)), m.group(3).strip())
           for m in KIT.finditer(line)]
    sets = sum(1 for _, _, n in out if re.search(r"\b(SET|KIT)\b", n))
    return out if len(out) >= 3 and sets >= 3 else []


def note_number(line):
    """The MIDI note a row is for, from its left-hand label columns."""
    digits = re.findall(r"\d{1,3}", line[:FIRST])
    if not digits:
        return None
    n = int(digits[-1])
    return n if n <= 127 else None


def parse(text):
    """{(tone, kit name): {note: sound name}} for every kit in the list.

    Each page is parsed on its own, split on the form feeds pdftotext writes
    at page breaks.  Parsing the whole document as one grid does not work:
    a block then runs past the end of its page and swallows rows of whatever
    table comes next, read at the wrong column offsets, which quietly filled
    the Arabic kit with fragments of the DSP list.
    """
    kits = {}
    for page in text.split("\f"):
        _parse_page(page, kits)
    return kits


def _data_columns(rows, ncols):
    """Where the data cells actually start, found from the rows themselves.

    Deriving the cell boundaries from the header does not work: the header
    text sits a few characters right of its column and the offset is not the
    same for every kit, so a fixed nudge either clips the left of some cells
    or swallows the tail of the kit next door.  The rows agree with each
    other far better than they agree with the header, so cluster the start
    columns of every cell on the page and keep the `ncols` busiest clusters.
    """
    starts = collections.Counter(c for r in rows for c, _ in r)
    clusters = []
    for col in sorted(starts):
        if clusters and col - clusters[-1][-1] <= 3:
            clusters[-1].append(col)
        else:
            clusters.append([col])
    return sorted(min(g) for g in clusters)


def _parse_page(text, kits):
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if kit_columns(l)]
    for n, i in enumerate(heads):
        cols = kit_columns(lines[i])
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = []
        for line in lines[i + 1:end]:
            note = note_number(line)
            if note is None:
                continue
            # Cells are whitespace-separated runs; a single space inside one
            # is kept, because several kit names carry one ("Riq Tek 1").
            body.append((note, [(m.start() + FIRST, m.group().strip())
                                for m in re.finditer(r"\S+(?: \S+)*",
                                                    line[FIRST:])]))
        if not body:
            continue
        # Pair each kit with the cell column nearest to its header, rather
        # than pairing the Nth cluster with the Nth kit: the page also holds
        # cell columns the header says nothing about, so counting them off in
        # order slides every kit one place left and silently reports the
        # neighbouring kit's sounds under this kit's name.
        found = _data_columns([g for _, g in body], len(cols))
        if not found:
            continue
        # Kits and cell columns both run left to right, so walk them
        # together and never reuse a column.  Taking the nearest column
        # independently per kit let two kits claim one column, and rejecting
        # the block on that dropped the whole first header row of the page.
        starts, last = [], -1
        for col, _, _ in cols:
            free = [c for c in found if c > last]
            if not free:
                break
            pick = min(free, key=lambda c, want=col - LEAD: abs(c - want))
            starts.append(pick)
            last = pick
        if len(starts) < len(cols):
            continue
        edges = starts + [10 ** 6]
        for note, groups in body:
            left = None
            for k, (_, tone, name) in enumerate(cols):
                cell = " ".join(t for c, t in groups
                                if edges[k] <= c < edges[k + 1]).strip()
                if cell.startswith(DITTO):
                    cell = left
                if cell:
                    kits.setdefault((tone, name), {})[note] = cell
                    left = cell
    return kits


# The tone list in the same appendix gives each kit its program and bank,
# which is what a conversion actually needs: "ARABIC SET" is useless to
# --tone, "52/120" is not.  Rows read "792 ARABIC SET  52  120  4".
# The name is built from single-space-separated words on purpose.  Allowing
# spaces freely inside it let the name run across the whole line -- these
# rows are all upper case, so "070 CHURCH BELLS ... 792 ARABIC SET" matched
# as one row and filed the Arabic kit's program under tone 070.
PROGRAM = re.compile(r"\b(\d{3}) ((?:[A-Z0-9.&'\-]+ )*?(?:SET|KIT)"
                     r"(?: \d)?) {2,}(\d{1,3}) +(120)\b")


def kit_programs(text):
    """{tone number: (program, bank)} for every drum kit in the tone list."""
    return {int(m.group(1)): (int(m.group(3)), int(m.group(4)))
            for m in PROGRAM.finditer(text)}


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text", help="appendix text from `pdftotext -layout`")
    p.add_argument("--kit", help="print one kit's notes, by name")
    p.add_argument("--json", help="write every kit here")
    a = p.parse_args()

    text = open(a.text, encoding="utf-8").read()
    kits = parse(text)
    if a.kit:
        hit = [(t, n) for (t, n) in kits if n.upper() == a.kit.upper()]
        if not hit:
            raise SystemExit(f"no kit called {a.kit!r}; have: "
                             + ", ".join(sorted(n for _, n in kits)))
        tone, name = hit[0]
        notes = kits[(tone, name)]
        print(f"{name} (tone {tone}), {len(notes)} notes")
        for k in sorted(notes):
            print(f"  {k:3d}  {notes[k]}")
    if a.json:
        progs = kit_programs(text)
        out = {}
        for (t, n), ns in sorted(kits.items()):
            prog, bank = progs.get(t, (None, None))
            out[str(t)] = {"name": n, "program": prog, "bank": bank,
                           "notes": {str(k): v for k, v in sorted(ns.items())}}
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"wrote {a.json}: {len(out)} kits")
    if not a.kit and not a.json:
        for (t, n), ns in sorted(kits.items()):
            print(f"  {t} {n}: {len(ns)} notes")


if __name__ == "__main__":
    main()
