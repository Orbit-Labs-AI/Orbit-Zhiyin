"""Soundtrack for the Orbit promo (v17), synthesised from scratch on the film's beat grid (132 BPM, 88 beats = 40 s).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

Every time below is a film beat, the same numbers as STORYBOARD.md, the scenes and `render.mjs --only` (no SHIFT).
0-4 low bed + grain, a rising blip per Agent badge, a tap per word · 4-8.8 light four on the floor, typing ticks,
a pluck per prompt bubble, the app-icon burst (b6.8) · 8.8-12.4 a stab per word of We Are Redesigning Everything,
low-pass closes at b12 · 12.4-17.8 half time, dissonant correction blips getting denser, riser · b18.2 DROP on
「So，」 then We / Redesign / for everyone, shimmer as the ring closes · 21.6-26.4 ring -> spiral swell, an arpeggio
that speeds up with the spin, bell when the mark stands (b25) · 26.4-40 compass: ticks drawn, the bloom, b28 full
groove, a tick per analysis row (b33-36.6), reveal hit b37.8 · 40-55 recommendations: pluck + counter ticks per entry
(b42-52), second peak b52 · 55 merge (down sweep), half time, the click b63.2, generation typing, chime b67.6 ·
69.4-77 ring -> compass -> spiral again, riser, b77 the mark settles · b79 end-card chord (third peak), the five
opening blips again on 「every agent」 (b80.6), fade to silence by b88. The groove never stops between b4 and the end
card (the only gap is the pre-drop beat b17.8-18.2 the storyboard asks for); the three peaks are the loudest moments.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 132
BEAT = 60 / BPM
END = 88            # film beats (scenes/60-close.js sets the same END)
TAIL = 1.0          # seconds of silence after b88, so the mux never cuts a sample short
N = int((END * BEAT + TAIL) * SR)
rng = np.random.default_rng(7)
BUS = {}  # name -> (L, R), for sidechain and reverb sends


def bus(name):
    if name not in BUS:
        BUS[name] = (np.zeros(N), np.zeros(N))
    return BUS[name]


def at(b):
    return int(round(b * BEAT * SR))


def put(sig, b, gain=1.0, pan=0.0, to='dry'):
    l_, r_ = bus(to)
    i = at(b)
    if i >= N or i < 0:
        return
    s = sig[: N - i] * gain
    l_[i:i + len(s)] += s * np.sqrt(0.5 * (1 - pan))
    r_[i:i + len(s)] += s * np.sqrt(0.5 * (1 + pan))


def tt(dur):
    return np.arange(int(dur * SR)) / SR


def midi(m):
    return 440 * 2 ** ((m - 69) / 12)


def lp(x, f, o=2):
    return signal.sosfilt(signal.butter(o, f, 'low', fs=SR, output='sos'), x)


def hp(x, f, o=2):
    return signal.sosfilt(signal.butter(o, f, 'high', fs=SR, output='sos'), x)


def bp(x, lo, hi, o=2):
    return signal.sosfilt(signal.butter(o, [lo, hi], 'band', fs=SR, output='sos'), x)


def noise(d):
    return rng.standard_normal(int(d * SR))


def saw(f, t, detune=(0,), ph=0.0):
    out = np.zeros_like(t)
    for d in detune:
        ff = f * 2 ** (d / 1200)
        out += 2 * ((t * ff + ph + rng.random()) % 1) - 1
    return out / len(detune)


# ---------------- instruments ----------------
def kick(d=0.5, punch=1.0):
    t = tt(d)
    f = 46 + 120 * np.exp(-t * 38) * punch
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 6.5)
    click = hp(noise(d), 3000) * np.exp(-t * 400) * 0.35
    return np.tanh((body + click) * 1.6)


def clap():
    d = 0.35
    t = tt(d)
    n = bp(noise(d), 900, 2600)
    env = np.zeros_like(t)
    for k, o in enumerate((0, 0.011, 0.022)):
        env += (t >= o) * np.exp(-(t - o).clip(0) * (90 if k < 2 else 16))
    return n * env * 0.9


def snare(d=0.25, tone=1.0):
    t = tt(d)
    n = bp(noise(d), 1200, 7000) * np.exp(-t * 22)
    b = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30) * tone
    return (n * 0.8 + b * 0.5)


def hat(open_=False):
    d = 0.32 if open_ else 0.06
    t = tt(d)
    return hp(noise(d), 7500, 4) * np.exp(-t * (11 if open_ else 70)) * (0.5 if open_ else 0.38)


def blip(m, d=0.5):
    t = tt(d)
    f = midi(m)
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.12 * np.sin(2 * np.pi * 3 * f * t)
    return s * np.exp(-t * 9) * np.minimum(1, t * 600)


def pluck(m, d=0.35):
    t = tt(d)
    s = saw(midi(m), t, (-7, 7))
    return lp(s, 2600) * np.exp(-t * 11) * np.minimum(1, t * 400)


def bass_note(m, d):
    t = tt(d)
    s = saw(midi(m), t, (-5, 5)) + 0.6 * np.sin(2 * np.pi * midi(m) * t)
    env = np.minimum(1, t * 300) * np.exp(-t * 2.2) * np.clip((d - t) * 60, 0, 1)
    return lp(s, 520, 4) * env


def pad(ms, d, cutoff=1800, att=0.25):
    t = tt(d)
    s = sum(saw(midi(m), t, (-11, -4, 4, 11)) for m in ms) / len(ms)
    env = np.minimum(1, t / att) * np.clip((d - t) / 0.3, 0, 1)
    return lp(s, cutoff, 2) * env


def stab(ms, d=0.9):
    t = tt(d)
    s = sum(saw(midi(m), t, (-9, 0, 9)) for m in ms) / len(ms)
    return lp(s, 3200) * np.exp(-t * 4.5) * np.minimum(1, t * 500)


def boom(d=3.0, f0=62, f1=26):
    t = tt(d)
    f = f1 + (f0 - f1) * np.exp(-t * 3)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 1.3)
    hit = lp(noise(d), 900) * np.exp(-t * 9) * 0.8
    crack = hp(noise(d), 2500) * np.exp(-t * 30) * 0.5
    return np.tanh((body + hit + crack) * 1.4)


def crash(d=2.5):
    t = tt(d)
    return hp(noise(d), 5000, 2) * np.exp(-t * 1.6) * 0.5


def riser(d, f0=300, f1=4000):
    t = tt(d)
    p = t / d
    n = noise(d)
    # three bands crossfaded along the sweep approximate a rising band-pass
    lo, mid, hi = bp(n, f0, f0 * 3), bp(n, f0 * 3, f1 / 2), hp(n, f1 / 2)
    sw = np.where(p < .5, lo * (1 - 2 * p) + mid * 2 * p, mid * (2 - 2 * p) + hi * (2 * p - 1))
    f = f0 * (f1 / f0) ** p
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25
    return (sw * 0.9 + tone) * p ** 2.2


def whoosh(d=0.5):
    t = tt(d)
    p = t / d
    n = noise(d)
    env = np.sin(np.pi * p) ** 2
    return (bp(n, 400, 1600) * (1 - p) + hp(n, 2500) * p) * env * 0.8


def reverse_swell(d=1.0):
    t = tt(d)
    p = t / d
    return hp(noise(d), 3000) * p ** 3 * 0.6


def tick():
    t = tt(0.05)
    return hp(noise(0.05), 4000) * np.exp(-t * 120) * 0.6 + np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 90) * 0.3


# ---------------- extra instruments ----------------
def clack(m):
    """A click on a control: a dry wooden clack with a pitched body on top."""
    t = tt(0.4)
    hit = bp(noise(0.4), 1400, 5200) * np.exp(-t * 160) * 1.1
    thump = np.sin(2 * np.pi * 140 * t) * np.exp(-t * 40) * 0.7
    return hit + thump + blip(m, 0.4) * 0.9


def glide(f0, f1, d):
    t = tt(d)
    f = f0 * (f1 / f0) ** np.clip(t / d, 0, 1)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((d - t) * 3, 0, 1)


def key_click():
    """One typed character: a 2 ms click with a faint pitched body."""
    t = tt(0.03)
    return hp(noise(0.03), 3500) * np.exp(-t * 400) * 0.7 + np.sin(2 * np.pi * (1700 + 500 * rng.random()) * t) * np.exp(-t * 220) * 0.2


def pop(m):
    """A bubble pops out of a badge: a pluck with a short upward chirp in front."""
    t = tt(0.06)
    chirp = np.sin(2 * np.pi * np.cumsum(600 + 2400 * t / 0.06) / SR) * np.exp(-t * 60) * 0.35
    out = pluck(m, 0.4)
    out[:len(chirp)] += chirp
    return out


def fix_blip(m, d=0.4):
    """A correction prompt: a blip rubbing against the semitone above it (slightly out of tune)."""
    t = tt(d)
    a = np.sin(2 * np.pi * midi(m) * t) + 0.3 * np.sin(2 * np.pi * 2 * midi(m) * t)
    b = np.sin(2 * np.pi * midi(m + 1) * 1.004 * t)
    return (a + 0.65 * b) * np.exp(-t * 10) * np.minimum(1, t * 500)


def bell(m, d=2.6):
    t = tt(d)
    f = midi(m)
    s = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * k) for r, a, k in
            ((1, 1, 1.4), (2.0, .45, 2.2), (2.76, .3, 3.0), (5.4, .16, 5.0), (8.93, .06, 8.0)))
    return s * np.minimum(1, t * 300)


def whoosh_down(d=1.0):
    """The merge: band-limited noise that sweeps downwards and closes."""
    t = tt(d)
    p = t / d
    n = noise(d)
    hi, mid, lo = hp(n, 3500), bp(n, 900, 3500), bp(n, 150, 900)
    sw = np.where(p < .5, hi * (1 - 2 * p) + mid * 2 * p, mid * (2 - 2 * p) + lo * (2 * p - 1))
    return sw * np.sin(np.pi * p) ** 1.2 * 0.8


def sparkle(b0, dur, n, gain, lo=84, hi=100):
    """Granular glitter: n tiny high blips scattered over dur beats (seeded, so deterministic)."""
    for i in range(n):
        put(blip(int(lo + (hi - lo) * rng.random()), 0.12), b0 + dur * (i / n) ** 0.6 + 0.04 * rng.random(),
            gain * (0.5 + 0.5 * rng.random()), rng.random() * 1.6 - 0.8, to='verbsend')


def grain(b0, b1, n, gain):
    """The light grain under the opening: sparse dust clicks, a few with a low pitched body."""
    for _ in range(n):
        b = b0 + (b1 - b0) * rng.random()
        t = tt(0.04)
        s = hp(noise(0.04), 5000) * np.exp(-t * 300)
        if rng.random() < .3:
            s = s + np.sin(2 * np.pi * (180 + 120 * rng.random()) * t) * np.exp(-t * 80) * 0.5
        put(s, b, gain * (0.4 + 0.6 * rng.random()), rng.random() * 1.6 - 0.8, to='verbsend')


def typing(b0, n, dur, gain=0.11):
    """n characters typed evenly over dur beats (AGD.chat's c.type)."""
    for k in range(n):
        put(key_click(), b0 + dur * k / n, gain * (0.8 + 0.4 * rng.random()), 0.15 * (rng.random() - 0.5))


def counter(b0, dur=0.8, n=10, gain=0.16):
    """A number rolling over dur beats with E.out: ticks dense at first, then slower (inverse of 1 - (1 - p)^2)."""
    for k in range(n):
        put(tick(), b0 + dur * (1 - np.sqrt(1 - k / n)), gain * (1 - 0.6 * k / n), 0.45)


def accel_arp(b0, b1, notes, d0, d1, gain, to='verbsend'):
    """An arpeggio whose step shrinks from d0 to d1 beats (the spiral spins faster as it grows)."""
    b, i = b0, 0
    while b < b1 - 1e-9:
        p = (b - b0) / (b1 - b0)
        put(pluck(notes[i % len(notes)] + 12 * (i // len(notes) % 2), 0.3), b, gain * (0.7 + 0.5 * p), -0.5 + (i % 5) * 0.25, to=to)
        b += d0 + (d1 - d0) * p
        i += 1


def roll(b0, notes, gain, gap=0.09, d=0.9):
    """A rolled chord (petals opening)."""
    for i, n in enumerate(notes):
        put(pluck(n, d), b0 + i * gap, gain, -0.4 + 0.8 * i / max(1, len(notes) - 1), to='verbsend')


# ---------------- harmony ----------------
Am, F, C, G = (57, 60, 64), (53, 57, 60), (48, 52, 55, 60), (55, 59, 62)
Dm, E, Am9 = (50, 53, 57), (52, 56, 59), (57, 60, 64, 67, 71)
ROOT = {Am: 33, F: 29, C: 36, G: 31, Dm: 38, E: 28, Am9: 33}
# (film beat, chord): bar changes, plus the drop (b18.2) and the end card (b79) that land off the bar line
PROG = [(0, Am), (4, F), (8, C), (12, Dm), (16, E), (18.2, Am), (20, F), (24, C), (28, G), (32, Am), (36, F),
        (40, C), (44, G), (48, Am), (52, F), (56, C), (60, G), (64, Am), (68, F), (72, C), (76, G), (79, Am9)]
AG = (76, 79, 81, 84, 88)   # the five Agent badges cc / cx / gm / ds / cp: E5 G5 A5 C6 E6, opening and end card


def chord(b):
    c = PROG[0][1]
    for s, ch in PROG:
        if b + 1e-9 >= s:
            c = ch
    return c


def segments(b0, b1):
    """Split [b0, b1) at chord changes."""
    cuts = [b0] + [s for s, _ in PROG if b0 < s < b1] + [b1]
    return list(zip(cuts[:-1], cuts[1:]))


KICKS = {'four': (0, 1, 2, 3), 'half': (0, 2.5)}
CLAPS = {'four': (1, 3), 'half': (2,)}


def groove(b0, b1, kick_on=True, clap_on=True, hats=True, bassline=True, arp=False, lvl=1.0, style='four'):
    b = np.ceil(b0 * 4 - 1e-9) / 4      # start on the sixteenth grid so every groove lines up with the beat
    while b < b1 - 1e-9:
        bi = round(b * 4) / 4
        if kick_on and any(abs(bi % 4 - k) < 1e-6 for k in KICKS[style]):
            put(kick(), bi, 0.95 * lvl, to='kick')
        if clap_on and any(abs(bi % 4 - k) < 1e-6 for k in CLAPS[style]):
            put(clap(), bi, 0.55 * lvl, 0.0, to='verbsend')
        if hats:
            frac = bi % 1
            if abs(frac - .5) < 1e-6:
                put(hat(True), bi, 0.42 * lvl, 0.25)
            else:
                put(hat(False), bi, (0.32 if frac == 0 else 0.22) * lvl, -0.3)
        if bassline and abs(bi % 1 - .5) < 1e-6:
            put(bass_note(ROOT[chord(bi)] + (12 if bi % 4 in (1.5, 3.5) else 0), BEAT * 0.45), bi, 0.75 * lvl, to='duck')
        if arp:
            ch = chord(bi)
            seq = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[1] + 24]
            put(pluck(seq[int(bi * 4) % 4], BEAT * 0.4), bi, 0.16 * lvl, 0.35 if int(bi * 4) % 2 else -0.35, to='verbsend')
        b += 0.25


def pads(b0, b1, gain=0.2, cutoff=1800):
    for s, e in segments(b0, b1):
        put(pad(chord(s), (e - s) * BEAT + 0.25, cutoff), s, gain, to='duckverb')


def bed(b0, b1, gain=0.3, shakers=True):
    """Sustained sub bass per chord and eighth shakers, so the energy never dips in half time."""
    for s, e in segments(b0, b1):
        d = (e - s) * BEAT
        t = tt(d)
        r = ROOT[chord(s)] + 12
        x = (np.sin(2 * np.pi * midi(r) * t) + 0.3 * lp(saw(midi(r), t, (-6, 6)), 300)) * np.minimum(1, t * 20) * np.clip((d - t) * 20, 0, 1)
        put(x, s, gain, to='duck')
    if shakers:
        b = np.ceil(b0 * 2 - 1e-9) / 2
        while b < b1 - 1e-9:
            put(bp(noise(0.08), 5000, 11000) * np.exp(-tt(0.08) * 50), b, 0.22 if b % 1 else 0.14, 0.5)
            b += 0.5


def peak(b, ch, gain=1.0, crash_gain=1.0):
    """An energy peak: boom + kick + chord stab + crash; the groove that follows is laid by the caller."""
    put(boom(3.0, 58, 26), b, 0.62 * gain, to='verbsend')
    put(kick(0.6, 1.3), b, 1.0 * gain, to='kick')
    put(stab(tuple(ch) + (ch[0] - 12, ch[0] + 12), 2.2), b, 0.42 * gain, to='verbsend')
    put(crash(3.0), b, 0.42 * gain * crash_gain, 0.2)
    put(crash(2.5), b, 0.3 * gain * crash_gain, -0.3)


# ================= 1a  现在，每天无数人在使用 AI Agent (b0-4) =================
put(pad((45, 52, 57), 4.4 * BEAT, 520, 0.8), 0, 0.34, to='verbsend')        # low bed
put(bass_note(33, 4.2 * BEAT), 0, 0.42, to='duck')
grain(0, 4.2, 26, 0.09)
for i, m in enumerate(AG):                                                  # H0: badges pop every .25 beat
    put(blip(m, 0.5), 0.2 + 0.25 * i, 0.22, -0.6 + 0.3 * i, to='verbsend')
for b_ in (0.5, 0.9, 1.4, 1.9, 2.4):                                        # 现在， / 每天 / 无数人 / 在使用 / AI Agent
    put(kick(0.25, 0.5), b_, 0.3, to='kick')
    put(blip(57 if b_ < 2.4 else 64, 0.35), b_, 0.1, 0, to='verbsend')
put(whoosh(0.7 * BEAT), 3.5, 0.2, -0.2)                                     # the sentence leaves upwards
put(reverse_swell(0.6 * BEAT), 3.4, 0.4)

# ================= 1b  从想法到交付 (b4-8.8) =================
groove(4.0, 8.8, clap_on=False, lvl=0.72)
bed(4.0, 8.8, 0.22, shakers=False)
pads(4.0, 8.8, 0.14, 1200)
typing(4.4, 9, 0.55)                                                        # 做一个记账 App
typing(5.1, 5, 0.4)                                                         # 写份路演稿
typing(5.65, 6, 0.45)                                                       # 生成产品官网
BUBBLES = [(4.8, 1), (5.0, 0), (5.3, 2), (5.55, 2), (5.8, 3), (6.1, 4), (6.15, 4), (6.3, 0)]
for b_, i in BUBBLES:                                                       # sends + the badges' own prompts
    put(pop(AG[i] - 12), b_, 0.13, -0.6 + 0.3 * i, to='verbsend')
put(reverse_swell(0.6 * BEAT), 6.2, 0.45)                                   # b6.8 the app icons burst out
for k, m in enumerate((53, 57, 60, 64, 65, 69, 72, 76, 77, 81, 84, 88)):    # one note per icon, rising
    put(pluck(m + 12, 0.45), 6.8 + 0.07 * k, 0.12 + 0.004 * k, -0.6 + 0.11 * k, to='verbsend')
put(pad((65, 69, 72, 76), 1.6 * BEAT, 3200, 0.05), 6.8, 0.16, to='verbsend')

# ================= 1c  We Are Redesigning Everything (b8.6-12.6) =================
groove(8.8, 12.4, lvl=0.86)
pads(8.8, 12.4, 0.14, 1500)
put(whoosh(0.9 * BEAT), 8.3, 0.16, 0.3)                                     # badges retreat to the corners
for k, b_ in enumerate((8.8, 9.3, 9.8, 10.3)):                              # We / Are / Redesigning / Everything
    top = (67, 69, 72, 76)[k]
    put(stab((48, 55, 60, 64, top), 0.7 if k < 3 else 1.4), b_, 0.3 + 0.04 * k, -0.15 + 0.1 * k, to='verbsend')
    put(kick(0.4, 1.0), b_, 0.5 if k < 3 else 0.75, to='kick')
put(crash(2.0), 10.3, 0.22, 0.25)
put(whoosh(0.8 * BEAT), 11.8, 0.22, -0.2)                                   # icons fly outwards
LPF = [(11.4, 12.2, 12.4, 13.2, 420)]                                       # b12 low-pass closes, reopens under 1d

# ================= 1d  人与 AI 的协作，也值得被重新设计 (b12.4-17.8) =================
groove(12.4, 17.75, style='half', lvl=0.86)
bed(12.4, 17.75, 0.3)
pads(12.4, 17.75, 0.15, 1300)
typing(13.4, 4, 0.35)                                                       # 请你修改
typing(13.9, 3, 0.2)                                                        # fix
typing(14.25, 4, 0.3)                                                       # 请你继续
FIX = [(13.8, 1), (14.0, 2), (14.15, 3), (14.5, 4), (14.6, 0), (14.9, 3), (15.2, 0), (15.5, 1), (15.7, 2),
       (15.9, 4), (16.1, 3), (16.25, 0), (16.4, 1)]
for k, (b_, i) in enumerate(FIX):                                           # denser and a little louder each time
    put(fix_blip(AG[i] - 12 + (k // 5)), b_, 0.1 + 0.006 * k, -0.6 + 0.3 * i, to='verbsend')
for k in range(10):                                                         # bubbles retract, newest first
    put(blip(96 - k, 0.12), 16.8 + 0.07 * k, 0.05, 0.6 - 0.12 * k, to='verbsend')
put(riser(2.6 * BEAT, 300, 6000), 15.6, 0.36, to='verbsend')                # b15.6-18.2, alone in the gap
put(reverse_swell(0.6 * BEAT), 17.6, 0.6)

# ================= 1e  So，We Redesign for everyone (b17.8-22) — first peak =================
peak(18.2, Am, 1.15)
for k, b_ in enumerate((18.6, 19.0, 19.4)):                                 # We / Redesign / for everyone
    put(stab((57, 64, (67, 69, 72)[k], 76), 0.6), b_, 0.2, -0.2 + 0.2 * k, to='verbsend')
groove(18.5, 22.0, arp=True, lvl=1.08)                                      # hats on the and, full from b19
put(hat(True), 18.5, 0.3, 0.25)
pads(18.2, 22.0, 0.2, 2400)
sparkle(18.9, 0.9, 22, 0.06)                                                # the ring closes (dashed circle b19.2)

# ================= 2  ring -> spiral -> Orbit mark -> compass (b21.6-28.2) =================
put(reverse_swell(2.2 * BEAT), 21.6, 0.42)                                  # ring tightens into the spiral
put(glide(330, 330 * 2 ** 1.5, 2.2 * BEAT), 21.6, 0.07, to='verbsend')
put(pad((53, 57, 60, 64, 69), 2.6 * BEAT, 900, 1.6 * BEAT), 21.6, 0.14, to='verbsend')
groove(22.0, 26.4, clap_on=False, lvl=0.88)
pads(22.0, 26.4, 0.16, 1800)
accel_arp(22.4, 25.0, (65, 69, 72, 76, 72, 79, 84), 0.5, 0.11, 0.1)       # speeds up with the spin
put(bass_note(36, 1.0 * BEAT), 24.0, 0.4, to='duck')                        # bar line under the rise
put(bell(84, 2.8), 25.0, 0.2, 0.0, to='verbsend')                           # the mark stands (ICON)
put(bell(76, 2.8), 25.0, 0.12, -0.2, to='verbsend')
put(boom(2.0, 48, 30), 25.0, 0.26, to='verbsend')
put(whoosh(1.0 * BEAT), 26.4, 0.2, 0.2)                                     # the mark flips to the top view
for k in range(16):                                                         # dial ticks drawn clockwise
    put(tick(), 26.6 + 0.075 * k, 0.05 + 0.002 * k, -0.6 + 0.08 * k)
put(glide(3000, 9000, 1.0 * BEAT) * 0.6 + hp(noise(1.0 * BEAT), 8000) * 0.15, 27.4, 0.07, 0.3, to='verbsend')  # the trace

# ================= 3  compass: collaboration persona (b26.4-40.4) =================
groove(26.4, 28.0, style='half', clap_on=False, lvl=0.88)
put(reverse_swell(0.6 * BEAT), 27.4, 0.5)
put(kick(0.5, 1.2), 28.0, 0.7, to='kick')
groove(28.0, 39.4, arp=True, lvl=1.0)                                       # b28 groove fully open
pads(26.4, 40.0, 0.18, 2000)
roll(28.6, (67, 71, 74, 79, 83), 0.1)                                       # the bud lands on your type and blooms
put(crash(2.0), 28.0, 0.18, -0.2)
put(whoosh(1.2 * BEAT), 31.4, 0.14, -0.3)                                   # compass slides left
for k in range(16):                                                         # R1: 16 sectors light up in turn
    put(blip(84 + (k % 4) * 3, 0.1), 33.0 + 0.04 * k, 0.045, -0.6 + 0.08 * k, to='verbsend')
for k, b_ in enumerate((33.0, 33.9, 34.8, 35.7, 36.6)):                     # one tick per row on the centre line
    if k:
        for j in range(4):                                                  # split-flap rolls to the letter
            put(key_click(), b_ - 0.24 + 0.06 * j, 0.09, 0.35)
    put(tick(), b_, 0.3, 0.3)
    put(blip(79 + (0, 2, 4, 7, 9)[k], 0.3), b_, 0.12, 0.3, to='verbsend')   # 16 -> 8 -> 4 -> 2 -> 1
put(reverse_swell(0.5 * BEAT), 37.3, 0.45)
put(kick(0.5, 1.2), 37.8, 0.55, to='kick')                                  # reveal: DIMV
put(stab((57, 64, 69, 72, 76), 1.4), 37.8, 0.22, to='verbsend')
put(crash(2.0), 37.8, 0.16, 0.2)
roll(38.0, (69, 72, 76, 81), 0.07, 0.1)                                     # petals change to your ratios
put(whoosh(1.0 * BEAT), 39.3, 0.2, 0.3)                                     # badges leave the dial

# ================= 4  recommendations (b39.4-55.6) — second peak at b52 =================
groove(39.4, 54.2, arp=True, lvl=1.02)
pads(40.0, 55.0, 0.18, 2200)
put(blip(76, 0.4), 40.4, 0.08, 0.5, to='verbsend')                          # the two counters appear
put(blip(81, 0.4), 40.6, 0.08, 0.5, to='verbsend')
for n, b_ in enumerate((42, 44, 46, 48, 50, 52)):                           # each entry reaches the centre line
    ch = chord(b_)
    m = (ch[n % len(ch)] + 24) if n % 2 == 0 else (ch[-1] + 24)
    put(pluck(m, 0.6), b_, 0.17, -0.2, to='verbsend')
    put(glide(1200, 2400, 0.35 * BEAT), b_ - 0.05, 0.03, -0.5, to='verbsend')   # links drawn to the card
    counter(b_ + 0.05)
peak(52, (53, 57, 60, 64), 0.88, 0.6)                                        # last entry lands (light crash)
put(whoosh(1.0 * BEAT), 54.2, 0.18, 0.2)                                    # the list scrolls off

# ================= 5  session trajectory + studio (b55-70) =================
groove(54.2, 56.0, clap_on=False, lvl=0.8)
put(whoosh_down(1.3 * BEAT), 55.0, 0.36, 0.0)                               # five badges merge into one
groove(56.0, 69.4, style='half', arp=True, lvl=0.84)                        # half time from b56
bed(56.0, 69.4, 0.26)
pads(55.0, 70.0, 0.16, 1700)
put(whoosh(1.0 * BEAT), 61.6, 0.2, -0.3)                                    # trajectory out, studio in
put(clack(84), 63.2, 0.26, 0.2)                                             # click 开始生成
b_ = 63.4
while b_ < 67.5:                                                            # SKILL.md is written line by line
    put(key_click(), b_, 0.06 + 0.04 * rng.random(), 0.3 * (rng.random() - 0.5))
    b_ += 0.07 + 0.12 * rng.random()
for k in range(12):                                                         # pulses flow from the badge to the card
    put(blip(91, 0.1), 63.6 + k / 3, 0.03, -0.4 + 0.07 * k, to='verbsend')
for m, g in ((81, 0.16), (88, 0.12), (93, 0.08)):                          # ✓ done
    put(bell(m, 2.0), 67.6, g, 0.1, to='verbsend')
put(whoosh(1.2 * BEAT), 68.2, 0.16, 0.2)                                    # the studio card leaves

# ================= 6  ring -> compass -> spiral again (b69.4-77.4) =================
put(whoosh(1.0 * BEAT), 69.4, 0.2, -0.2)                                    # the merged badge splits into a ring
sparkle(69.8, 1.4, 18, 0.05)
groove(69.4, 74.4, style='half', clap_on=False, lvl=0.72)
bed(69.4, 77.0, 0.22)
pads(69.4, 79.0, 0.2, 1600)
roll(71.4, (60, 64, 67, 72, 76), 0.08, 0.12)                                # the ring unfolds into the compass
roll(72.6, (69, 72, 76, 81), 0.06, 0.1)                                     # your type's flower
put(reverse_swell(1.2 * BEAT), 73.2, 0.3)                                   # it folds back into the ring
groove(74.4, 77.0, kick_on=False, clap_on=False, lvl=0.7)                   # groove thins out, pulse stays
accel_arp(74.4, 76.4, (67, 71, 74, 79, 74, 83, 86), 0.5, 0.12, 0.09)      # the spiral grows (as at b22.4)
put(riser(2.4 * BEAT, 300, 5000), 74.6, 0.26, to='verbsend')
put(boom(2.4, 50, 28), 77.0, 0.3, to='verbsend')                            # the mark settles
put(stab((55, 62, 67, 71), 1.6), 77.0, 0.2, to='verbsend')
put(glide(440, 660, 1.4 * BEAT), 77.8, 0.05, to='verbsend')                 # the mark moves up
groove(77.0, 78.75, style='half', clap_on=False, lvl=0.72)
put(reverse_swell(0.7 * BEAT), 78.3, 0.5)

# ================= 7  end card (b79-88) — third peak =================
peak(79.0, Am9, 1.0, 0.8)
put(pad(Am9, (END - 79) * BEAT, 1500, 0.3), 79.0, 0.26, to='verbsend')
groove(79.5, END, arp=True, lvl=0.78)                                       # groove runs under the end card
bed(79.0, END, 0.2)
for i, m in enumerate(AG):                                                  # 「every agent」: the opening blips
    put(blip(m, 0.7), 80.6 + 0.1 * i, 0.2, -0.6 + 0.3 * i, to='verbsend')
FADE = (86.0, 88.0)                                                         # everything decays to 0 by b88

# ---------------- mix ----------------
kl = bus('kick')[0]
kenv = np.abs(signal.hilbert(lp(kl, 120)))
duck = 1 - 0.75 * np.clip(lp(kenv, 12, 1) * 2.2, 0, 1)

ir_t = tt(2.4)
ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 2.6)
ir = lp(ir, 6000)
ir /= np.sqrt(np.sum(ir ** 2))

out_l = bus('dry')[0] + bus('kick')[0] + bus('verbsend')[0] + (bus('duck')[0] + bus('duckverb')[0]) * duck
out_r = bus('dry')[1] + bus('kick')[1] + bus('verbsend')[1] + (bus('duck')[1] + bus('duckverb')[1]) * duck
send_l = bus('verbsend')[0] + bus('duckverb')[0] * duck
send_r = bus('verbsend')[1] + bus('duckverb')[1] * duck
out_l += signal.fftconvolve(send_l, ir)[:N] * 0.3
out_r += signal.fftconvolve(send_r, np.roll(ir, 211))[:N] * 0.3

mix = np.stack([out_l, out_r])
for b0, b1, b2, b3, fc in LPF:                      # low-pass automation: zero-phase copy, crossfaded in and out
    w = np.interp(np.arange(N), [at(b0), at(b1), at(b2), at(b3)], [0, 1, 1, 0], left=0, right=0)
    sos = signal.butter(2, fc, 'low', fs=SR, output='sos')
    mix = mix * (1 - 0.85 * w) + signal.sosfiltfilt(sos, mix) * 0.85 * w
mix = hp(mix, 25)
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.8) / np.tanh(1.8)
p = np.clip((np.arange(N) - at(FADE[0])) / (at(FADE[1]) - at(FADE[0])), 0, 1)
mix *= 0.5 * (1 + np.cos(np.pi * p)) * 0.82      # cosine fade to exactly 0 at b88, silence in the tail

os.makedirs(os.path.join(os.path.dirname(__file__), 'out'), exist_ok=True)
path = os.path.join(os.path.dirname(__file__), 'out', 'soundtrack.wav')
with wave.open(path, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype('<i2').tobytes())
print('wrote', path, f'{N / SR:.2f}s ({END} beats = {END * BEAT:.2f}s + {TAIL}s tail), peak {np.max(np.abs(mix)):.3f}')
