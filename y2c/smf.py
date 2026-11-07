"""Minimal Standard MIDI File I/O -- enough for Yamaha style files.

Yamaha .sty/.prs/.bcs files are Standard MIDI Files (format 0) with extra
chunks appended after the MTrk (CASM, OTSc, MDBs, FNRc, GUID...).  Every
chunk uses the same header: 4-byte ASCII tag + 4-byte big-endian length.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class Ev:
    tick: int
    kind: str            # note_on note_off cc pc at cat pb meta sysex
    ch: int = -1
    a: int = 0
    b: int = 0
    meta: int = -1
    data: bytes = b""


def read_vlq(buf, i):
    v = 0
    while True:
        b = buf[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def write_vlq(v):
    out = bytearray([v & 0x7F])
    v >>= 7
    while v:
        out.append(0x80 | (v & 0x7F))
        v >>= 7
    out.reverse()
    return bytes(out)


def iter_chunks(data, start=0):
    """Yield (tag, offset, body) for each top-level chunk."""
    i = start
    while i + 8 <= len(data):
        tag = data[i:i + 4].decode("latin-1")
        size = struct.unpack(">I", data[i + 4:i + 8])[0]
        if size > len(data):
            break
        yield tag, i, data[i + 8:i + 8 + size]
        i += 8 + size


def read_track(body):
    """Decode one MTrk body into a list of Ev, absolute ticks."""
    evs, i, tick, running = [], 0, 0, None
    n = len(body)
    while i < n:
        d, i = read_vlq(body, i)
        tick += d
        st = body[i]
        if st < 0x80:
            if running is None:
                raise ValueError("running status with no prior status byte")
        else:
            i += 1
            running = st if st < 0xF0 else None
        if st == 0xFF:
            mt = body[i]
            i += 1
            ln, i = read_vlq(body, i)
            evs.append(Ev(tick, "meta", meta=mt, data=body[i:i + ln]))
            i += ln
            if mt == 0x2F:
                break
        elif st in (0xF0, 0xF7):
            ln, i = read_vlq(body, i)
            evs.append(Ev(tick, "sysex", a=st, data=body[i:i + ln]))
            i += ln
        else:
            hi, ch = st & 0xF0, st & 0x0F
            if hi in (0xC0, 0xD0):
                evs.append(Ev(tick, "pc" if hi == 0xC0 else "cat", ch, body[i]))
                i += 1
            else:
                a, b = body[i], body[i + 1]
                i += 2
                if hi == 0x90 and b == 0:
                    hi = 0x80
                kind = {0x80: "note_off", 0x90: "note_on", 0xA0: "at",
                        0xB0: "cc", 0xE0: "pb"}[hi]
                evs.append(Ev(tick, kind, ch, a, b))
    return evs


_STATUS = {"note_off": 0x80, "note_on": 0x90, "at": 0xA0,
           "cc": 0xB0, "pc": 0xC0, "cat": 0xD0, "pb": 0xE0}


def _ev_bytes(e):
    if e.kind == "meta":
        return bytes([0xFF, e.meta]) + write_vlq(len(e.data)) + e.data
    if e.kind == "sysex":
        return bytes([e.a]) + write_vlq(len(e.data)) + e.data
    m = _STATUS[e.kind]
    if m in (0xC0, 0xD0):
        return bytes([m | e.ch, e.a])
    return bytes([m | e.ch, e.a, e.b])


def write_smf(path, division, tracks):
    fmt = 1 if len(tracks) > 1 else 0
    out = bytearray(b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), division))
    for evs in tracks:
        body, last = bytearray(), 0
        order = {"note_off": 0, "meta": 1, "cc": 1, "pc": 1}
        for e in sorted(evs, key=lambda x: (x.tick, order.get(x.kind, 2))):
            if e.kind == "meta" and e.meta == 0x2F:
                continue
            body += write_vlq(e.tick - last)
            last = e.tick
            body += _ev_bytes(e)
        body += write_vlq(0) + b"\xff\x2f\x00"
        out += b"MTrk" + struct.pack(">I", len(body)) + body
    with open(path, "wb") as f:
        f.write(bytes(out))
