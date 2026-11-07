"""Yamaha style file (.sty/.prs/.bcs/.pcs/.sst) parser."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .smf import Ev, iter_chunks, read_track

SETUP_MARKERS = {"SFF1", "SFF2", "SInt"}

# 0-based MIDI channel -> Yamaha style part role
YAMAHA_CHANNELS = {
    8:  "rhythm_sub",
    9:  "rhythm_main",
    10: "bass",
    11: "chord1",
    12: "chord2",
    13: "pad",
    14: "phrase1",
    15: "phrase2",
}


@dataclass
class Section:
    name: str
    start: int
    end: int


@dataclass
class Ctab:
    section: str
    src_channel: int
    name: str
    raw: bytes


@dataclass
class Style:
    path: str
    division: int = 480
    events: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    ctabs: list = field(default_factory=list)
    tempo_bpm: float = 120.0
    numerator: int = 4
    denominator: int = 4
    sff_version: str = ""

    @property
    def ticks_per_bar(self):
        return int(self.division * 4 * self.numerator / self.denominator)

    def section(self, name):
        for s in self.sections:
            if s.name == name:
                return s
        return None


def _parse_casm(body, out):
    """Walk CASM -> CSEG -> {Sdec, Ctb2/Ctab, Cntt} and collect chord tables."""
    for tag, _, seg in iter_chunks(body):
        if tag != "CSEG":
            continue
        sections = []
        for stag, _, sbody in iter_chunks(seg):
            if stag == "Sdec":
                sections = [s.strip() for s in
                            sbody.decode("latin-1").split(",") if s.strip()]
            elif stag in ("Ctb2", "Ctab"):
                if len(sbody) < 9:
                    continue
                src = sbody[0]
                nm = sbody[1:9].decode("latin-1").rstrip("\x00 ")
                for sec in (sections or ["?"]):
                    out.append(Ctab(sec, src, nm, sbody))


def parse(path) -> Style:
    with open(path, "rb") as f:
        data = f.read()

    st = Style(path=path)
    for tag, _, body in iter_chunks(data):
        if tag == "MThd":
            _, _, div = struct.unpack(">HHH", body[:6])
            st.division = div
        elif tag == "MTrk":
            st.events.extend(read_track(body))
        elif tag == "CASM":
            _parse_casm(body, st.ctabs)

    st.events.sort(key=lambda e: e.tick)

    markers = []
    for e in st.events:
        if e.kind != "meta":
            continue
        if e.meta == 0x06:                                    # marker
            name = e.data.decode("latin-1").strip()
            if name.startswith("SFF"):
                st.sff_version = name
            markers.append((e.tick, name))
        elif e.meta == 0x51 and e.tick == 0:                  # tempo
            us = int.from_bytes(e.data, "big")
            if us:
                st.tempo_bpm = round(60_000_000 / us, 2)
        elif e.meta == 0x58 and e.tick == 0:                  # time signature
            st.numerator, st.denominator = e.data[0], 1 << e.data[1]

    end = max((e.tick for e in st.events), default=0)
    for i, (tick, name) in enumerate(markers):
        stop = markers[i + 1][0] if i + 1 < len(markers) else end
        st.sections.append(Section(name, tick, stop))
    return st


def musical_sections(st: Style):
    return [s for s in st.sections
            if s.name not in SETUP_MARKERS and s.end > s.start]


def setup_events(st: Style):
    """Events from the SInt (setup) section: program changes, volume, pan..."""
    sec = st.section("SInt")
    if sec is None:
        return [e for e in st.events if e.tick == 0 and e.kind in ("pc", "cc")]
    return [e for e in st.events if sec.start <= e.tick < sec.end
            and e.kind in ("pc", "cc")]
