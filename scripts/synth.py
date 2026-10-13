"""A tiny procedural music synthesizer for seed data.

Every track is generated from a seed: chord progression, melody, bass and drums are synthesized
from scratch with numpy, so the audio is original and free of third-party rights (CC0).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import soundfile as sf

SR = 22_050
SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11], "dorian": [0, 2, 3, 5, 7, 9, 10]}
PROGRESSIONS = {"minor": [[0, 5, 2, 6], [0, 3, 4, 0], [0, 5, 3, 4]], "major": [[0, 4, 5, 3], [0, 5, 3, 4], [0, 3, 0, 4]],
                "dorian": [[0, 3, 0, 3], [0, 6, 3, 0]]}


@dataclass(frozen=True)
class Style:
    bpm: tuple[int, int]
    scale: str
    drums: str | None  # "boom_bap" | "four" | "backbeat" | "chip" | None
    lead: str  # "keys" | "saw" | "square" | "bell"
    pad: str  # "warm" | "saw" | "square" | "air"
    swing: float = 0.0
    crackle: bool = False
    cutoff: float = 0.25


STYLES = {
    "lofi": Style((72, 86), "dorian", "boom_bap", "keys", "warm", swing=0.18, crackle=True, cutoff=0.12),
    "synthwave": Style((96, 110), "minor", "backbeat", "saw", "saw", cutoff=0.22),
    "ambient": Style((56, 68), "major", None, "bell", "air", cutoff=0.1),
    "chiptune": Style((128, 148), "major", "chip", "square", "square", cutoff=0.6),
    "house": Style((120, 124), "minor", "four", "keys", "warm", cutoff=0.3),
    "downtempo": Style((88, 96), "minor", "boom_bap", "bell", "warm", swing=0.08, cutoff=0.15),
}


def midi_hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    env = np.ones(n)
    env[: min(a, n)] = np.linspace(0, 1, min(a, n))
    if r < n:
        env[-r:] *= np.linspace(1, 0, r)
    return env


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """Windowed-sinc FIR lowpass; `cutoff` is a fraction of Nyquist."""
    taps = 101
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(cutoff * n) * np.hanning(taps)
    return np.convolve(x, kernel / kernel.sum(), mode="same")


def _osc(kind: str, freq: float, n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / SR
    phase = (freq * t) % 1.0
    match kind:
        case "sine":
            return np.sin(2 * np.pi * freq * t)
        case "saw":
            detune = 1.006
            return (2 * phase - 1) * 0.5 + (2 * ((freq * detune * t) % 1.0) - 1) * 0.5
        case "square":
            return np.where(phase < 0.5, 1.0, -1.0) * 0.6
        case "keys":  # electric-piano-ish: sine with decaying harmonics
            decay = np.exp(-t * 3.5)
            return np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t) * decay + 0.1 * np.sin(6 * np.pi * freq * t) * decay
        case "bell":
            return (np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-t * 4)) * np.exp(-t * 2.2)
        case _:
            return np.sin(2 * np.pi * freq * t)


class Track:
    def __init__(self, seconds: float) -> None:
        self.buf = np.zeros(int(seconds * SR) + SR)

    def add(self, start_s: float, signal: np.ndarray, gain: float) -> None:
        i = int(start_s * SR)
        if i >= len(self.buf):
            return
        end = min(len(self.buf), i + len(signal))
        self.buf[i:end] += signal[: end - i] * gain


def _kick(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    freq = 45 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 9)


def _snare(n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / SR
    noise = rng.standard_normal(n) * np.exp(-t * 18)
    return noise * 0.7 + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25) * 0.5


def _hat(n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    return np.diff(noise, prepend=0) * np.exp(-t * 70) * 0.5


def render(style_name: str, seed: int, seconds: float = 40.0) -> np.ndarray:
    style = STYLES[style_name]
    rng = np.random.default_rng(seed)
    bpm = int(rng.integers(*style.bpm))
    beat = 60 / bpm
    bar = beat * 4
    root = int(rng.integers(45, 53))  # A2..C#3
    scale = SCALES[style.scale]
    progression = PROGRESSIONS[style.scale][int(rng.integers(len(PROGRESSIONS[style.scale])))]
    bars = int(seconds / bar)
    track = Track(bars * bar)

    def degree(d: int, octave: int = 0) -> int:
        return root + scale[d % 7] + 12 * (d // 7 + octave)

    pad_kind = {"warm": "keys", "saw": "saw", "square": "square", "air": "sine"}[style.pad]
    lead_kind = {"keys": "keys", "saw": "saw", "square": "square", "bell": "bell"}[style.lead]
    motif = [int(x) for x in rng.choice([0, 1, 2, 3, 4, 5, 6, 7, 9], size=8)]
    motif_rhythm = rng.choice([0.5, 0.5, 1.0, 0.25, 1.5], size=8)

    for b in range(bars):
        t0 = b * bar
        chord_root = progression[b % len(progression)]
        section_energy = 0.6 if b < 2 or b >= bars - 2 else 1.0
        # pad / chord
        chord = [degree(chord_root + i, 1) for i in (0, 2, 4)]
        n = int(bar * SR)
        if style.pad == "air":
            n = int(bar * 1.6 * SR)
        for note in chord:
            sig = _osc(pad_kind, midi_hz(note), n, rng) * _env(n, 0.3 if style.pad == "air" else 0.02, 0.4)
            track.add(t0, sig, 0.10 * section_energy)
        # bass
        for step in range(4 if style.drums != "chip" else 8):
            length = beat if style.drums != "chip" else beat / 2
            note = degree(chord_root, -1) + (12 if style.drums == "chip" and step % 2 else 0)
            m = int(length * 0.9 * SR)
            kind = "square" if style.drums == "chip" else ("saw" if style_name == "synthwave" else "sine")
            track.add(t0 + step * length, _osc(kind, midi_hz(note), m, rng) * _env(m, 0.005, 0.05), 0.22)
        # lead melody (skip the intro bar)
        if b >= 1 and b < bars - 1:
            pos = 0.0
            for i, (d, r) in enumerate(zip(motif, motif_rhythm, strict=True)):
                if pos >= 4:
                    break
                variation = int(rng.integers(-1, 2)) if b % 4 == 3 else 0
                note = degree(chord_root + d + variation, 2 if style.lead == "bell" else 1)
                swing = style.swing * beat if (i % 2 and r == 0.5) else 0
                m = int(min(r, 4 - pos) * beat * SR)
                track.add(t0 + pos * beat + swing, _osc(lead_kind, midi_hz(note), m, rng) * _env(m, 0.01, 0.08), 0.13)
                pos += float(r)
        # drums
        hit = int(0.35 * SR)
        if style.drums and b >= 1:
            for step in range(16):
                ts = t0 + step * beat / 4 + (style.swing * beat / 4 if step % 2 else 0)
                if style.drums == "four":
                    if step % 4 == 0:
                        track.add(ts, _kick(hit), 0.55)
                    if step % 4 == 2:
                        track.add(ts, _hat(hit, rng), 0.35)
                    if step in (4, 12):
                        track.add(ts, _snare(hit, rng), 0.25)
                elif style.drums == "chip":
                    if step % 4 == 0:
                        track.add(ts, _kick(int(0.15 * SR)), 0.4)
                    if step in (4, 12):
                        track.add(ts, _hat(hit, rng) * 3, 0.2)
                    if step % 2:
                        track.add(ts, _hat(int(0.05 * SR), rng), 0.15)
                else:
                    if step in (0, 10) or (style.drums == "backbeat" and step == 8):
                        track.add(ts, _kick(hit), 0.5)
                    if step in (4, 12):
                        track.add(ts, _snare(hit, rng), 0.35)
                    if step % 2 == 0:
                        track.add(ts, _hat(int(0.08 * SR), rng), 0.18)

    out = track.buf[: int(bars * bar * SR)]
    out = _lowpass(out, min(0.95, style.cutoff * 2.5))
    # simple stereo space: delayed, quieter copies
    left = out.copy()
    right = out.copy()
    for delay, g in ((0.031, 0.25), (0.067, 0.18), (beat * 0.75, 0.12)):
        d = int(delay * SR)
        right[d:] += out[:-d] * g
        left[int(d * 1.3):] += out[: -int(d * 1.3)] * g * 0.8
    stereo = np.stack([left, right], axis=1)
    if style.crackle:
        crackle = (rng.random(stereo.shape[0]) > 0.9993) * rng.standard_normal(stereo.shape[0]) * 0.15
        stereo += crackle[:, None]
    fade = int(1.5 * SR)
    stereo[:fade] *= np.linspace(0, 1, fade)[:, None]
    stereo[-fade * 2:] *= np.linspace(1, 0, fade * 2)[:, None]
    peak = np.max(np.abs(stereo)) or 1.0
    return (stereo / peak * 0.89).astype(np.float32)


def encode_ogg(samples: np.ndarray) -> bytes:
    # libsndfile's Vorbis encoder can crash on very large single writes, so feed it in blocks.
    buf = io.BytesIO()
    with sf.SoundFile(buf, "w", SR, samples.shape[1], format="OGG", subtype="VORBIS") as out:
        for start in range(0, len(samples), 8192):
            out.write(samples[start:start + 8192])
    return buf.getvalue()


def cover_svg(title: str, palette: tuple[str, str, str], motif: str, seed: int) -> str:
    rng = np.random.default_rng(seed)
    a, b, c = palette
    shapes = []
    if motif == "sun":
        shapes.append('<circle cx="256" cy="230" r="120" fill="url(#s)"/>')
        shapes += [f'<rect x="120" y="{250 + i * 18}" width="272" height="{4 + i}" fill="{a}"/>' for i in range(6)]
        shapes += [f'<line x1="{x}" y1="512" x2="256" y2="340" stroke="{c}" stroke-opacity=".5"/>' for x in range(-200, 720, 64)]
    elif motif == "waves":
        for i in range(7):
            y = 140 + i * 45
            amp = 20 + rng.integers(0, 30)
            shapes.append(f'<path d="M0 {y} Q128 {y - amp} 256 {y} T512 {y}" stroke="{c}" stroke-width="3" '
                          f'fill="none" opacity="{0.25 + i * 0.1:.2f}"/>')
    elif motif == "grid":
        for _ in range(28):
            x, y = (int(v) for v in rng.integers(0, 16, 2))
            shapes.append(f'<rect x="{x * 32}" y="{y * 32}" width="32" height="32" fill="{c}" opacity=".7"/>')
    else:  # orbs
        for _ in range(9):
            x, y, r = int(rng.integers(40, 470)), int(rng.integers(40, 470)), int(rng.integers(20, 110))
            shapes.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" opacity="{rng.uniform(.15, .5):.2f}"/>')
    safe = title.replace("&", "&amp;").replace("<", "&lt;")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/>'
        f'<stop offset="1" stop-color="{b}"/></linearGradient><linearGradient id="s" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{c}"/><stop offset="1" stop-color="{a}"/></linearGradient></defs>'
        '<rect width="512" height="512" fill="url(#g)"/>' + "".join(shapes) +
        f'<text x="32" y="476" font-family="Helvetica, Arial, sans-serif" font-size="34" font-weight="700" '
        f'fill="#fff" fill-opacity=".92">{safe}</text></svg>'
    )


def avatar_svg(name: str, palette: tuple[str, str, str]) -> str:
    a, b, c = palette
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
        f'<defs><radialGradient id="g" cx=".3" cy=".3" r=".9"><stop offset="0" stop-color="{c}"/>'
        f'<stop offset=".6" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></radialGradient></defs>'
        '<rect width="512" height="512" fill="url(#g)"/>'
        f'<text x="256" y="300" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="150" '
        f'font-weight="800" fill="#fff" fill-opacity=".9">{initials}</text></svg>'
    )
