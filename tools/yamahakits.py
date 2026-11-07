"""Read Yamaha's Drum & SFX Kit List into kit tables, from a PSR Data List.

    # spreadsheet Data List (preferred -- real cells, no column guessing)
    python3 tools/yamahakits.py DataList.xlsx --json maps/yamaha-drum-kits.json
    python3 tools/yamahakits.py DataList.xlsx --kit 'Arabic Kit 2'
    # older PDF Data List
    pdftotext -layout psrs650_en_dl_a0.pdf /tmp/ydl.txt
    python3 tools/yamahakits.py /tmp/ydl.txt --json maps/yamaha-drum-kits.json

This is the missing half of the mapping problem.  A style's drum note means
nothing on its own: the meaning comes from the kit the style's part declares,
and the 46 Iranian styles declare twelve different ones.  The converter
assumed one GM-standard layout for all of them, which is why notes landed on
whistles and cuicas -- in GM's standard kit those keys ARE whistles and
cuicas, but the percussion parts here declare Arabic Kit 2 and Arabic Mixture
Kit, where the same keys are tablah and katem strokes.

Prefer the .xlsx.  The spreadsheet has addressable cells: row 4 names each
kit, row 5 gives its MSB-LSB-PC, column B holds the MIDI note number, and
each kit's sound name sits every fourth column from E.  The PDF path has to
infer column boundaries from text layout, which cost two bugs -- rows for
keys that exist on the keyboard carry an extra label before the numbers, so
a leading-digit match found only 18 rows of ninety; and locating columns by
clustering the data loses the columns that are mostly blank, which are
exactly the ones that mean "same as the reference kit".

PC is 1-based where MIDI program numbers are 0-based: a style declaring
program 56 wants PC 57.  Notes are MIDI numbers, not the keyboard numbers
printed beside them -- the two differ by an octave.
"""
import argparse
import collections
import json
import re

CODE = re.compile(r"(\d{3})/(\d{3})/(\d{3,4})")
# A note row carries the note twice -- keyboard number then MIDI number --
# as "25   C#   0   13     C# -1".  Rows for keys that exist on the keyboard
# are ALSO labelled with that key at the start of the line ("C1", "C#1"), and
# requiring the line to begin with a digit matched only the 18 rows that
# happen to lack a label, out of about ninety.
ROW = re.compile(r"^\s*(?:[A-G]#?-?\d\s+)?(\d{1,3})\s+([A-G]#?)\s+(-?\d)"
                 r"\s+(\d{1,3})\s+([A-G]#?)\s+(-?\d)")


def cells(line, starts):
    """Split one row into its kit cells, by the data columns given."""
    groups = [(m.start(), m.group().strip())
              for m in re.finditer(r"\S+(?: \S+)*", line)]
    out = []
    edges = list(starts) + [10 ** 6]
    for i in range(len(starts)):
        txt = " ".join(t for c, t in groups if edges[i] <= c < edges[i + 1])
        out.append(txt.strip())
    return out


def data_columns(rows, want):
    """Cluster the start columns of the rows' cells, keeping the busiest."""
    counts = collections.Counter(c for r in rows for c, _ in r)
    clusters = []
    for col in sorted(counts):
        if clusters and col - clusters[-1][-1] <= 3:
            clusters[-1].append(col)
        else:
            clusters.append([col])
    ranked = sorted(clusters, key=lambda g: -sum(counts[c] for c in g))
    return sorted(min(g) for g in ranked[:want])


def parse(text):
    """{"MSB/LSB/PC": {"name": str, "notes": {midi: sound}}}."""
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if "MSB (0" in l]
    kits = {}
    for n, h in enumerate(heads):
        codes = CODE.findall(lines[h])
        if not codes:
            continue
        # Kit names sit on the few lines under the code line; take the line
        # with as many separated groups as there are codes.
        # Kit names are separated by runs of two or more spaces.  A character
        # class that includes a single space does not work: it runs greedily
        # across the gaps and returns every name on the line as one string.
        # Take the kit names WITH their column positions.  Those positions
        # are the cell boundaries: every kit has a name in the header even
        # when its column is almost all blanks, whereas clustering the data
        # only finds columns that have data in them -- which is why Rock,
        # Room, Brush and Jazz came back with a dozen notes each instead of
        # seventy.  A mostly-blank column means "same as the reference kit",
        # so it is exactly the columns with least data that must not be lost.
        HDR = {"Keyboard", "MIDI", "Key", "Alternate", "Off", "Group",
               "Voice No.", "Note#", "Note"}
        named, best = None, -1
        for j in range(h + 1, min(h + 7, len(lines))):
            g = [(m.start(), m.group().strip())
                 for m in re.finditer(r"\S+(?: \S+)*", lines[j])]
            g = [(c, t) for c, t in g if re.match(r"[A-Z]", t) and len(t) > 2
                 and t not in HDR and "MSB" not in t and "Note#" not in t]
            if len(g) >= len(codes) and len(g) > best:
                named, best = g, len(g)
        if named:
            named = named[:len(codes)]
            names = [t for _, t in named]
            hdr_cols = [c for c, _ in named]
        else:
            names, hdr_cols = [f"kit{i}" for i in range(len(codes))], None
        names = names[:len(codes)]
        while len(names) < len(codes):
            names.append(f"kit{len(names)}")
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = []
        for line in lines[h:end]:
            m = ROW.match(line)
            if not m:
                continue
            midi = int(m.group(4))
            tail = line[m.end():]
            off = m.end()
            groups = [(c.start() + off, c.group().strip())
                      for c in re.finditer(r"\S+(?: \S+)*", tail)]
            body.append((midi, groups))
        if not body:
            continue
        if hdr_cols and len(hdr_cols) == len(codes):
            # Cells sit a little left of their header text; nudge the
            # boundaries left by the gap the data itself reveals.
            found = data_columns([g for _, g in body], len(codes))
            lead = 0
            if found:
                lead = max(0, min(hdr_cols) - min(found))
            starts = [max(0, c - lead) for c in hdr_cols]
        else:
            starts = data_columns([g for _, g in body], len(codes))
        if len(starts) < len(codes):
            continue
        for midi, groups in body:
            vals = []
            edges = starts + [10 ** 6]
            for i in range(len(starts)):
                vals.append(" ".join(t for c, t in groups
                                     if edges[i] <= c < edges[i + 1]).strip())
            # Drop a leading alternate-group digit that shares the first cell.
            if vals and re.fullmatch(r"\d", vals[0] or ""):
                vals[0] = ""
            ref = vals[0] if vals else ""
            for i, (msb, lsb, pc) in enumerate(codes):
                key = f"{int(msb)}/{int(lsb)}/{int(pc)}"
                sound = vals[i] if i < len(vals) else ""
                if not sound:
                    sound = ref          # blank means "as the reference kit"
                if not sound or sound in ("O",):
                    continue
                k = kits.setdefault(key, {"name": names[i], "notes": {}})
                k["notes"].setdefault(str(midi), sound)
    return kits


# --- spreadsheet Data List -------------------------------------------------
CELL = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


def _letters(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _grid(zf, target, shared):
    import re as _re
    raw = zf.read("xl/" + target.lstrip("/").replace("xl/", ""))
    doc = raw.decode("utf-8", "replace")
    out = {}
    for m in CELL.finditer(doc):
        col, row, attrs, body = m.groups()
        if body is None:                 # a self-closing, empty cell
            continue
        v = _re.search(r"<v>(.*?)</v>", body, _re.S)
        if v is None:
            t = _re.search(r"<t[^>]*>(.*?)</t>", body, _re.S)
            if t:
                out[(int(row), col)] = _re.sub(r"<[^>]+>", "",
                                               t.group(1)).strip()
            continue
        val = v.group(1)
        if 't="s"' in attrs:
            i = int(val)
            val = shared[i] if i < len(shared) else val
        out[(int(row), col)] = val.replace("\r", " ").strip()
    return out


def parse_xlsx(path, want="920"):
    """{"MSB/LSB/PC": {"name": str, "notes": {midi: sound}}} from a Data List."""
    import zipfile
    zf = zipfile.ZipFile(path)
    wb = zf.read("xl/workbook.xml").decode("utf-8", "replace")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    rmap = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))
    names = re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb)
    shared = []
    if "xl/sharedStrings.xml" in zf.namelist():
        raw = zf.read("xl/sharedStrings.xml").decode("utf-8", "replace")
        shared = [re.sub(r"<[^>]+>", "", m).replace("\r", " ").strip()
                  for m in re.findall(r"<si>(.*?)</si>", raw, re.S)]
    sheet = None
    for nm, rid in names:
        if "Drum" in nm and want in nm:
            sheet = rmap[rid]
            break
    if sheet is None:
        for nm, rid in names:
            if "Drum" in nm:
                sheet = rmap[rid]
                break
    if sheet is None:
        raise SystemExit("no Drum & SFX Kit List sheet in this workbook")
    g = _grid(zf, sheet, shared)
    # Row 4 names the kits, row 5 gives MSB-LSB-PC, both every fourth column
    # from E; column B carries the MIDI note number.
    kits, cols = {}, []
    for i in range(4, 400, 4):
        c = _letters(i)
        name, code = g.get((4, c)), g.get((5, c))
        if not code:
            continue
        m = re.match(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", code)
        if not m:
            continue
        key = f"{int(m.group(1))}/{int(m.group(2))}/{int(m.group(3))}"
        kits[key] = {"name": (name or key).strip(), "notes": {}}
        cols.append((c, key))
    for (row, c), v in g.items():
        if c != "B" or not v.isdigit():
            continue
        midi = int(v)
        if not 0 <= midi <= 127:
            continue
        for col, key in cols:
            sound = g.get((row, col))
            if sound and sound not in ("O",):
                kits[key]["notes"][str(midi)] = sound
    return kits


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text", help="a Data List .xlsx, or its text from "
                                "`pdftotext -layout`")
    p.add_argument("--model", default="920",
                   help="which model's sheet to read when the workbook holds "
                        "several (default 920)")
    p.add_argument("--kit", help="print one kit, by name or MSB/LSB/PC")
    p.add_argument("--json")
    a = p.parse_args()
    if a.text.lower().endswith((".xlsx", ".xlsm")):
        kits = parse_xlsx(a.text, a.model)
    else:
        kits = parse(open(a.text, encoding="utf-8").read())
    if a.kit:
        hit = [k for k, v in kits.items()
               if k == a.kit or v["name"].lower() == a.kit.lower()]
        if not hit:
            raise SystemExit("no such kit; have: "
                             + ", ".join(sorted({v['name'] for v in kits.values()})))
        k = kits[hit[0]]
        print(f"{k['name']}  ({hit[0]}), {len(k['notes'])} notes")
        for n in sorted(k["notes"], key=int):
            print(f"  {int(n):3d}  {k['notes'][n]}")
    elif a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(kits, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"wrote {a.json}: {len(kits)} kits")
    else:
        for key, v in sorted(kits.items()):
            print(f"  {key:16s} {v['name']:<26} {len(v['notes']):3d} notes")


if __name__ == "__main__":
    main()
