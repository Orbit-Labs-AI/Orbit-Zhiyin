"""Soundtrack for the Tandem promo, synthesised from scratch on the same beat grid as promo.js (124 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

Sections (beats), same grid as promo.js and STORYBOARD.md: 0-8 open (a blip per word, chip and planet) · 7.9-14.6
the mark is traced, tips over and we dive into it (a swirl of ticks) · 14.6-33 groove A under the sentiment ride, the
numbers and the overview wall (a blip per phrase, odometer ticks, a pluck per bar) · 33.5-46 the compass in half time
(a tick and a scale note each time the needle passes a type, never a break) · 46 the landing chord, broken beat ·
50.6-84 groove A with an arp (recommend, trajectory, insight, studio) · 84-90.5 build · 90.8-100.6 the features ·
101-109 half time, the aurora collapses and the mark returns · 109.2 end card, tail to 118.
Transitions only get a soft whoosh.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 124
BEAT = 60 / BPM
END = 118
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


# ---------------- arrangement ----------------
A, C_, E_, F_, G_ = 57, 60, 64, 53, 55  # A3 C4 E4 F3 G3
CHORDS = [(57, 60, 64), (53, 57, 60), (48, 52, 55, 60), (55, 59, 62)]  # Am F C G
ROOTS = [33, 29, 36, 31]  # A1 F1 C2 G1


def chord_at(b):
    return int((b // 4) % 4)


KICKS = {'four': (0, 1, 2, 3), 'half': (0, 2.5), 'broken': (0, 1.75, 2.5)}
CLAPS = {'four': (1, 3), 'half': (2,), 'broken': (1, 3)}


def groove(b0, b1, kick_on=True, clap_on=True, hats=True, bassline=True, arp=False, lvl=1.0, style='four'):
    b = b0
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


PENT = [57, 60, 62, 64, 67]

# open: the words and chips, the planets fall onto the mark, the mark is traced, it tips over and we dive into it
put(pad((45, 52), 8 * BEAT, 600, 1.5), 0, 0.28, to='verbsend')
for i, m in enumerate((76, 79, 83)):
    put(blip(m, 0.8), 0.25 + i * 0.6, 0.2, -0.2 + i * 0.2, to='verbsend')
for i, m in enumerate((81, 84, 88, 91, 93)):
    put(blip(m), 2.2 + i * 0.375, 0.24, (-0.5 + i * 0.25), to='verbsend')
for i, m in enumerate((79, 83, 81, 86, 84)):
    put(blip(m, 0.8), (4, 4.5, 6, 6.4, 6.8)[i], 0.16, -0.3 + i * 0.15, to='verbsend')
for i in range(5):
    put(blip(76 + [0, 3, 7, 10, 12][i], 0.5), 7.5 + i * 0.12, 0.12, -0.4 + i * 0.2, to='verbsend')
t = tt(2.4 * BEAT)
f = 440 * 2 ** (np.clip(t / (2.4 * BEAT), 0, 1) * 1.2)
put(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((2.4 * BEAT - t) * 3, 0, 1), 7.9, 0.06, 0, to='verbsend')
put(boom(3.0, 55, 28), 10.3, 0.42, to='verbsend')
pads(8, 14.6, 0.16, 1300)
groove(10.3, 12.8, kick_on=False, clap_on=False, hats=True, bassline=True, lvl=0.45)
k = 0.0                                                     # the dive: a swirl of ticks that speeds up
while k < 1.8:
    put(tick(), 12.8 + k, 0.12 + 0.2 * k / 1.8, np.sin(k * 9) * 0.6)
    k += 0.25 * (1 - k / 2.1) + 0.04
put(riser(1.8 * BEAT, 300, 6000), 12.8, 0.35, to='verbsend')
put(reverse_swell(0.8 * BEAT), 13.8, 0.6)

# the sentiment ride: groove A, a blip as each phrase stands up
put(crash(2.5), 14.6, 0.4, 0.2)
groove(14.6, 22.3, arp=False, lvl=0.85)
pads(14.6, 22.3, 0.16)
for i in range(8):
    put(blip(PENT[i % 5] + 24, 0.5), 15 + i * 0.82, 0.13, -0.5 + i * 0.14, to='verbsend')
# numbers roll (the groove keeps going), they fly into the tiles, the tiles open into the wall
groove(22.3, 27.8, clap_on=False, lvl=0.8)
for i in range(3):
    b0 = 22.3 + i * 0.5
    t_ = 0.0
    while t_ < 1.9:
        put(tick(), b0 + t_, 0.18 * (1 - t_ / 2.2), -0.4 + i * 0.4)
        t_ += 0.05 + 0.12 * (t_ / 1.9) ** 1.5
put(whoosh(1.4 * BEAT), 25.7, 0.24, 0)
groove(27.8, 33.3, arp=True)
pads(22.3, 33.5, 0.15)
for i in range(30):
    put(pluck(PENT[i % 5] + 12 * (i // 10), 0.25), 28.6 + i * 0.07, 0.08, -0.6 + i * 0.04, to='verbsend')
put(whoosh(2 * BEAT), 33.2, 0.3, -0.3)

# 01 · the compass: half-time groove that never stops; a tick and a note each time the needle passes a type
groove(33.5, 46, style='half', lvl=0.8, arp=False)
pads(33.5, 46, 0.19, 1500)
put(riser(2.4 * BEAT, 500, 4500), 33.8, 0.16, to='verbsend')


def sweep(b):
    if b < 37:
        return -150.0
    p = min(1.0, (b - 37) / 9)
    e = 16 * p ** 5 if p < .5 else 1 - (-2 * p + 2) ** 5 / 2
    return -150 + 1230 * e


prev = np.floor(sweep(37) / 22.5)
SCALE = [57, 60, 62, 64, 67, 69, 72, 74, 76, 79, 81, 84, 86, 88, 91, 93]
for k in range(1, 4501):
    bb = 37 + k * 9 / 4500
    cur = np.floor(sweep(bb) / 22.5)
    if cur != prev:
        idx = int(cur) % 16
        put(tick(), bb, 0.22, 0.1)
        put(blip(SCALE[idx], 0.3), bb, 0.08, -0.5 + idx / 16, to='verbsend')
        prev = cur
put(riser(4 * BEAT, 300, 3500), 41.5, 0.2, to='verbsend')
put(boom(2.6, 52, 26), 46, 0.45, to='verbsend')
put(stab((57, 60, 64, 69), 1.8), 46, 0.3, to='verbsend')
put(crash(2.5), 46, 0.28)
groove(46.5, 50.6, style='broken', lvl=0.85)
pads(46, 50.6, 0.17)

# 02 · recommend: groove A with an arp, a rising blip per suggestion; the install clicks
put(whoosh(1 * BEAT), 50.2, 0.24, 0.3)
groove(50.6, 63, arp=True)
pads(50.6, 63, 0.16)
for i in range(12):
    put(blip(PENT[i % 5] + 24 + 12 * (i // 5), 0.45), 50.9 + i * 0.5 + 0.25, 0.13, -0.5 + i * 0.09, to='verbsend')
put(stab((57, 64, 69, 72), 1.4), 56.9, 0.22, to='verbsend')
for b_ in (59.4, 61):
    put(tick(), b_, 0.4, 0.2)
put(blip(88, 1.2), 61.2, 0.18, 0, to='verbsend')

# 03 · trajectory, insight, studio: groove A with sixteenth hats, a soft air movement at each change
groove(63, 84, arp=True, lvl=0.95)
pads(63, 84, 0.16)
for b_ in (63, 65.1, 68.6, 71.2, 75.8, 79.6, 81.4):
    put(whoosh(0.9 * BEAT), b_ - 0.4, 0.17, 0.3)
put(tick(), 74.4, 0.35, 0.2)

# 04 · ask: a build that keeps the hats, a half-beat breath, then the features
groove(84, 90.5, kick_on=False, clap_on=False, hats=True, bassline=False, arp=True, lvl=0.75)
pads(84, 90.5, 0.2, 2600)
b_ = 86.0
while b_ < 90.5:
    step = 0.5 if b_ < 88 else 0.25 if b_ < 89.5 else 0.125
    put(snare(0.12, 0.4), b_, 0.08 + 0.22 * (b_ - 86) / 4.5, 0.1)
    b_ += step
put(riser(6.5 * BEAT, 250, 6000), 84, 0.38, to='verbsend')
for k in (84, 86, 88, 89, 90):
    put(kick(0.4), k, 0.45, to='kick')
put(reverse_swell(0.6 * BEAT), 90.2, 0.6)
put(crash(), 90.8, 0.45, -0.2)
groove(90.8, 100.6, arp=True, lvl=1.0)
pads(90.8, 100.6, 0.17)
for b_ in (92.6, 94, 95.8, 97.4, 98.8):
    put(whoosh(0.7 * BEAT), b_ - 0.5, 0.15, 0.3)
for b_ in (96.6, 97.9):
    put(tick(), b_, 0.35, 0.2)
put(stab((53, 57, 60), 1.0), 99.2, 0.2, to='verbsend')

# close: your compass, the aurora collapses into a ring, the ring grows into the mark, the end card
put(whoosh(1.4 * BEAT), 100.5, 0.26, -0.2)
groove(101, 105.6, style='half', clap_on=False, arp=True, lvl=0.6)
pads(101, 109, 0.2, 2200)
put(riser(1.6 * BEAT, 300, 3000), 104.4, 0.18, to='verbsend')
t = tt(4 * BEAT)
f = 520 * 2 ** (np.clip(t / (4 * BEAT), 0, 1) * 1.2)
put(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((4 * BEAT - t) * 3, 0, 1), 105.8, 0.06, 0, to='verbsend')
put(boom(4.0, 55, 24), 109.2, 0.5, to='verbsend')
put(crash(4), 109.2, 0.28)
put(pad((45, 52, 57, 60, 64), 9 * BEAT, 1400, 0.3), 109.2, 0.3, to='verbsend')
for i, m in enumerate((81, 84, 88, 93)):
    put(blip(m, 1.2), 110.6 + i * 1.2, 0.18, -0.4 + i * 0.27, to='verbsend')

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
mix *= fade[:, None] * 0.7

os.makedirs(os.path.join(os.path.dirname(__file__), 'out'), exist_ok=True)
path = os.path.join(os.path.dirname(__file__), 'out', 'soundtrack.wav')
with wave.open(path, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype('<i2').tobytes())
print('wrote', path, f'{N / SR:.1f}s')
