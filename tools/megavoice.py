"""Read Yamaha's MegaVoice Map out of a PSR Data List .xlsx.

    python3 tools/megavoice.py DataList.xlsx --json maps/yamaha-megavoice.json
    python3 tools/megavoice.py DataList.xlsx --voice ElectricBass

A MegaVoice is not a louder or quieter instrument -- it is a bank of
articulations stacked behind one program, selected by how hard the note is
struck and where on the keyboard it sits.  ElectricBass answers velocity
1-60 with an open note, 61-80 with a harder one, 81-120 with a DEAD note and
121-127 with a SLAP; and every key from C6 up is a sound effect rather than a
pitch at all.  Yamaha's styles use this constantly, because it is how a
sequenced bass line gets real playing noise in it.

On any instrument that is not a Yamaha those extra layers are nonsense.  The
velocity still arrives, so the dead notes and slaps come out as ordinary
notes played hard, and the key zones still arrive, so the strum and fret
noise comes out as shrill high pitches.  Measured over the 46 Iranian styles:
19.0% of all melodic notes are on MegaVoice parts, 26.9% of those are not a
plain dynamic, and 16.9% of them sit in the noise key zone -- 2,109 notes
that cannot be anything but wrong.

The sheet puts each voice on two rows: the first carries MSB, LSB, PC, the
voice name and the velocity ranges, the second the label for each range.
Columns F to AD are velocity switch points; AE and beyond are key zones,
headed "C6 and higher" and "C8 and higher".

Those names are in Yamaha's keyboard octaves, where middle C is C3, so C6 is
MIDI 96 and C8 is MIDI 120 -- and the styles confirm it rather than the other
way round.  Their MegaVoice notes form two populations with a clean gap:
10,380 run from key 24 to key 83 and stop, SEVEN stray notes sit in 84-95,
and then 2,109 notes cluster from exactly 96 upwards with a second rise at
exactly 120.  Both thresholds land on the document's own boundaries.
"""
import argparse
import json
import re
import sys
import zipfile

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from yamahakits import _grid                         # noqa: E402

# Yamaha keyboard octaves: C3 is middle C, so C6 and C8 are these MIDI keys.
NOISE_C6 = 96
NOISE_C8 = 120

RANGE = re.compile(r"^(\d{1,3})\s*-\s*(\d{1,3})$")


def _colnum(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


KEYZONE_FROM = _colnum("AE")


def parse(path, want=None):
    """{"msb/lsb/program": {"name", "vel": [[lo, hi, label]], "noise_from"}}."""
    zf = zipfile.ZipFile(path)
    wb = zf.read("xl/workbook.xml").decode("utf-8", "replace")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    rmap = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))
    sheets = re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb)
    shared = []
    if "xl/sharedStrings.xml" in zf.namelist():
        raw = zf.read("xl/sharedStrings.xml").decode("utf-8", "replace")
        shared = [re.sub(r"<[^>]+>", "", m).replace("\r", " ").strip()
                  for m in re.findall(r"<si>(.*?)</si>", raw, re.S)]
    picked = [r for nm, r in sheets if "MegaVoice" in nm
              and (want is None or want in nm)] or \
             [r for nm, r in sheets if "MegaVoice" in nm]
    if not picked:
        raise SystemExit("no MegaVoice Map sheet in this workbook")
    out = {}
    for rid in picked:
        g = _grid(zf, rmap[rid], shared)
        rows = sorted({r for r, _ in g})
        pending = None
        for row in rows:
            cells = {c: v for (r, c), v in g.items() if r == row and v}
            msb, lsb, pc = cells.get("B"), cells.get("C"), cells.get("D")
            ranges = {c: v for c, v in cells.items()
                      if _colnum(c) >= _colnum("F") and RANGE.match(v)}
            if msb and lsb and pc and msb.isdigit() and pc.isdigit():
                # A new voice.  Its label row has not been read yet.
                pending = {"key": f"{int(msb)}/{int(lsb)}/{int(pc) - 1}",
                           "name": cells.get("E", ""), "ranges": ranges}
                continue
            if pending is None or ranges:
                # A sub-element row of a layered voice: the first element's
                # switch points are the ones that matter, so later ones are
                # left alone rather than overwriting them.
                continue
            # A label row: pair each label with the range in the same column.
            vel, noise = [], None
            for col, rng in pending["ranges"].items():
                label = cells.get(col, "").strip().lower()
                lo, hi = (int(x) for x in RANGE.match(rng).groups())
                if _colnum(col) >= KEYZONE_FROM:
                    if label:
                        noise = NOISE_C6
                    continue
                vel.append([lo, hi, label])
            vel.sort()
            if pending["name"] and vel:
                out.setdefault(pending["key"], {
                    "name": pending["name"], "vel": vel,
                    "noise_from": noise or NOISE_C6})
            pending = None
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsx", nargs="+")
    p.add_argument("--model")
    p.add_argument("--voice", help="print one voice's layers, by name")
    p.add_argument("--labels", action="store_true",
                   help="print every articulation label the table uses")
    p.add_argument("--json")
    a = p.parse_args()
    table = {}
    for path in a.xlsx:
        got = parse(path, a.model)
        for k, v in got.items():
            table.setdefault(k, v)
        print(f"{path.rsplit('/', 1)[-1]}: {len(got)} MegaVoices",
              file=sys.stderr)
    if a.voice:
        for k, v in table.items():
            if a.voice.lower() in v["name"].lower():
                print(f"{v['name']}  ({k}), noise from key {v['noise_from']}")
                for lo, hi, label in v["vel"]:
                    print(f"  vel {lo:3d}-{hi:3d}  {label}")
        return
    if a.labels:
        import collections
        c = collections.Counter(l for v in table.values()
                                for _, _, l in v["vel"])
        for label, n in c.most_common():
            print(f"  {n:4d}  {label}")
        return
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(table, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"wrote {a.json}: {len(table)} MegaVoices")
    else:
        for k, v in sorted(table.items()):
            print(f"  {k:<12} {v['name']:<24} {len(v['vel'])} layers")


if __name__ == "__main__":
    main()
