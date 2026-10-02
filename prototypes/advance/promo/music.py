"""Soundtrack for the Tandem promo, synthesised from scratch on the same beat grid as promo.js (124 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

Sections (beats), same grid as promo.js and STORYBOARD.md: 0-8 cold open (a blip per word and per agent chip, the
planets fall onto the mark) · 8-13 the Orbit mark is traced · 13.8-17 odometer ticks · 16-29.5 groove (a climbing tone
under the sparkline, a pluck per growing bar) · 29.5-46 compass (chord per slow type, a tick per flick, a settle chord
on yours) · 46-58 recommend (a blip per suggestion, install clicks) · 58-79 trajectory, insight, studio · 79-86 build ·
87-101 seven features · 101-108 the compass tilts into an orbit · 107.5 end card, tail to 120.
Transitions only get a soft whoosh.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 124
BEAT = 60 / BPM
END = 120
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


def groove(b0, b1, kick_on=True, clap_on=True, hats=True, bassline=True, arp=False, lvl=1.0):
    b = b0
    while b < b1 - 1e-9:
        bi = round(b * 4) / 4
        if kick_on and abs(bi - round(bi)) < 1e-6:
            put(kick(), bi, 0.95 * lvl, to='kick')
        if clap_on and abs(bi % 2 - 1) < 1e-6:
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


# cold open: the words land one by one, then the five agent chips, a soft riser into the logo
put(pad((45, 52), 8 * BEAT, 600, 1.5), 0, 0.28, to='verbsend')
for i, m in enumerate((76, 79, 83)):
    put(blip(m, 0.8), 0.25 + i * 0.6, 0.2, -0.2 + i * 0.2, to='verbsend')
for i, m in enumerate((81, 84, 88, 91, 93)):
    put(blip(m), 0.95 + i * 0.375, 0.26, (-0.5 + i * 0.25), to='verbsend')
for i, m in enumerate((79, 83)):
    put(blip(m, 0.8), 4 + i * 0.5, 0.18, -0.2 + i * 0.4, to='verbsend')
for i, m in enumerate((81, 86, 84)):
    put(blip(m, 0.8), 6 + i * 0.4, 0.18, -0.3 + i * 0.3, to='verbsend')
put(riser(4 * BEAT, 300, 3000), 4, 0.3, to='verbsend')
put(reverse_swell(1.0 * BEAT), 7, 0.5)

# the five Agents orbit and fall onto the mark; the mark is traced with a rising shimmer
for i in range(5):
    put(blip(76 + [0, 3, 7, 10, 12][i], 0.5), 7.5 + i * 0.12, 0.12, -0.4 + i * 0.2, to='verbsend')
t = tt(2.4 * BEAT)
f = 440 * 2 ** (np.clip(t / (2.4 * BEAT), 0, 1) * 1.2)
put(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((2.4 * BEAT - t) * 3, 0, 1), 7.9, 0.06, 0, to='verbsend')
# logo: a soft bloom rather than a hit
put(boom(3.0, 55, 28), 10.3, 0.45, to='verbsend')
put(crash(3), 8, 0.3, 0.2)
put(pad(CHORDS[0], 6 * BEAT, 1600, 0.4), 8, 0.3, to='verbsend')
for i, m in enumerate((81, 88, 84)):
    put(blip(m, 1.2), 9 + i * 0.75, 0.16, -0.3 + i * 0.3, to='verbsend')
put(riser(2.5 * BEAT, 400, 4000), 11.5, 0.22, to='verbsend')

# 1 · the numbers roll: a ratchet of ticks that slows down for each number
for i in range(3):
    b0 = 13.8 + i * 0.5
    t = 0.0
    while t < 1.9:
        put(tick(), b0 + t, 0.22 * (1 - t / 2.2), -0.4 + i * 0.4)
        t += 0.05 + 0.12 * (t / 1.9) ** 1.5
put(whoosh(1.4 * BEAT), 17.2, 0.25, 0)
groove(14, 16, kick_on=True, clap_on=False, hats=True, bassline=False, lvl=0.5)
# drop 1
put(crash(), 16, 0.4, 0.3)
groove(16, 29.5, arp=False)
pads(14, 29.5, 0.15)

# 2 · the sparkline runs forward: a gliding tone that climbs with it
t = tt(2.8 * BEAT)
f = 440 * 2 ** (np.clip(t / (2.8 * BEAT), 0, 1) ** 1.3)
put(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((2.8 * BEAT - t) * 4, 0, 1), 19.8, 0.07, 0.2, to='verbsend')
put(whoosh(1.2 * BEAT), 22.4, 0.24, 0.4)

# 3 · bars grow one by one: a pluck per column, climbing the A-minor pentatonic
PENT = [57, 60, 62, 64, 67]
for i in range(30):
    m = PENT[i % 5] + 12 * (i // 10)
    put(pluck(m, 0.3), 23.2 + i * 0.12, 0.11, -0.6 + i * 0.04, to='verbsend')

# 4 · the bars curl into the compass: the band sweeps round, the rose grows
put(whoosh(2 * BEAT), 29.4, 0.3, -0.3)
put(riser(3 * BEAT, 500, 5000), 29.6, 0.18, to='verbsend')
pads(29.5, 37.25, 0.18, 1500)
for k in range(10):
    put(blip(PENT[k % 5] + 24, 0.5), 30 + k * 0.25, 0.07, np.sin(k / 10 * 2 * np.pi) * 0.7, to='verbsend')
put(stab((57, 64, 69), 1.4), 31.6, 0.22, to='verbsend')
groove(32.5, 37.25, kick_on=True, clap_on=False, hats=True, bassline=True, lvl=0.6)

# 5 · sixteen types: three slow ones with a chord each, twelve flicks (a tick and a rising blip each), then yours
for b_, ch in ((32.5, (57, 60, 64)), (34.5, (53, 57, 60)), (36, (55, 59, 62))):
    put(stab(ch, 1.4), b_, 0.26, to='verbsend')
FD = [.6, .5, .4, .32, .28, .26, .26, .28, .34, .42, .55, .75]
bb = 37.25
for i, d in enumerate(FD):
    put(tick(), bb, 0.32, 0.15)
    put(blip(69 + [0, 3, 5, 7, 10, 12, 15, 12, 10, 7, 5, 3][i], 0.35), bb, 0.12, -0.2 + i * 0.04, to='verbsend')
    bb += d
put(riser(5 * BEAT, 250, 3500), 37.25, 0.22, to='verbsend')
put(pad((45, 52), 5 * BEAT, 900, 0.5), 37.25, 0.2, to='verbsend')
put(boom(2.6, 52, 26), 42.25, 0.5, to='verbsend')
put(stab((57, 60, 64, 69), 1.8), 42.25, 0.32, to='verbsend')
put(crash(2.5), 42.25, 0.28)
for k, m in enumerate((81, 84, 88, 93)):
    put(blip(m, 0.7), 42.6 + k * 0.25, 0.2, -0.3 + k * 0.2, to='verbsend')
groove(43, 46, lvl=0.75)
pads(42.25, 46, 0.17)

# 02 · recommend: a coin-like blip as each suggestion arrives, climbing; the counter lands on a chord
put(whoosh(1 * BEAT), 45.6, 0.24, 0.3)
groove(46, 58, arp=True)
pads(46, 58, 0.16)
for i in range(12):
    put(blip(PENT[i % 5] + 24 + 12 * (i // 5), 0.45), 46.4 + i * 0.45 + 0.25, 0.14, -0.5 + i * 0.09, to='verbsend')
put(stab((57, 64, 69, 72), 1.4), 51.9, 0.24, to='verbsend')
for b_ in (54.4, 56):
    put(tick(), b_, 0.4, 0.2)
put(blip(88, 1.2), 56.2, 0.2, 0, to='verbsend')

# 03 · trajectory, insight, studio
put(whoosh(1.2 * BEAT), 57.6, 0.24, -0.3)
groove(58, 79, arp=True)
pads(58, 79, 0.16)
for b_ in (60.1, 63.6, 66.2, 70.8, 75.4):
    put(whoosh(0.9 * BEAT), b_ - 0.4, 0.18, 0.3)
put(tick(), 69.4, 0.35, 0.2)

# 04 · ask (build), a gap, then the features
groove(79, 86, kick_on=False, clap_on=False, hats=True, bassline=False, arp=True, lvl=0.75)
pads(79, 86, 0.2, 2600)
b_ = 81.0
while b_ < 86:
    step = 0.5 if b_ < 83 else 0.25 if b_ < 85 else 0.125
    put(snare(0.12, 0.4), b_, 0.08 + 0.22 * (b_ - 81) / 5, 0.1)
    b_ += step
put(riser(7 * BEAT, 250, 6000), 79, 0.4, to='verbsend')
for k in (79, 81, 83, 84, 85):
    put(kick(0.4), k, 0.45, to='kick')
put(reverse_swell(1.0 * BEAT), 86, 0.6)
put(crash(), 87, 0.5, -0.2)
groove(87, 101, arp=True, lvl=1.0)
pads(87, 101, 0.17)
for i in range(7):
    put(whoosh(0.7 * BEAT), 87 + i * 2 - 0.65, 0.16, 0.4 if i % 2 else -0.4)

# close: your compass, it tilts back into an orbit, the mark is traced, the end card
put(crash(2.5), 101, 0.3)
groove(101, 107.5, kick_on=False, clap_on=False, hats=True, bassline=True, arp=True, lvl=0.55)
pads(101, 108, 0.2, 2200)
put(riser(3 * BEAT, 300, 3000), 104.2, 0.18, to='verbsend')
t = tt(2.4 * BEAT)
f = 520 * 2 ** (np.clip(t / (2.4 * BEAT), 0, 1) * 1.2)
put(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, t * 8) * np.clip((2.4 * BEAT - t) * 3, 0, 1), 105.2, 0.06, 0, to='verbsend')
put(boom(4.0, 55, 24), 107.5, 0.55, to='verbsend')
put(crash(4), 107.5, 0.3)
put(pad((45, 52, 57, 60, 64), 12 * BEAT, 1400, 0.3), 107.5, 0.3, to='verbsend')
for i, m in enumerate((81, 84, 88, 93)):
    put(blip(m, 1.2), 109.4 + i * 1.5, 0.2, -0.4 + i * 0.27, to='verbsend')

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
