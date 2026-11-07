"""Casio AC7 rhythm files: reader, writer, and inspector.

FORMAT
------
Reverse-engineered from a factory rhythm exported from a CT-X5000, and
verified by rebuilding that file byte-for-byte (see `y2c.py ac7check`).
All multi-byte values are little-endian.

  0x00  4   'AC07'
  0x04  u32 total file size
  0x08  u32 base offset for element pointers (0x1c)
  0x0c  u32 MIXR section offset (absolute)
  0x10  u32 DRUM section offset (absolute)
  0x14  u32 OTHR section offset (absolute)
  0x18  u32 0xffffffff (unused slot)
  0x1c  7   directory head; byte 0x22 is the element count
  0x23  u32 x count   element offsets, relative to 0x1c
  then  TLV parameter stream: id 0x00 = 12-byte rhythm name,
        id 0x02 = tempo in BPM, terminated by `ff 00`
  then  one 'ELMT' chunk per element
  then  'MIXR', 'DRUM', 'OTHR'

Chunks are `tag(4) + u16 length` where the length spans the tag itself.
ELMT bodies are TLV streams (id, len, value; `ff 00` ends them); of these
id 0x06 is the length in bars, 0x07 the track count and 0x22 the track codes.

MIXR/DRUM/OTHR add `u16 unknown + u16 count + count x u32 absolute offsets`
before their payload.  DRUM holds the event streams of the drum and
percussion tracks, OTHR every pitched and control track; streams appear in
element order, and `code & 0x0f` picks the part (0 drum, 1 percussion,
2 bass, 3-6 chord, 0x0f control).

An event stream is a flat run of 3-byte frames, `(delta, code, value)`:

  code 0x01-0x7f   note: value is velocity, or 0 for note-off
  code 0x80-0xfb   controller / setup (pitch bend, tone selection, ...)
  code 0xfc        end of stream; its delta pads to the element's end
  code 0xff        meta

Resolution is 96 ticks per quarter note, so a 4/4 bar is 384 ticks.
"""
from __future__ import annotations

import string
import struct
from collections import Counter
from dataclasses import dataclass, field

MAGIC = b"AC07"
PPQN = 96
END = 0xFC
META = 0xFF

# part index (code & 0x0f) -> role name used by the rest of the toolkit.
# The index is the accomp MIDI channel minus 9, so by the MIDI Implementation
# table (channels 9-16 = Percussion, Drum, Bass, Chord 1-5) part 0 is the
# PERCUSSION part and part 1 the DRUM part -- not the other way round.  Two
# independent checks agree: the MIXR column at this index holds GM program 33
# (fingered bass) for part 2, matching channel 11; and in the factory rhythms
# part 1 is the one carrying the standard kick/snare/hat vocabulary while
# part 0 carries shakers, tambourines and the kit's extended notes.
# Part 7 is Chord 5.  The manual's mixer section lists the eight parts the
# number keys select -- Percussion [1], Drums [2], Bass [3], Chord 1 to
# Chord 5 [4] to [8] -- which is why MIXR carries eight rows per element.
# It had no name here before, so describe() called it "part7"; the accomp
# channel arithmetic (part = channel - 9) only reaches part 6, because MIDI
# stops at channel 15, so the fifth chord part is never visible that way.
PART_ROLE = {0: "perc", 1: "drum", 2: "bass", 3: "chord1",
             4: "chord2", 5: "chord3", 6: "chord4", 7: "chord5",
             0x0F: "control"}
DRUM_PARTS = (0, 1)

# Element order as it appears in the file.  Inferred from the bar-length
# pattern of the factory sample (4,4,4,1,1,4 twice over, so the one-bar
# elements at 3/4 and 9/10 are the fill-ins); verify by ear after converting.
ELEMENT_ROLES = ["Intro1", "Variation1", "Variation2", "Fill1", "Fill2",
                 "Ending1", "Intro2", "Variation3", "Variation4",
                 "Fill3", "Fill4", "Ending2"]

# Slots 6 and 11 are empty in all three factory rhythms, and their MIXR rows
# sit at the file's default tone/volume while every used slot carries real
# values.  The format is two blocks of six -- intro, two variations, two
# fills, ending -- and the keyboard drives only the first block's intro and
# ending, so writing these two slots has no audible effect.
UNUSED_ELEMENTS = (6, 11)


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------

def hexdump(data, offset=0, length=256, width=16):
    out = []
    for row in range(offset, min(offset + length, len(data)), width):
        chunk = data[row:row + width]
        hexs = " ".join(f"{b:02x}" for b in chunk).ljust(width * 3 - 1)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{row:08x}  {hexs}  |{text}|")
    return "\n".join(out)


def read_tlv(data, start, end):
    """Parse an (id, len, value) stream; stops after the 0xff terminator."""
    out, o = [], start
    while o < end:
        pid = data[o]
        if pid == META:
            o += 2
            break
        ln = data[o + 1]
        out.append((pid, data[o + 2:o + 2 + ln]))
        o += 2 + ln
    return out, o


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

@dataclass
class Frame:
    dt: int
    code: int
    val: int

    @property
    def is_note(self):
        return 0 < self.code < 0x80

    def bytes(self):
        return bytes([self.dt & 0xFF, self.code & 0xFF, self.val & 0xFF])


@dataclass
class Track:
    code: int
    frames: list = field(default_factory=list)
    section: str = ""                # "DRUM" or "OTHR", as the file allocates

    @property
    def part(self):
        return self.code & 0x0F

    @property
    def role(self):
        return PART_ROLE.get(self.part, f"part{self.part}")

    @property
    def in_drum_section(self):
        """Which of the two stream sections holds this track's events.

        Read from the element's 0x20 index table where available.  The part
        index is only a fallback: it predicts the section correctly for a bit
        over half of the factory rhythms and not for the rest, so a file that
        says otherwise is believed.
        """
        if self.section:
            return self.section == "DRUM"
        return self.part in DRUM_PARTS

    def notes(self):
        """Pair note-on/note-off frames into (tick, dur, key, vel)."""
        out, open_n, t = [], {}, 0
        for f in self.frames:
            t += f.dt
            if not f.is_note:
                continue
            if f.val:
                open_n.setdefault(f.code, []).append((t, f.val))
            else:
                stack = open_n.get(f.code)
                if stack:
                    start, vel = stack.pop(0)
                    out.append((start, max(1, t - start), f.code, vel))
        for key, stack in open_n.items():
            for start, vel in stack:
                out.append((start, 24, key, vel))
        out.sort()
        return out

    def prefix(self):
        """The track's setup frames: controllers and meta before the music.

        Their deltas are zeroed so the setup lands at tick 0 -- otherwise the
        clock is already advanced when the first replacement note is written,
        and the whole track plays late by that amount.  Note frames in the
        head of the stream belong to the template's own music, so they go.
        """
        head = self.frames
        for i, f in enumerate(self.frames):
            if f.is_note and f.val:
                head = self.frames[:i]
                break
        return [Frame(0, f.code, f.val) for f in head
                if not f.is_note and f.code != END]

    def total_ticks(self):
        return sum(f.dt for f in self.frames)


@dataclass
class Element:
    index: int
    raw: bytes                       # the complete ELMT chunk, kept verbatim
    bars: int
    codes: list
    tracks: list = field(default_factory=list)

    @property
    def role(self):
        return (ELEMENT_ROLES[self.index] if self.index < len(ELEMENT_ROLES)
                else f"Element{self.index}")

    def track(self, role):
        for t in self.tracks:
            if t.role == role:
                return t
        return None

    def bar_lengths(self):
        """Ticks-per-bar implied by each of this element's event streams.

        A full-length stream ends with a 0xfc frame whose delta pads out to
        the element's end, so most tracks run exactly bars x ticks-per-bar.
        Sparse tracks stop early and a few overrun by a handful of ticks, so
        this returns every candidate and lets the caller take a consensus.
        """
        if not self.bars:
            return []
        return [L // self.bars for L in
                (t.total_ticks() for t in self.tracks)
                if L and L % self.bars == 0]


@dataclass
class Ac7:
    dir_head: bytes = b""            # 0x1c .. 0x22 inclusive
    file_params: bytes = b""         # name TLV + file parameters, verbatim
    unused18: int = 0xFFFFFFFF
    base: int = 0x1C
    mixr: bytes = b""                # the whole MIXR chunk, verbatim
    drum_head: bytes = b""           # DRUM tag+len+unknown, rebuilt on write
    othr_head: bytes = b""
    elements: list = field(default_factory=list)

    @property
    def name(self):
        for pid, val in read_tlv(self.file_params, 0, len(self.file_params))[0]:
            if pid == 0x00:
                return val.decode("latin-1").rstrip("\x00 ")
        return ""

    @property
    def tempo(self):
        for pid, val in read_tlv(self.file_params, 0, len(self.file_params))[0]:
            if pid == 0x02 and val:
                return val[0]
        return 0

    @property
    def meter_code(self):
        """The raw time-signature byte (file-level TLV id 0x01), or None."""
        for pid, val in read_tlv(self.file_params, 0, len(self.file_params))[0]:
            if pid == 0x01 and val:
                return val[0]
        return None

    @property
    def meter(self):
        """The stored time signature as (numerator, denominator), or None."""
        code = self.meter_code
        return meter_from_code(code) if code is not None else None

    def measured_ticks_per_bar(self):
        """The rhythm's ticks per bar, taken as a consensus of its streams.

        The time signature is also stored in a file field this tool has not
        decoded (see the README), but the event streams themselves give the
        bar length directly, which is what actually has to match the style.
        Returns None when no value is clearly dominant.
        """
        votes = Counter(L for el in self.elements for L in el.bar_lengths())
        if not votes:
            return None
        top = votes.most_common(2)
        (best, n) = top[0]
        runner = top[1][1] if len(top) > 1 else 0
        # Sparse tracks stop early and a few overrun, so a clear plurality --
        # at least twice the runner-up -- is the signal, not a majority.
        return best if n >= 2 and n >= 2 * runner else None

    def tracks_in(self, section):
        """All tracks of a section, in the order the file stores them."""
        want = section == "DRUM"
        return [t for el in self.elements for t in el.tracks
                if t.in_drum_section == want]


# Meters a CT-X rhythm slot can hold, as ticks per bar at 96 ppqn.  Several
# share a bar length -- 3/4 and 6/8 are both 288 -- so a measured bar length
# narrows the meter without always pinning it down.
COMMON_METERS = [(2, 4), (3, 4), (4, 4), (5, 4), (6, 4),
                 (3, 8), (5, 8), (6, 8), (7, 8), (9, 8), (12, 8), (2, 2)]


def ticks_per_bar(num, den):
    return int(PPQN * 4 * num / den)


# The time signature lives in TLV id 0x01, which appears once at file level
# and again on every element.  The byte packs the numerator into its top five
# bits and the denominator's power of two into the low three:
#
#     code = (numerator << 3) | log2(denominator)
#
# Verified against three factory rhythms exported from a CT-X5000: 4/4 is
# 0x22, 6/8 is 0x33 and 3/4 is 0x1a, and in each one the decoded meter agrees
# with the bar length measured independently from the event streams.
METER_CODES = {(4, 4): 0x22, (6, 8): 0x33, (3, 4): 0x1A}

_DEN_EXP = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7}


# What the instrument itself accepts, from the manual's rhythm editor (EN-77,
# "Beat (time signature) ... Setting Ranges: 2/4 to 8/4, 2/8 to 16/8").  The
# codec round-trips every meter in that range, which is a far stronger check
# than the three codes we could read off factory rhythms.  It also bounds the
# domain: a denominator of 16 or 2, or a numerator past these limits, has no
# representation the keyboard will read, so say so instead of writing a byte
# it cannot interpret.
METER_RANGE = {4: (2, 8), 8: (2, 16)}


def meter_code(num, den):
    """(code, verified) for a meter, or (None, False) if not representable."""
    if (num, den) in METER_CODES:
        return METER_CODES[(num, den)], True
    lo_hi = METER_RANGE.get(den)
    if lo_hi is None or not lo_hi[0] <= num <= lo_hi[1]:
        return None, False
    return (num << 3) | _DEN_EXP[den], False


def meter_from_code(code):
    """Inverse of meter_code; None when the byte does not decode."""
    num, exp = code >> 3, code & 0x07
    if not num:
        return None
    return (num, 1 << exp)


def meter_candidates(tpb):
    """Every common meter with this bar length, best-known first."""
    return [m for m in COMMON_METERS if ticks_per_bar(*m) == tpb]


def describe_meter(tpb):
    if tpb is None:
        return "unknown"
    cands = meter_candidates(tpb)
    names = " or ".join(f"{n}/{d}" for n, d in cands) if cands else "non-standard"
    return f"{tpb} ticks/bar ({names})"


# --------------------------------------------------------------------------
# parse
# --------------------------------------------------------------------------

def _section(data, off):
    ln, cnt = struct.unpack_from("<HH", data, off + 4)[0], None
    unk, cnt = struct.unpack_from("<HH", data, off + 6)
    tbl = [struct.unpack_from("<I", data, off + 10 + 4 * i)[0]
           for i in range(cnt)]
    spans = [(tbl[i], (tbl[i + 1] if i + 1 < cnt else off + ln) - tbl[i])
             for i in range(cnt)]
    return ln, unk, spans


def stream_index(table):
    """The per-track stream indices in element TLV 0x20 (14-bit, flag in 0x80)."""
    return [table[2 * k] | ((table[2 * k + 1] & 0x7F) << 8)
            for k in range(len(table) // 2)]


def _drum_positions(codes, table, di, oi):
    """Which of an element's track positions have their events in DRUM.

    Positions, not code values: an element may list the same code twice (the
    intro and ending elements store two copies of each part), so a set of
    codes would classify both copies alike and mis-split the streams.

    TLV 0x20 lists the element's stream indices, the DRUM-section ones first
    and then the OTHR-section ones, each run continuing that section's running
    count.  That makes the size of the DRUM run recoverable even though the
    table does not say which section an entry belongs to: it is the split that
    leaves both runs consecutive.  Where several splits fit, the one closest to
    the part-index prediction wins.

    The part index alone is not enough.  Of the 235 rhythms in the CT-X3000
    factory set it predicts the split for 135 and is wrong for the other 100 --
    usually by putting a second drum copy, or the drum part itself, in DRUM
    when the file keeps it in OTHR.
    """
    idx, n = stream_index(table), len(codes)
    drumish = [j for j, c in enumerate(codes) if (c & 0x0F) in DRUM_PARTS]
    if len(idx) != n:
        return set(drumish)
    fits = [k for k in range(n + 1)
            if idx[:k] == list(range(di, di + k))
            and idx[k:] == list(range(oi, oi + n - k))]
    if not fits:
        return set(drumish)
    k = min(fits, key=lambda c: abs(c - len(drumish)))
    # Fill the DRUM run from the drum parts first, then in track order, so the
    # common case (k == the number of drum parts) keeps the obvious labelling.
    chosen = drumish[:k]
    for j in range(n):
        if len(chosen) >= k:
            break
        if j not in chosen:
            chosen.append(j)
    return set(chosen)


def _frames(data, off, size):
    out = []
    for p in range(off, off + size, 3):
        out.append(Frame(data[p], data[p + 1], data[p + 2]))
    return out


def parse(data: bytes) -> Ac7:
    if data[:4] != MAGIC:
        raise ValueError(f"not an AC7 file (magic {data[:4]!r})")
    size, base, mixr_o, drum_o, othr_o, unused = struct.unpack_from("<6I", data, 4)
    if size != len(data):
        raise ValueError(f"size field {size} != actual {len(data)}")

    count = data[0x22]
    tbl_at = 0x23
    eoffs = [base + struct.unpack_from("<I", data, tbl_at + 4 * i)[0]
             for i in range(count)]

    ac7 = Ac7(dir_head=data[base:tbl_at],
              file_params=data[tbl_at + 4 * count:eoffs[0]],
              unused18=unused, base=base,
              mixr=data[mixr_o:mixr_o + struct.unpack_from("<H", data, mixr_o + 4)[0]],
              drum_head=data[drum_o:drum_o + 8],
              othr_head=data[othr_o:othr_o + 8])

    _, _, dspans = _section(data, drum_o)
    _, _, ospans = _section(data, othr_o)

    di = oi = 0
    for i, off in enumerate(eoffs):
        ln = struct.unpack_from("<H", data, off + 4)[0]
        body, _ = read_tlv(data, off + 6, off + ln)
        fields = {}
        for pid, val in body:
            fields.setdefault(pid, []).append(val)
        bars = fields[0x06][0][0]
        codes = list(fields[0x22][0])
        el = Element(i, data[off:off + ln], bars, codes)
        in_drum = _drum_positions(codes, fields.get(0x20, [b""])[0], di, oi)
        for j, c in enumerate(codes):
            if j in in_drum:
                so, ss = dspans[di]; di += 1
                sec = "DRUM"
            else:
                so, ss = ospans[oi]; oi += 1
                sec = "OTHR"
            el.tracks.append(Track(c, _frames(data, so, ss), sec))
        ac7.elements.append(el)
    if di != len(dspans) or oi != len(ospans):
        raise ValueError(f"stream allocation mismatch: DRUM {di}/{len(dspans)} "
                         f"OTHR {oi}/{len(ospans)}")
    return ac7


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def _build_section(head, tracks):
    """tag+len+unknown from `head`, then count, offset table and payload."""
    bodies = [b"".join(f.bytes() for f in t.frames) for t in tracks]
    cnt = len(bodies)
    table_at = 10
    data_at = table_at + 4 * cnt
    offs, run = [], data_at
    for b in bodies:
        offs.append(run)
        run += len(b)
    total = run
    out = bytearray(head[:4])
    out += struct.pack("<HHH", total, struct.unpack_from("<H", head, 6)[0], cnt)
    for o in offs:
        out += struct.pack("<I", o)          # patched to absolute by caller
    for b in bodies:
        out += b
    return bytes(out), offs, data_at


def build(ac7: Ac7) -> bytes:
    head_len = 0x1C
    body = bytearray()
    body += ac7.dir_head
    table_at = head_len + len(ac7.dir_head)
    body += b"\x00" * (4 * len(ac7.elements))        # element table placeholder
    body += ac7.file_params
    # element offsets are relative to `base`, and `body` starts at `base`
    eoffs, pos = [], len(body)
    for el in ac7.elements:
        eoffs.append(pos)
        pos += len(el.raw)
        body += el.raw
    struct.pack_into("<" + "I" * len(eoffs), body,
                     len(ac7.dir_head), *eoffs)

    mixr_off = head_len + len(body)
    body += ac7.mixr
    drum_off = head_len + len(body)
    drum, doffs, _ = _build_section(ac7.drum_head, ac7.tracks_in("DRUM"))
    body += drum
    othr_off = head_len + len(body)
    othr, ooffs, _ = _build_section(ac7.othr_head, ac7.tracks_in("OTHR"))
    body += othr

    out = bytearray(MAGIC)
    out += struct.pack("<6I", head_len + len(body), ac7.base,
                       mixr_off, drum_off, othr_off, ac7.unused18)
    out += body
    # stream offset tables hold absolute file offsets
    for sect_off, offs in ((drum_off, doffs), (othr_off, ooffs)):
        for i, o in enumerate(offs):
            struct.pack_into("<I", out, sect_off + 10 + 4 * i, sect_off + o)
    return bytes(out)


# --------------------------------------------------------------------------
# writing a converted rhythm into a template
# --------------------------------------------------------------------------

def encode_track(notes, prefix, total_ticks):
    """Build an event stream from (tick, dur, key, vel) notes.

    Deltas are a single byte, so a rest longer than 255 ticks is split with
    note-off frames for the upcoming key -- releasing a key that is not
    sounding is a no-op, which makes it a safe filler.
    """
    evs = []
    for tick, dur, key, vel in notes:
        evs.append((tick, 1, key, vel & 0x7F))
        evs.append((tick + dur, 0, key, 0))
    evs.sort(key=lambda e: (e[0], e[1]))

    frames, t = list(prefix), 0
    for tick, _on, key, vel in evs:
        gap = tick - t
        while gap > 0xFF:
            frames.append(Frame(0xFF, key, 0))
            gap -= 0xFF
        frames.append(Frame(gap, key, vel))
        t = tick
    # The trailing rest needs the same splitting as any other gap.  Clamping
    # it to 0xFF instead left the stream short of the element, and the
    # keyboard loops a track at its own stream end rather than at the
    # element's bar count: the track restarts inside the element and plays its
    # opening bar again, over beats that belong to the end of the pattern.
    #
    # Measured, not reasoned: PROBE52's percussion stream came to 2097 ticks
    # in a 2304-tick element, and a recording of it off the instrument had
    # extra hits at ticks 2097, 2193 and 2289 -- the track's first bar, 207
    # ticks early -- before the element boundary reset it.  Every onset in
    # that recording is accounted for by this and nothing else.
    #
    # 5817 non-empty factory tracks come to exactly bars * ticks_per_bar, and
    # the rest overrun it by a few ticks; none fall short the way ours did.
    gap = max(0, total_ticks - t)
    filler = evs[-1][2] if evs else 1        # note-off on a key: a no-op
    while gap > 0xFF:
        frames.append(Frame(0xFF, filler, 0))
        gap -= 0xFF
    frames.append(Frame(gap, END, 0))
    return frames


def clip_track(tr: Track, total_ticks):
    """Drop a track's frames past `total_ticks` and re-end it there.

    Only needed when an element is re-barred shorter than the template's: the
    control tracks are carried over verbatim, so a 7-bar intro cut to 2 bars
    would otherwise leave a stream running three times past the element.
    Factory rhythms overrun their elements by at most a few ticks, so bring
    ours back inside that range.  Frames within range, tone selection among
    them, are kept untouched.
    """
    kept, t = [], 0
    for f in tr.frames:
        if f.code == END:
            continue
        if t + f.dt > total_ticks:
            break
        t += f.dt
        kept.append(f)
    kept.append(Frame(max(0, min(0xFF, total_ticks - t)), END, 0))
    tr.frames = kept


def apply_rhythm(ac7: Ac7, rhythm, clear_unused=False):
    """Replace the template's note data with a converted rhythm.

    Every ELMT and MIXR byte is kept, so the template's tones, mixer settings
    and chord-conversion tables stay intact; only the notes change.  Each
    track keeps its own leading setup frames.
    """
    report = {"written": [], "skipped": [], "cleared": [], "dropped": [],
              "rebarred": []}
    tpb = ticks_per_bar(rhythm.numerator, rhythm.denominator)
    for el in ac7.elements:
        src = rhythm.elements.get(el.role)
        if src is None:
            if clear_unused:
                for tr in el.tracks:
                    tr.frames = encode_track([], tr.prefix(), el.bars * tpb)
                report["cleared"].append(el.role)
            else:
                report["skipped"].append(el.role)
            continue
        if src.bars != el.bars:
            report["rebarred"].append((el.role, el.bars, src.bars))
            set_bars(el, src.bars)
        total = el.bars * tpb
        for tr in el.tracks:
            if tr.role == "control":
                if tr.total_ticks() > total:
                    clip_track(tr, total)
                continue
            part = src.parts.get(tr.role)
            notes = ([(n.tick, n.dur, n.key, n.vel) for n in part.notes]
                     if part else [])
            tr.frames = encode_track(notes, tr.prefix(), total)
            report["written"].append((el.role, tr.role, len(notes)))
        for role, part in src.parts.items():
            if el.track(role) is None and part.notes:
                report["dropped"].append((el.role, role, len(part.notes)))
    return report


def set_bars(el: Element, bars):
    """Patch the element's bar count (TLV id 0x06) inside its raw chunk."""
    raw = bytearray(el.raw)
    o = 6
    while o < len(raw):
        pid, ln = raw[o], raw[o + 1]
        if pid == META:
            return False
        if pid == 0x06 and ln == 1:
            raw[o + 2] = max(1, min(255, int(bars)))
            el.raw = bytes(raw)
            el.bars = int(bars)
            return True
        o += 2 + ln
    return False


def set_name(ac7: Ac7, name):
    """Rewrite the 12-byte name in the file-level TLV stream."""
    fp = bytearray(ac7.file_params)
    o = 0
    while o < len(fp):
        pid, ln = fp[o], fp[o + 1]
        if pid == META:
            break
        if pid == 0x00 and ln >= 8:
            fp[o + 2:o + 2 + ln] = name.encode("ascii", "replace")[:ln].ljust(ln, b"\x00")
            ac7.file_params = bytes(fp)
            return True
        o += 2 + ln
    return False


def set_tempo(ac7: Ac7, bpm):
    fp = bytearray(ac7.file_params)
    o, hits = 0, 0
    while o < len(fp):
        pid, ln = fp[o], fp[o + 1]
        if pid == META:
            break
        if pid == 0x02 and ln == 1:
            fp[o + 2] = max(20, min(255, int(bpm)))
            hits += 1
        o += 2 + ln
    ac7.file_params = bytes(fp)
    return hits


# --------------------------------------------------------------------------
# MIXR -- one 6-byte mixer record per element and part
# --------------------------------------------------------------------------
# Decoded by reading the table against the three factory rhythms: the record
# is (program, bank, volume, pan, reverb, chorus), and the program/bank pair
# is a plain GM program with a bank MSB.  The bass column reads program 33
# (fingered bass), the chord columns 0/4/25/27/48 (piano, Rhodes, steel
# guitar, clean guitar, strings), and both drum columns carry bank 120.
#
# This matters because the drum tracks contain no program change at all, so
# the kit a converted rhythm plays is whatever its template assigned -- the
# note numbers alone do not decide the sound.

MIXR_FIELDS = ("program", "bank", "volume", "pan", "reverb", "chorus")
MIXR_PARTS = 8                  # parts 0-7 per element
DRUM_BANK = 120                 # bank MSB that selects a drum kit


def mixr_layout(ac7: Ac7):
    """(payload offset, record count) for the MIXR table, or None."""
    m = ac7.mixr
    if len(m) < 10 or m[:4] != b"MIXR":
        return None
    count = struct.unpack_from("<H", m, 8)[0]
    base = 10 + 4 * count
    if count == 0 or base + 6 * count > len(m):
        return None
    return base, count


def mixer_row(ac7: Ac7, element, part):
    """The six mixer bytes for one element and part, or None."""
    lay = mixr_layout(ac7)
    if lay is None:
        return None
    base, count = lay
    i = element * MIXR_PARTS + part
    if not 0 <= i < count:
        return None
    return tuple(ac7.mixr[base + 6 * i:base + 6 * i + 6])


def _part_index(role):
    return next((p for p, r in PART_ROLE.items()
                 if r == role and p < MIXR_PARTS), None)


def set_tone(ac7: Ac7, role, program, bank=None, elements=None):
    """Point one part at a different tone in every element.

    Returns the number of records rewritten.  `elements` limits the change to
    a set of element indices; by default every element is set, so the kit
    cannot vary between a variation and its fill.
    """
    lay = mixr_layout(ac7)
    part = _part_index(role)
    if lay is None or part is None:
        return 0
    base, count = lay
    m = bytearray(ac7.mixr)
    changed = 0
    for e in range(count // MIXR_PARTS):
        if elements is not None and e not in elements:
            continue
        o = base + 6 * (e * MIXR_PARTS + part)
        m[o] = max(0, min(127, int(program)))
        if bank is not None:
            m[o + 1] = max(0, min(127, int(bank)))
        changed += 1
    ac7.mixr = bytes(m)
    return changed


def set_mix(ac7: Ac7, role, elements=None, **fields):
    """Set any MIXR field on one part in every element.

    set_tone only writes program and bank, which is all a kit change needs.
    The remaining four columns matter too: a part inherits the template's
    volume, pan, reverb and chorus, and those were balanced for the template's
    own arrangement, not ours.  Baladi gives its percussion reverb 70 out of
    127, which is sensible when a full band plays over it and makes a solo
    hand-drum groove sound distant when it is the only thing sounding.

    Returns the number of records rewritten.  Unknown field names raise.
    """
    lay = mixr_layout(ac7)
    part = _part_index(role)
    if lay is None or part is None:
        return 0
    bad = set(fields) - set(MIXR_FIELDS)
    if bad:
        raise ValueError(f"no MIXR field called {sorted(bad)}; "
                         f"have {list(MIXR_FIELDS)}")
    base, count = lay
    m = bytearray(ac7.mixr)
    changed = 0
    for e in range(count // MIXR_PARTS):
        if elements is not None and e not in elements:
            continue
        o = base + 6 * (e * MIXR_PARTS + part)
        for name, v in fields.items():
            m[o + MIXR_FIELDS.index(name)] = max(0, min(127, int(v)))
        changed += 1
    ac7.mixr = bytes(m)
    return changed


def tone_summary(ac7: Ac7):
    """One line per part: the tones it uses across the elements."""
    lay = mixr_layout(ac7)
    if lay is None:
        return "no MIXR table"
    out = []
    for part in range(MIXR_PARTS):
        role = PART_ROLE.get(part, f"part{part}")
        seen = Counter()
        for e in range(len(ac7.elements)):
            row = mixer_row(ac7, e, part)
            if row:
                seen[(row[0], row[1])] += 1
        used = ", ".join(f"prog {p} bank {b} x{n}"
                         for (p, b), n in seen.most_common())
        out.append(f"  {role:<8} {used}")
    return "\n".join(out)


def set_meter(ac7: Ac7, num, den):
    """Write the time signature into the file header and every element.

    Returns (code, verified, patched) -- patched counts the TLV fields that
    were rewritten.  The streams themselves must already be written at this
    meter's bar length or the keyboard and the notes will disagree.
    """
    code, verified = meter_code(num, den)
    if code is None:
        return None, False, 0
    patched = 0

    fp = bytearray(ac7.file_params)
    o = 0
    while o < len(fp):
        pid, ln = fp[o], fp[o + 1]
        if pid == META:
            break
        if pid == 0x01 and ln == 1:
            fp[o + 2] = code
            patched += 1
        o += 2 + ln
    ac7.file_params = bytes(fp)

    for el in ac7.elements:
        raw = bytearray(el.raw)
        o = 6
        while o < len(raw):
            pid, ln = raw[o], raw[o + 1]
            if pid == META:
                break
            if pid == 0x01 and ln == 1:
                raw[o + 2] = code
                patched += 1
            o += 2 + ln
        el.raw = bytes(raw)
    return code, verified, patched


def _meter_line(a: Ac7):
    code, stored = a.meter_code, a.meter
    tpb = a.measured_ticks_per_bar()
    bits = []
    if code is not None:
        bits.append(f"{stored[0]}/{stored[1]}" if stored else "unrecognised")
        bits.append(f"(stored 0x{code:02x})")
    bits.append(f"- streams measure {describe_meter(tpb)}")
    if stored and tpb is not None and ticks_per_bar(*stored) != tpb:
        bits.append("<-- STORED METER AND STREAMS DISAGREE")
    return " ".join(bits)


def describe(ac7: Ac7):
    L = [f"name   : {ac7.name!r}", f"tempo  : {ac7.tempo} bpm",
         f"meter  : {_meter_line(ac7)}",
         f"elements: {len(ac7.elements)}   tracks: "
         f"{sum(len(e.tracks) for e in ac7.elements)}", "",
         "tones (from MIXR; the streams carry no program change):",
         tone_summary(ac7), "",
         f"{'element':<12} {'bars':>4}  tracks (role: notes)"]
    for el in ac7.elements:
        parts = []
        for tr in el.tracks:
            n = len(tr.notes())
            parts.append(f"{tr.role}:{n}" if n else f"{tr.role}:-")
        L.append(f"{el.role:<12} {el.bars:>4}  " + " ".join(parts))
    return "\n".join(L)


def file_params(a: Ac7):
    """File-level TLV parameters as a list of (id, occurrence, value)."""
    out, seen = [], Counter()
    for pid, val in read_tlv(a.file_params, 0, len(a.file_params))[0]:
        out.append((pid, seen[pid], val))
        seen[pid] += 1
    return out


def element_params(el: Element):
    """Element TLV parameters, skipping the bulky track-code and setup ids."""
    out, seen = [], Counter()
    for pid, val in read_tlv(el.raw, 6, len(el.raw))[0]:
        if pid in (0x20, 0x21, 0x36, 0x31, 0x32, 0x35):
            continue
        out.append((pid, seen[pid], val))
        seen[pid] += 1
    return out


def diff(a: Ac7, b: Ac7, name_a="A", name_b="B"):
    """Compare two rhythms field by field.

    Built to pin down parameters the format model still carries verbatim --
    export two factory rhythms that differ in one respect (say a 4/4 and a
    6/8) and the field that encodes it is the one that changes.
    """
    L, w = [], max(len(name_a), len(name_b), 6)
    L.append(f"{'field':<22} {name_a:>{w}}  {name_b:>{w}}")
    L.append("-" * (24 + 2 * w))

    def row(label, x, y, always=False):
        if always or x != y:
            L.append(f"{label:<22} {str(x):>{w}}  {str(y):>{w}}"
                     + ("" if x == y else "   <-- differs"))

    row("name", repr(a.name), repr(b.name), True)
    row("tempo", a.tempo, b.tempo, True)
    row("ticks/bar (measured)", a.measured_ticks_per_bar(),
        b.measured_ticks_per_bar(), True)
    row("elements", len(a.elements), len(b.elements), True)
    L.append("")
    L.append("file-level TLV parameters (id/occurrence):")
    pa = {(i, k): v for i, k, v in file_params(a)}
    pb = {(i, k): v for i, k, v in file_params(b)}
    for key in sorted(set(pa) | set(pb)):
        x, y = pa.get(key), pb.get(key)
        if x != y:
            L.append(f"  id 0x{key[0]:02x}[{key[1]}]"
                     f"{'':<10} {(x.hex() if x else '-'):>{w}}"
                     f"  {(y.hex() if y else '-'):>{w}}   <-- differs")
    L.append("")
    L.append("element TLV parameters:")
    for i in range(min(len(a.elements), len(b.elements))):
        ea, eb = a.elements[i], b.elements[i]
        qa = {(p, k): v for p, k, v in element_params(ea)}
        qb = {(p, k): v for p, k, v in element_params(eb)}
        for key in sorted(set(qa) | set(qb)):
            x, y = qa.get(key), qb.get(key)
            if x != y:
                L.append(f"  [{i:2d}] {ea.role:<11} id 0x{key[0]:02x}[{key[1]}]"
                         f"  {(x.hex() if x else '-')} -> {(y.hex() if y else '-')}")
    return "\n".join(L)


def to_midi_events(ac7: Ac7, layout=None):
    """Decode the whole rhythm to MIDI, elements laid end to end."""
    from .smf import Ev
    layout = layout or {"drum": 9, "perc": 9, "bass": 0, "chord1": 1,
                        "chord2": 2, "chord3": 3, "chord4": 4}
    evs, offset = [], 0
    if ac7.tempo:
        evs.append(Ev(0, "meta", meta=0x51,
                      data=int(60_000_000 / ac7.tempo).to_bytes(3, "big")))
    for el in ac7.elements:
        evs.append(Ev(offset, "meta", meta=0x06, data=el.role.encode()))
        for tr in el.tracks:
            ch = layout.get(tr.role)
            if ch is None:
                continue
            for tick, dur, key, vel in tr.notes():
                evs.append(Ev(offset + tick, "note_on", ch, key, vel))
                evs.append(Ev(offset + tick + dur, "note_off", ch, key, 0))
        offset += el.bars * 384
    return evs
