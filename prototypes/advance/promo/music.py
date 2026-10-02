"""Soundtrack for the Orbit promo, synthesised from scratch on the same beat grid as promo.js (124 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

Sections (beats), v7, same grid as promo.js and the 声音 table in STORYBOARD.md: 0-3.4 open (a blip per word,
odometer, five chips) · 3.4-7.9 half time, highlighter, sentence swap · 7.9-14.6 the mark is traced and we dive ·
14.6-21.6 groove A under the sentiment ride, push-through riser · 21.2-28 numbers (ratchets) and particles ·
28-44 half time, a tick + scale note per type the needle passes (sweep_at = sweepAt in scenes/30-persona.js),
four locks at 37.6/39.1/40.6/42.1, riser + snare roll · 44 DROP, full groove to 52 · 53-57.4 checks, warnings,
the click and the portal · 57.4-63.4 conveyor, 63.4 landing chord · 64-77 install, 7 days, before/after ·
79.4 DROP · 83.4-101 groove B montage · 101-113 half time close, 107.6 end card, tail 1.5 s.
The groove never stops between b3.4 and b101; the two drops are the loudest moments.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 124
BEAT = 60 / BPM
END = 113
N = int((END * BEAT + 1.5) * SR)
rng = np.random.default_rng(7)
L = np.zeros(N)
R = np.zeros(N)
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
    if i >= N:
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


# ---------------- extra instruments (v7) ----------------
def clack(m):
    """A lock: a dry wooden clack with a pitched body on top."""
    t = tt(0.4)
    hit = bp(noise(0.4), 1400, 5200) * np.exp(-t * 160) * 1.1
    thump = np.sin(2 * np.pi * 140 * t) * np.exp(-t * 40) * 0.7
    tone = blip(m, 0.4) * 0.9
    return hit + thump + tone


def scratch(d=0.3):
    """A strike-through: a short band-limited noise swipe that brightens as it goes."""
    t = tt(d)
    p = t / d
    n = noise(d)
    return (bp(n, 1500, 4000) * (1 - p) + hp(n, 4000) * p) * np.sin(np.pi * p) ** 0.7 * 0.7


def marker(d=0.35):
    """The highlighter: a soft felt-tip swish."""
    t = tt(d)
    p = t / d
    return bp(noise(d), 2200, 6500) * (p ** 0.4) * np.clip((1 - p) * 6, 0, 1) * 0.6


def slide(m0, m1, d):
    """A pitch glide from m0 to m1 (exponential in pitch), soft attack, short release."""
    t = tt(d)
    p = np.clip(t / d, 0, 1)
    f = midi(m0) * (midi(m1) / midi(m0)) ** (p ** 0.7)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) + 0.3 * np.sin(2 * ph)
    return s * np.minimum(1, t * 60) * np.clip((d - t) * 8, 0, 1)


def glide(f0, f1, d):
    t = tt(d)
    f = f0 * (f1 / f0) ** np.clip(t / d, 0, 1)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((d - t) * 3, 0, 1)


def sparkle(b0, dur, n, gain, lo=84, hi=100):
    """Granular glitter: n tiny high blips scattered over dur beats (seeded, so deterministic)."""
    for i in range(n):
        put(blip(int(lo + (hi - lo) * rng.random()), 0.12), b0 + dur * (i / n) ** 0.6 + 0.04 * rng.random(),
            gain * (0.5 + 0.5 * rng.random()), rng.random() * 1.6 - 0.8, to='verbsend')


def hats16(b0, b1, lvl=1.0):
    """Sixteenth closed hats on top of a groove (groove B)."""
    b = b0
    while b < b1 - 1e-9:
        if abs((b % 0.5) - 0.25) < 1e-6:
            put(hat(False), b, 0.16 * lvl, 0.4)
        b += 0.25


# ---------------- arrangement ----------------
A, C_, E_, F_, G_ = 57, 60, 64, 53, 55  # A3 C4 E4 F3 G3
CHORDS = [(57, 60, 64), (53, 57, 60), (48, 52, 55, 60), (55, 59, 62)]  # Am F C G
ROOTS = [33, 29, 36, 31]  # A1 F1 C2 G1


def chord_at(b):
    return int((b // 4) % 4)


KICKS = {'four': (0, 1, 2, 3), 'half': (0, 2.5), 'broken': (0, 1.75, 2.5)}
CLAPS = {'four': (1, 3), 'half': (2,), 'broken': (1, 3)}


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
            put(bass_note(ROOTS[chord_at(bi)] + (12 if bi % 4 in (1.5, 3.5) else 0), BEAT * 0.45), bi, 0.75 * lvl, to='duck')
        if arp:
            ch = CHORDS[chord_at(bi)]
            seq = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[1] + 24]
            put(pluck(seq[int(bi * 4) % 4], BEAT * 0.4), bi, 0.16 * lvl, 0.35 if int(bi * 4) % 2 else -0.35, to='verbsend')
        b += 0.25


def pads(b0, b1, gain=0.22, cutoff=1800):
    b = b0
    while b < b1 - 1e-9:
        nb = min(b1, (b // 4 + 1) * 4)
        put(pad(CHORDS[chord_at(b)], (nb - b) * BEAT + 0.25, cutoff), b, gain, to='duckverb')
        b = nb


def bed(b0, b1, gain=0.3):
    """Half-time filler: a sustained sub bass per chord and eighth shakers, so the energy never dips."""
    b = b0
    while b < b1 - 1e-9:
        nb = min(b1, (b // 4 + 1) * 4)
        d = (nb - b) * BEAT
        t = tt(d)
        r = ROOTS[chord_at(b)] + 12
        s = (np.sin(2 * np.pi * midi(r) * t) + 0.3 * lp(saw(midi(r), t, (-6, 6)), 300)) * np.minimum(1, t * 20) * np.clip((d - t) * 20, 0, 1)
        put(s, b, gain, to='duck')
        b = nb
    b = np.ceil(b0 * 2) / 2
    while b < b1 - 1e-9:
        put(bp(noise(0.08), 5000, 11000) * np.exp(-tt(0.08) * 50), b, 0.22 if b % 1 else 0.14, 0.5)
        b += 0.5


def drop(b, gain=1.0):
    """An energy peak: boom + chord + crash; the full groove that follows is laid by the caller."""
    put(boom(3.0, 58, 26), b, 0.62 * gain, to='verbsend')
    put(kick(0.6, 1.3), b, 1.0 * gain, to='kick')
    put(stab((45, 57, 60, 64, 69), 2.2), b, 0.42 * gain, to='verbsend')
    put(crash(3.0), b, 0.42 * gain, 0.2)
    put(crash(2.5), b, 0.3 * gain, -0.3)


PENT = [57, 60, 62, 64, 67]
SCALE = [57, 60, 62, 64, 67, 69, 72, 74, 76, 79, 81, 84, 86, 88, 91, 93]

# 1 · open, two questions (b0-7.9): a low bed, a blip per word, odometer, five chips, then half-time from b3.4
put(pad((45, 52), 8.2 * BEAT, 600, 0.6), 0, 0.34, to='verbsend')
put(bass_note(33, 3.4 * BEAT), 0, 0.5, to='duck')
for b_, m in ((0.25, 76), (1.0, 79), (2.0, 83)):                    # 每天 / 和 5 个 Agent / 协作上百次
    put(blip(m, 0.8), b_, 0.26, 0, to='verbsend')
    put(kick(0.3, 0.6), b_, 0.35, to='kick')
t_ = 0.0
while t_ < 0.5:                                                     # the orange 0 -> 5 odometer
    put(tick(), 1.0 + t_, 0.2, 0.3)
    t_ += 0.1
for i, m in enumerate((81, 84, 88, 91, 93)):                        # five agent chips pop, rising
    put(blip(m, 0.4), 1.2 + i * 0.2, 0.2, -0.5 + i * 0.25, to='verbsend')
put(whoosh(0.8 * BEAT), 2.6, 0.26, -0.2)                            # b3.0 the sentence shrinks to an eyebrow
groove(3.4, 7.9, style='half', clap_on=False, lvl=0.92)
bed(3.4, 14.6, 0.32)
pads(3.4, 7.9, 0.17, 1200)
put(marker(0.4), 4.2, 0.5, 0.3)                                     # highlighter under 怎样
put(whoosh(0.6 * BEAT), 5.3, 0.26, 0.2)                             # sentence swap
for i in range(5):                                                  # planets pulled to the mark
    put(blip(76 + [0, 3, 7, 10, 12][i], 0.5), 7.5 + i * 0.12, 0.14, -0.4 + i * 0.2, to='verbsend')

# 2 · the mark is traced, tips over and we dive into it (b7.9-14.6, as v6)
put(glide(440, 440 * 2 ** 1.2, 2.4 * BEAT), 7.9, 0.08, to='verbsend')
groove(7.9, 10.3, style='half', clap_on=False, lvl=0.92)
pads(7.9, 14.6, 0.17, 1300)
put(boom(3.0, 55, 28), 10.3, 0.42, to='verbsend')
groove(10.3, 14.6, style='half', clap_on=False, lvl=0.9)
k = 0.0                                                             # the dive: a swirl of ticks that speeds up
while k < 1.8:
    put(tick(), 12.8 + k, 0.14 + 0.2 * k / 1.8, np.sin(k * 9) * 0.6)
    k += 0.25 * (1 - k / 2.1) + 0.04
put(riser(1.8 * BEAT, 300, 6000), 12.8, 0.35, to='verbsend')
put(reverse_swell(0.8 * BEAT), 13.8, 0.6)

# 3 · sentiment ride (b14.6-21.6): groove A, a blip per road sign, then the push-through
put(crash(2.5), 14.6, 0.35, 0.2)
groove(14.6, 21.2, lvl=0.85)
pads(14.6, 21.6, 0.16)
for i in range(8):                                                  # signs every 0.7 beat from b14.8
    put(blip(PENT[i % 5] + 24, 0.5), 14.8 + i * 0.7, 0.14, -0.5 + i * 0.14, to='verbsend')
put(riser(1.2 * BEAT, 400, 7000), 20.4, 0.32, to='verbsend')
put(whoosh(1.0 * BEAT), 20.9, 0.34, 0)

# 4a · numbers (b21.2-25.6): three staggered ratchets; the groove goes light (no clap)
groove(21.2, 28.0, clap_on=False, lvl=0.82)
pads(21.6, 28.0, 0.16)
for i in range(3):
    b0 = 21.2 + i * 0.4
    t_ = 0.0
    while t_ < 1.6:
        put(tick(), b0 + t_, 0.2 * (1 - t_ / 2.0), -0.4 + i * 0.4)
        t_ += 0.05 + 0.12 * (t_ / 1.6) ** 1.5

# 4b · particles -> compass (b24.6-28)
sparkle(25.4, 0.8, 26, 0.07)                                        # 186 burst into particles
put(reverse_swell(1.4 * BEAT), 25.6, 0.55)                          # the tilted orbit flips flat (b27.0)
put(glide(3000, 9000, 1.2 * BEAT) * 0.6 + hp(noise(1.2 * BEAT), 8000) * 0.15, 27.0, 0.08, 0.3, to='verbsend')  # the light traces the ring
for i in range(8):                                                  # particles land on the dial
    put(pluck(SCALE[8 + i % 6], 0.25), 27.4 + i * 0.18, 0.07, -0.6 + i * 0.17, to='verbsend')


# 4c · the needle sweeps the 16 types: half time; a tick and a scale note each time it passes a type
SW0, SW1 = 30, 44


def sweep_at(b):
    """Needle bearing in degrees: the SAME curve as scenes/30-persona.js sweepAt()."""
    if b < SW0:
        return -150.0
    p = min(1.0, max(0.0, (b - SW0) / (SW1 - SW0)))
    e = .4 * (p / .4) ** 3 if p < .4 else 1 - .6 * (1 - (p - .4) / .6) ** 3
    return -150 + 1230 * e + (5 * np.sin((b - SW1) * 5) * np.exp(-(b - SW1) * 2.2) if b > SW1 else 0)


groove(28.0, 44.0, style='half', lvl=0.95)
bed(27.0, 44.0, 0.36)
pads(28.0, 44.0, 0.24, 1700)
prev = np.floor(sweep_at(SW0) / 22.5)
NT = 14000
for k in range(1, NT + 1):
    bb = SW0 + k * (SW1 - SW0) / NT
    cur = np.floor(sweep_at(bb) / 22.5)
    if cur != prev:
        idx = int(cur) % 16
        put(tick(), bb, 0.22, 0.1)
        put(blip(SCALE[idx], 0.3), bb, 0.08, -0.5 + idx / 16, to='verbsend')
        prev = cur

# 4d · four evidence locks, rising; riser and a snare roll into the drop
for b_, m in zip((37.6, 39.1, 40.6, 42.1), (57, 60, 64, 69)):      # A3 C4 E4 A4
    put(clack(m), b_, 0.42, 0.0, to='verbsend')
    put(clack(m + 12), b_, 0.12, 0.3)
    put(whoosh(0.7 * BEAT), b_ - 0.6, 0.12, -0.4)                   # the chip flying in
put(riser(2.5 * BEAT, 300, 6000), 41.5, 0.4, to='verbsend')
b_ = 42.0
while b_ < 44 - 1e-9:
    step = 0.5 if b_ < 42.5 else 0.25 if b_ < 43.25 else 0.125
    put(snare(0.12, 0.5), b_, 0.1 + 0.3 * (b_ - 42) / 2, 0.1)
    b_ += step
put(reverse_swell(0.6 * BEAT), 43.4, 0.6)

# 4e · DROP b44: the needle lands; full groove (four on the floor + clap + arp) to b52
drop(44)
groove(44.0, 52.0, arp=True, lvl=1.12)
pads(44.0, 52.0, 0.2, 2400)

# 4f · strengths and blind spots, the click into the portal
groove(52.0, 55.6, arp=True, lvl=0.92)
pads(52.0, 57.4, 0.17)
for i in range(3):                                                  # ✓ ×3: crisp ticks
    put(tick(), 53.0 + i * 0.3, 0.32, 0.3)
    put(blip(88 + [0, 3, 7][i], 0.25), 53.0 + i * 0.3, 0.1, 0.3, to='verbsend')
for i in range(3):                                                  # ⚠ ×3: low notes
    put(blip(45 + [0, -2, -4][i], 0.5), 53.9 + i * 0.3, 0.28, -0.2, to='duck')
put(clack(81), 55.6, 0.26, 0.2)                                     # the click on 建议 →
put(whoosh(1.0 * BEAT), 55.6, 0.3, 0.2)                             # bloom
groove(55.6, 57.4, style='half', clap_on=False, lvl=0.9)
bed(55.6, 57.4, 0.3)
put(reverse_swell(1.8 * BEAT), 55.6, 0.7)
put(riser(1.8 * BEAT, 500, 5000), 55.6, 0.22, to='verbsend')

# 5a · the conveyor: groove A + arp; a rising blip as each card's hours land in the total
put(crash(2.0), 57.4, 0.3, -0.2)
groove(57.4, 63.4, arp=True, lvl=0.95)
pads(57.4, 63.4, 0.16)
arr_ = 58.5                                                         # arrivals: interval 0.5 -> 0.3, last at 62.9
for i in range(12):
    put(blip(PENT[i % 5] + 24 + 12 * (i // 5), 0.4), arr_, 0.15, -0.5 + i * 0.09, to='verbsend')
    put(tick(), arr_, 0.12, 0.2)
    arr_ += 0.5 - 0.2 * i / 10
put(stab((57, 64, 69, 72, 76), 1.8), 63.4, 0.36, to='verbsend')    # 22.7 lands
put(crash(2.5), 63.4, 0.32, 0.2)
put(kick(0.5, 1.2), 63.4, 0.8, to='kick')

# 5b · one-click install
groove(63.4, 70.0, arp=True, lvl=0.92)
pads(63.4, 70.0, 0.16)
for b_ in (66.0, 67.4, 68.4):
    put(clack(84), b_, 0.24, 0.2)
put(whoosh(0.6 * BEAT), 66.0, 0.3, -0.2)                            # card flips into the modal
put(blip(88, 0.6), 68.6, 0.18, 0, to='verbsend')                    # installed
put(blip(93, 0.8), 68.85, 0.16, 0, to='verbsend')

# 5c · 7 days: seven ticks, rising
groove(70.0, 78.8, arp=True, lvl=0.92)
pads(70.0, 79.4, 0.16)
put(whoosh(1.0 * BEAT), 69.4, 0.2, 0.2)
for i in range(7):
    put(tick(), 70.4 + i * 0.25, 0.3, -0.4 + i * 0.13)
    put(blip(PENT[i % 5] + 24 + 12 * (i // 5), 0.25), 70.4 + i * 0.25, 0.11, -0.4 + i * 0.13, to='verbsend')

# 5d · before / after: three descending slides + strike scratches, then the "有效" chord
for i, b_ in enumerate((73.4, 74.4, 75.4)):
    m0 = 81 - 2 * i
    put(slide(m0, m0 - 12, 0.9 * BEAT), b_, 0.16, -0.3 + 0.3 * i, to='verbsend')
    put(scratch(0.32), b_, 0.32, 0.3 - 0.3 * i)
for m in (69, 73, 76, 81):                                          # A major blip
    put(blip(m, 0.9), 76.6, 0.1, 0, to='verbsend')

# 5e · DROP b79.4: two prefix ticks, then 22.7 slams down; full groove to b83.4
groove(78.8, 79.4, kick_on=False, clap_on=False, lvl=0.8)
for b_ in (78.8, 79.1):
    put(tick(), b_, 0.4, 0.0)
    put(blip(88, 0.2), b_, 0.1, 0, to='verbsend')
put(reverse_swell(0.8 * BEAT), 78.6, 0.65)
drop(79.4, 1.1)
groove(79.4, 83.4, arp=True, lvl=1.12)
pads(79.4, 83.4, 0.2, 2400)

# 6 · feature montage (b83.4-101.4): groove B (sixteenth hats + arp), an air movement at each change
groove(83.4, 101.0, arp=True, lvl=0.95)
hats16(83.4, 101.0)
pads(83.4, 101.0, 0.16)
for b_, d in ((83.6, 0.8), (89.7, 0.6), (95.2, 0.4), (96.4, 0.4), (97.6, 0.4), (98.8, 0.4), (100.0, 0.4)):
    put(whoosh(d * BEAT), b_ - d / 2, 0.2, 0.3)
put(whoosh(0.3 * BEAT), 92.3, 0.34, -0.3)                           # the 3D whip into Ask
for i in range(11):                                                 # 我上周为什么总在返工？ typed
    put(tick(), 92.6 + i * 0.13, 0.1, -0.2 + 0.04 * i)
put(clack(86), 94.4, 0.22, 0)                                       # send: AI shimmer
for i, m in enumerate((84, 88, 91, 96, 100)):
    put(blip(m, 0.5), 94.4 + i * 0.06, 0.08, -0.4 + i * 0.2, to='verbsend')
for i in range(2):                                                  # ⌘K 部署
    put(tick(), 98.4 + i * 0.2, 0.14, 0.2)
put(clack(84), 99.4, 0.24, -0.2)                                    # click Lite
put(whoosh(0.5 * BEAT), 100.4, 0.22, 0.4)                           # dark-mode wipe

# 7 · close (b101-113): half time; ring, spiral, the mark and the end card
put(whoosh(1.0 * BEAT), 100.8, 0.24, -0.2)
groove(101.0, 107.6, style='half', clap_on=False, arp=True, lvl=0.8)
bed(101.0, 107.6, 0.24)
pads(101.0, 107.6, 0.2, 2200)
put(riser(1.4 * BEAT, 300, 4000), 102.8, 0.24, to='verbsend')
put(glide(520, 520 * 2 ** 1.2, 3.4 * BEAT), 104.2, 0.08, to='verbsend')
put(reverse_swell(0.8 * BEAT), 106.8, 0.5)
put(boom(4.0, 55, 24), 107.6, 0.55, to='verbsend')
put(kick(0.6, 1.2), 107.6, 0.8, to='kick')
put(crash(4), 107.6, 0.32)
put(pad((45, 52, 57, 60, 64), (END - 107.6) * BEAT + 1.5, 1400, 0.3), 107.6, 0.32, to='verbsend')
for i, m in enumerate((81, 84, 88)):
    put(blip(m, 1.2), 108.6 + i * 1.0, 0.2, -0.4 + i * 0.4, to='verbsend')

# ---------------- mix ----------------
duck = np.ones(N)
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

mix = np.stack([out_l, out_r], 1)
mix = hp(mix.T, 25).T
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.8) / np.tanh(1.8)
fade = np.ones(N)
fade[-int(1.2 * SR):] = np.linspace(1, 0, int(1.2 * SR))
mix *= fade[:, None] * 0.82

os.makedirs(os.path.join(os.path.dirname(__file__), 'out'), exist_ok=True)
path = os.path.join(os.path.dirname(__file__), 'out', 'soundtrack.wav')
with wave.open(path, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype('<i2').tobytes())
print('wrote', path, f'{N / SR:.1f}s')
