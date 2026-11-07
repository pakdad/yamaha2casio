Windows build of `y2c`, for 64-bit Intel/AMD Windows. Built by GitHub Actions
on a Windows runner — see `.github/workflows/windows-exe.yml`.

Download `y2c.exe` and run it. Nothing to install: Python and Tk are inside.

## What you also need

| | |
|---|---|
| **a rhythm of your own, saved from your CT-X to USB** | The converter writes into a real `.AC7` container, so it needs one to write into. Factory rhythms are Casio's content and none ship here. Any user rhythm will do; one that uses all its parts in all its sections works best. |
| **Yamaha styles** | `.sty`, `.prs`, `.bcs` or `.pcs`. Yours to find. |

## Read this before judging the tones

**The tone and drum-kit tables are not in this download.** They are generated
from Casio's and Yamaha's own manuals, which are their content, so they are
not distributed — not in the repository and not in this `.exe`.

Without them the conversion still runs, and the meter, bar counts, part
layout, chord handling and the hand-written drum maps all work. But **the
tone mapping does not**, so every melodic part will play whatever tone your
template rhythm had, instead of the nearest CT-X equivalent of what the style
asked for. If the tones sound wrong, this is almost certainly why, and it is
not the converter failing.

The window tells you at startup which tables it is missing. To supply them,
put a `maps/` folder containing them **next to `y2c.exe`** and restart — a
folder beside the program is preferred over anything built in. The
repository's `docs/README.md` gives the one command that builds each from a
manual you own.

For the full thing, run from source instead. It is pure standard-library
Python 3, so there is nothing to install there either.

## Reporting a problem

The useful report names the part and the note, not the overall impression:
"the chord 2 tone in variation 3 is wrong", or "the percussion B flat in the
second octave plays a whistle". Those are what fixed nearly every problem so
far, because a single bad note almost always turns out to be one whole class
of fault rather than one wrong entry.

Known gaps are listed in the README: fill-ins can only be 1–2 bars, the fifth
chord part has no slot in the AC7 layout and is folded into a free part when
there is one, and some Yamaha kits hold far more sounds than any CT-X kit, so
some collapse is unavoidable.

The `.AC7` format is undocumented; everything here was worked out by
measurement and checked against Casio's published manuals. *Casio*, *CT-X*,
*Yamaha* and *PSR* are their owners' trademarks. This project is not
affiliated with either company.
