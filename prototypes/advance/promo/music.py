"""Soundtrack for the Orbit promo, synthesised from scratch on the same beat grid as promo.js (124 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

Sections (beats), v7, same grid as promo.js and the 声音 table in STORYBOARD.md: 0-3.4 open (a blip per word,
odometer, five chips) · 3.4-7.9 half time, highlighter, sentence swap · 7.9-22.6 (film beats) the mark is traced,
the wordmark reveal, the dive. Everything after is written in scene beats and played SHIFT[scene] beats later ·
14.6-21.6 groove A under the sentiment ride, push-through riser · 21.2-28 numbers (ratchets) and particles ·
28-44 half time, a tick + scale note per type the lead petal passes (sweep_at = sweepAt in scenes/30-persona.js),
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
# = SHIFT in promo.js: each later scene plays this many beats later (wordmark reveal, longer persona / recs holds)
SHIFT = {'20-sentiment': 8, '30-persona': 8, '40-recs': 12, '50-montage': 16, '60-close': 8}
SH = 0              # shift put() applies; set per section below
END = 113 + SHIFT['60-close']   # film beats
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
    i = at(b + SH)
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
bed(3.4, 22.6, 0.32)
pads(3.4, 7.9, 0.17, 1200)
put(marker(0.4), 4.2, 0.5, 0.3)                                     # highlighter under 怎样
put(whoosh(0.6 * BEAT), 5.3, 0.26, 0.2)                             # sentence swap
for i in range(5):                                                  # planets pulled to the mark
    put(blip(76 + [0, 3, 7, 10, 12][i], 0.5), 7.5 + i * 0.12, 0.14, -0.4 + i * 0.2, to='verbsend')

# 2 · the mark is traced (b7.9-10.4), the kit's reveal turns it into Orbit·知音 (turn b11-14.1, letters b13.3-15.5),
# the letters leave (b17.4), the O tips to the top view (b18.6) and we dive into it (b20.8-22.6)
put(glide(440, 440 * 2 ** 1.2, 2.4 * BEAT), 7.9, 0.08, to='verbsend')
groove(7.9, 10.3, style='half', clap_on=False, lvl=0.92)
pads(7.9, 22.6, 0.17, 1300)
put(boom(3.0, 55, 28), 10.3, 0.42, to='verbsend')                   # the mark is complete
put(whoosh(3.0 * BEAT), 11.0, 0.2, -0.3)                            # the turn
put(glide(520, 520 * 2 ** 0.5, 3.0 * BEAT), 11.0, 0.06, to='verbsend')
for i, m_ in enumerate((76, 79, 81, 83, 84, 86, 88)):                # rbit·知音, one note per glyph
    put(blip(m_, 0.6), 13.3 + i * 0.227, 0.16, -0.45 + i * 0.15, to='verbsend')
groove(14.0, 22.6, style='half', clap_on=False, lvl=0.9)
put(whoosh(0.8 * BEAT), 17.3, 0.2, 0.3)                             # letters leave
put(glide(440 * 2 ** 0.5, 440, 2.0 * BEAT), 18.6, 0.06, to='verbsend')
k = 0.0                                                             # the dive: a swirl of ticks that speeds up
while k < 1.8:
    put(tick(), 20.8 + k, 0.14 + 0.2 * k / 1.8, np.sin(k * 9) * 0.6)
    k += 0.25 * (1 - k / 2.1) + 0.04
put(riser(1.8 * BEAT, 300, 6000), 20.8, 0.35, to='verbsend')
put(reverse_swell(0.8 * BEAT), 21.8, 0.6)
SH = SHIFT['20-sentiment']                                          # from here on: scene beats

# 3 · sentiment ride (b14.6-21.6): groove A, a blip per road sign, then the push-through
put(crash(2.5), 14.6, 0.35, 0.2)
groove(14.6, 21.2, lvl=0.85)
pads(14.6, 21.6, 0.16)
for i in range(8):                                                  # signs every 0.7 beat from b14.8
    put(blip(PENT[i % 5] + 24, 0.5), 14.8 + i * 0.7, 0.14, -0.5 + i * 0.14, to='verbsend')
put(riser(1.2 * BEAT, 400, 7000), 20.4, 0.32, to='verbsend')
put(whoosh(1.0 * BEAT), 20.9, 0.34, 0)

# 4a · three words (b21.2-25.6): a soft note as each rises; the groove goes light (no clap)
groove(21.2, 28.0, clap_on=False, lvl=0.82)
pads(21.6, 28.0, 0.16)
for i in range(3):
    put(blip(PENT[i] + 24, 0.6), 21.4 + i * 0.4, 0.16, -0.4 + i * 0.4, to='verbsend')

# 4b · particles -> compass (b24.6-28)
sparkle(25.0, 0.8, 26, 0.07)                                        # 186 bursts into particles (30-persona b25.0)
put(reverse_swell(1.4 * BEAT), 25.6, 0.55)                          # the tilted orbit flips flat (b27.0)
put(glide(3000, 9000, 1.2 * BEAT) * 0.6 + hp(noise(1.2 * BEAT), 8000) * 0.15, 27.0, 0.08, 0.3, to='verbsend')  # the light traces the ring
for i in range(8):                                                  # particles land on the dial
    put(pluck(SCALE[8 + i % 6], 0.25), 27.4 + i * 0.18, 0.07, -0.6 + i * 0.17, to='verbsend')


# 4c · the flower browses two example types and lands on yours (30-persona STOPS: 33.4 / 38.2 / 43.4, MOVE 1.8):
# no ticks; a soft swish as the petals spin closed, a bloom chord as the next type spins open
groove(28.0, 44.0, style='half', lvl=0.95)
bed(27.0, 44.0, 0.36)
pads(28.0, 44.0, 0.24, 1700)
put(glide(330, 660, 3.0 * BEAT), 30.0, 0.06, to='verbsend')      # the closed bud turns once round
for at_, ch in ((33.4, (57, 64, 69)), (38.2, (60, 64, 72)), (43.4, (57, 64, 69, 76))):
    if at_ > 34:
        put(whoosh(0.9 * BEAT), at_ - 1.8, 0.14, -0.2)              # petals spin closed
    for i, n in enumerate(ch):                                      # bloom: a rolled chord
        put(pluck(n + 12, 0.9), at_ - 0.6 + i * 0.07, 0.1, -0.3 + i * 0.2, to='verbsend')
put(riser(2.5 * BEAT, 300, 6000), 41.5, 0.4, to='verbsend')
b_ = 42.0
while b_ < 44 - 1e-9:
    step = 0.5 if b_ < 42.5 else 0.25 if b_ < 43.25 else 0.125
    put(snare(0.12, 0.5), b_, 0.1 + 0.3 * (b_ - 42) / 2, 0.1)
    b_ += step
put(reverse_swell(0.6 * BEAT), 43.4, 0.6)

# 4e · DROP b44: your type lands; full groove (four on the floor + clap + arp) while it is read (to b53.5)
drop(44)
groove(44.0, 53.5, arp=True, lvl=1.12)
pads(44.0, 53.5, 0.2, 2400)

# 4f · strengths and blind spots (rows every .45 beat from b54.5), the click into the portal at b59.6
groove(53.5, 59.6, arp=True, lvl=0.92)
pads(53.5, 61.4, 0.17)
for i in range(3):                                                  # ✓ ×3: crisp ticks
    put(tick(), 54.5 + i * 0.45, 0.32, 0.3)
    put(blip(88 + [0, 3, 7][i], 0.25), 54.5 + i * 0.45, 0.1, 0.3, to='verbsend')
for i in range(3):                                                  # ⚠ ×3: low notes
    put(blip(45 + [0, -2, -4][i], 0.5), 54.5 + (3 + i) * 0.45, 0.28, -0.2, to='duck')
put(clack(81), 59.6, 0.26, 0.2)                                     # the click on 建议 →
put(whoosh(1.0 * BEAT), 59.6, 0.3, 0.2)                             # bloom
groove(59.6, 61.4, style='half', clap_on=False, lvl=0.9)
bed(59.6, 61.4, 0.3)
put(reverse_swell(1.8 * BEAT), 59.6, 0.7)
put(riser(1.8 * BEAT, 500, 5000), 59.6, 0.22, to='verbsend')

SH = SHIFT['40-recs']
# 5a · three cards drop (40-recs LAND 57.0 / 60.8 / 64.6): a soft landing and a short ripple as the estimate rolls
put(crash(2.0), 57.0, 0.26, -0.2)
groove(57.0, 65.6, arp=True, lvl=0.92)
pads(57.0, 65.6, 0.16)
for i, at_ in enumerate((57.0, 60.8, 64.6)):
    put(whoosh(0.5 * BEAT), at_ - 0.5, 0.12, 0.2)
    put(blip(PENT[i * 2 % 5] + 24, 0.5), at_, 0.16, -0.3 + i * 0.3, to='verbsend')
    for k in range(5):                                              # the number rolls
        put(tick(), at_ + k * 0.14, 0.1 * (1 - k / 6), 0.2)

# 5b · lift, press, the install sheet is read (quiet), 下一步 / 确认写入, applied
groove(65.6, 67.2, arp=True, lvl=0.9)
groove(67.2, 74.6, style='half', clap_on=False, lvl=0.8)
pads(65.6, 74.6, 0.18, 1600)
put(clack(84), 66.6, 0.24, 0.2)
put(whoosh(0.6 * BEAT), 66.6, 0.3, -0.2)                            # card flips into the sheet
for b_ in (71.8, 73.0):
    put(clack(84), b_, 0.24, 0.2)
put(blip(88, 0.6), 73.3, 0.18, 0, to='verbsend')                    # applied
put(blip(93, 0.8), 73.55, 0.16, 0, to='verbsend')

# 5c · before / after of the same recommendation: three descending slides, then the "有效" chord
groove(74.6, 81.6, arp=True, lvl=0.92)
pads(74.6, 81.6, 0.16)
put(whoosh(1.0 * BEAT), 74.8, 0.2, 0.2)
for i, b_ in enumerate((76.4, 77.2, 78.0)):
    m0 = 81 - 2 * i
    put(slide(m0, m0 - 12, 0.9 * BEAT), b_, 0.16, -0.3 + 0.3 * i, to='verbsend')
for m_ in (69, 73, 76, 81):                                         # A major blip
    put(blip(m_, 0.9), 79.2, 0.1, 0, to='verbsend')

# 5e · DROP b82.2: two prefix ticks, then 把时间还给你自己; full groove to b86.6
groove(81.6, 82.2, kick_on=False, clap_on=False, lvl=0.8)
for b_ in (81.6, 81.9):
    put(tick(), b_, 0.4, 0.0)
    put(blip(88, 0.2), b_, 0.1, 0, to='verbsend')
put(reverse_swell(0.8 * BEAT), 81.4, 0.65)
drop(82.2, 1.1)
groove(82.2, 86.6, arp=True, lvl=1.12)
pads(82.2, 86.6, 0.2, 2400)

SH = SHIFT['50-montage']
# 6 · trajectory and studio only (b83.4-93.5): groove B, an air movement at each push-in and on the way out
groove(83.4, 92.7, arp=True, lvl=0.95)
hats16(83.4, 92.7)
pads(83.4, 93.0, 0.16)
for b_, d in ((83.9, 0.8), (88.7, 0.6)):
    put(whoosh(d * BEAT), b_ - d / 2, 0.2, 0.3)
put(whoosh(0.8 * BEAT), 92.7, 0.22, -0.3)

SH = SHIFT['60-close']
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
put(pad((45, 52, 57, 60, 64), (END - SHIFT['60-close'] - 107.6) * BEAT + 1.5, 1400, 0.3), 107.6, 0.32, to='verbsend')
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
