"""Read Yamaha's Voice List out of a PSR Data List .xlsx.

    python3 tools/yamahavoices.py DataList.xlsx --json maps/yamaha-voices.json
    python3 tools/yamahavoices.py DataList.xlsx --find santur

The companion to tools/yamahakits.py: that one says what a drum NOTE means,
this one says what a melodic PART is playing.  A style part declares its
voice as a bank MSB, bank LSB and program, and the 46 Iranian styles name 187
distinct ones across their bass and chord parts -- santurs, ouds, kanuns,
Arabic strings and a lot of synth variations.  Without this table those are
just three numbers and the converter has nothing to map them to.

The sheet is laid out one voice per row: column B category, C sub-category,
D the voice name, E/F/G the MSB, LSB and PC, H the voice type (S.Art, Mega,
Live, Cool, Sweet and so on).

PC here is 1-based, 1-128, as the header says.  Everything else in this
project uses the raw MIDI program, so the JSON is keyed on MSB/LSB/program
with the program 0-based -- the same numbers a style's program-change event
carries.
"""
import argparse
import collections
import json
import re
import sys
import zipfile

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from yamahakits import _grid                        # noqa: E402


def parse(path, want=None):
    """{"msb/lsb/program": {"name", "category", "sub", "type"}}."""
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
    picked = [(nm, rid) for nm, rid in sheets if "Voice List" in nm
              and (want is None or want in nm)]
    if not picked:
        picked = [(nm, rid) for nm, rid in sheets if "Voice List" in nm]
    if not picked:
        raise SystemExit("no Voice List sheet in this workbook")
    out = {}
    for nm, rid in picked:
        g = _grid(zf, rmap[rid], shared)
        cat = sub = ""
        for row in sorted({r for r, _ in g}):
            cell = lambda c: g.get((row, c), "")      # noqa: E731
            cat = cell("B") or cat
            sub = cell("C") or sub
            name, msb, lsb, pc = (cell("D"), cell("E"), cell("F"), cell("G"))
            if not (name and msb.isdigit() and lsb.isdigit() and pc.isdigit()):
                continue
            prog = int(pc) - 1                        # the sheet's PC is 1-128
            if not 0 <= prog <= 127:
                continue
            key = f"{int(msb)}/{int(lsb)}/{prog}"
            out.setdefault(key, {"name": name, "category": cat,
                                 "sub": sub, "type": cell("H")})
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsx", nargs="+")
    p.add_argument("--model", help="restrict to sheets naming this model")
    p.add_argument("--find", help="print voices whose name matches")
    p.add_argument("--json")
    a = p.parse_args()
    voices = {}
    for path in a.xlsx:
        got = parse(path, a.model)
        for k, v in got.items():
            voices.setdefault(k, v)
        print(f"{path.rsplit('/', 1)[-1]}: {len(got)} voices", file=sys.stderr)
    if a.find:
        rx = re.compile(a.find, re.I)
        for k, v in voices.items():
            if rx.search(v["name"]):
                print(f"  {k:<14} {v['name']:<24} {v['category']}/{v['sub']}")
        return
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(voices, f, indent=1, ensure_ascii=False, sort_keys=True)
        print(f"wrote {a.json}: {len(voices)} voices")
    else:
        cat = collections.Counter(v["category"] for v in voices.values())
        for c, n in cat.most_common():
            print(f"  {n:4d}  {c}")


if __name__ == "__main__":
    main()
