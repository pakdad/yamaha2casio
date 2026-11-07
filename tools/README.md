# tools

Standalone scripts; none of them is needed to convert a style. Like the rest
of this repository they use **only the standard library** — there is nothing
to install.

They do three jobs: read the makers' published tables into `maps/`, convert a
folder in one go, and build the program.

Recording and transcribing audio used to live here. It is a different job with
different dependencies, so it moved to
[audio2style](https://github.com/pakdad/audio2style), which writes `.sty`
files for this to convert.

## Reading the published tables

These turn a manual into the lookup tables the converter needs. None of their
output is distributed with this repository; `docs/README.md` says where to get
the source documents.

| script | reads | writes |
|---|---|---|
| `drumlist.py` | Casio's tone/rhythm appendix, as text | `maps/ctx-drum-assignments.json` |
| `ctxtones.py` | the same text | `maps/ctx-tones.json` |
| `yamahakits.py` | a Yamaha PSR Data List `.xlsx` | `maps/yamaha-drum-kits.json` |
| `yamahavoices.py` | the same workbook | `maps/yamaha-voices.json` |
| `megavoice.py` | the same workbook | `maps/yamaha-megavoice.json` |

Each takes `--grep` to look something up without writing a file:

```sh
python3 tools/ctxtones.py /tmp/app.txt --grep 'santur|oud|kanun|ney'
```

## Choosing and checking a kit

* `kit_table.py` — which notes each CT-X drum kit actually has, read off a
  tree of factory rhythms. Casio publishes no drum assignment list for the
  non-GM kits, so this is the only way to know whether a note will make a
  sound at all. `--covers DIR ROLE` scores every kit against what a set of
  rhythms plays on one part, which is how to pick the kit for a conversion
  instead of guessing.

* `make_drummap.py` — pairs two Casio kits into a hand-checkable map from the
  generated tables, so the result can be read and corrected rather than
  trusted.

The factory rhythms reveal a key's rhythmic *role* but never its sound. To
establish that you have to play a probe and listen; see the main README's
"Asking the keyboard instead of guessing".

## Converting a folder

* `convert_all.py` — converts every style in a directory, giving each a
  stable 8-character filename for the keyboard and a 12-character display
  name, and reporting what it had to drop, clamp or fold.

## Recording the keyboard

* `capture.sh` — record the keyboard over one aligned window: USB-MIDI into
  `midi.mid` and `midi.txt`, line-in audio into `audio.wav`.

  ```sh
  ./tools/capture.sh 60 mytake
  ```

  It is here because `y2c.py kitdiff` reads the MIDI side: a timestamped
  capture of the keyboard's accompaniment output is what lets the converter
  compare the kit it *thinks* it is addressing against the one the instrument
  actually plays. The same script is also in `audio2style`, which needs the
  audio side; it is sixty lines of ALSA and depends on neither repository's
  code, so both carry a copy rather than one borrowing from the other.

  **The CT-X5000 does not transmit its auto-accompaniment over MIDI.** It
  sends what the keys play — a minute with a factory rhythm running produced
  225 Active Sensing messages and not one note event, while hand-played keys
  on the same link produced 96 note-ons on channel 0. So a rhythm playing on
  the instrument can be checked only by recording its audio, which is what
  the companion repository is for.

## Building the program

* `build_app.py` — freeze the window into one runnable file for the machine
  you are on. `--check` reports what a build here would produce without
  building it.

* `build_windows_exe.sh` — the same for Windows, via wine.

**PyInstaller cannot cross-compile.** It bundles the interpreter that runs it,
so the building machine fixes both the operating system and the processor:
a Windows `.exe` needs a Windows Python, and an x86-64 one needs an x86-64
Python. There is no flag for either. `build_app.py` says what you are actually
going to get before it starts.
