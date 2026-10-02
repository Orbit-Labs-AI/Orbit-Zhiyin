"""Soundtrack for the Tandem promo, synthesised from scratch on the same beat grid as promo.js (124 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

Sections (beats): 0-8 cold open (blips on the agent names, riser) · 8 impact · 8-16 pad + fly-in build ·
16-32 drop 1 · 32-36 four DIMV hits · 36-48 groove · 48-64 groove · 64-72 build (roll, riser, gap) ·
72-88 drop 2 (accent on every cut) · 88-96 hero · 96 final impact, tail to 108.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 124
BEAT = 60 / BPM
END = 108
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


# cold open: drone, blips on the five agent names, ticks, riser into the logo
put(pad((45, 52), 8 * BEAT, 600, 1.5), 0, 0.28, to='verbsend')
for i, m in enumerate((81, 84, 88, 91, 93)):
    put(blip(m), i * 0.75, 0.35, (-0.5 + i * 0.25), to='verbsend')
for b in range(4, 8):
    put(tick(), b, 0.5, 0.2)
    put(tick(), b + .5, 0.3, -0.2)
put(riser(4 * BEAT), 4, 0.45, to='verbsend')
put(reverse_swell(1.0 * BEAT), 7, 0.9)

# logo impact
put(boom(), 8, 1.0, to='verbsend')
put(crash(3), 8, 0.7, 0.2)
put(stab(CHORDS[0], 1.8), 8, 0.35, to='verbsend')
pads(8, 16, 0.2, 1200)
put(whoosh(1 * BEAT), 11, 0.8, -0.3)
put(kick(0.6, 1.4), 12, 0.9, to='kick')
for b in (13, 14, 15, 15.5):
    put(kick(), b, 0.6, to='kick')
for k in range(16):
    put(snare(0.12), 14 + k * 0.125, 0.12 + 0.3 * k / 16, 0.1)
put(riser(2 * BEAT, 500, 6000), 14, 0.4)
put(reverse_swell(0.5 * BEAT), 15.5, 1.0)

# drop 1
put(crash(), 16, 0.8, 0.3)
put(boom(1.2, 80, 40), 16, 0.6)
groove(16, 31.5, arp=True)
pads(16, 32, 0.16)
for b in (20, 24, 28):
    put(whoosh(0.5 * BEAT), b - 0.5, 0.55, 0.3)
    put(stab(CHORDS[chord_at(b)], 0.7), b, 0.22, to='verbsend')
put(whoosh(1 * BEAT), 31, 0.8)

# DIMV: four hits, then the name
for i, b in enumerate((32, 33, 34, 35)):
    put(boom(0.9, 90, 40), b, 0.9)
    put(stab((45 + (0, 3, 7, 12)[i], 57 + (0, 3, 7, 12)[i]), 0.8), b, 0.4, to='verbsend')
    put(snare(0.3), b, 0.35)
put(boom(2.0), 36, 0.8, to='verbsend')
put(crash(), 36, 0.6)
put(stab(CHORDS[0], 1.6), 36, 0.35, to='verbsend')
put(riser(2 * BEAT, 400, 5000), 36, 0.3)

# persona + trajectory grooves
groove(38, 48, clap_on=True, arp=False, lvl=0.85)
pads(38, 48, 0.17)
put(crash(2), 44, 0.4)
put(stab(CHORDS[chord_at(44)], 0.7), 44, 0.25, to='verbsend')
put(crash(), 48, 0.6)
groove(48, 60, arp=True)
pads(48, 64, 0.16)
put(stab(CHORDS[chord_at(56)], 0.7), 56, 0.25, to='verbsend')
put(whoosh(0.5 * BEAT), 55.5, 0.5)
groove(60, 64, kick_on=True, clap_on=False, arp=True, lvl=0.8)

# build: ask the local agent
groove(64, 71.5, kick_on=False, clap_on=False, hats=True, bassline=False, arp=True, lvl=0.8)
pads(64, 71.5, 0.2, 2600)
b = 64.0
while b < 71.5:
    step = 0.5 if b < 68 else 0.25 if b < 70 else 0.125
    put(snare(0.12), b, 0.15 + 0.4 * (b - 64) / 7.5, 0.1)
    b += step
put(riser(7.5 * BEAT, 250, 7000), 64, 0.55, to='verbsend')
for k in (64, 66, 68, 69, 70, 70.5, 71):
    put(kick(0.4), k, 0.55, to='kick')

# drop 2
put(boom(1.6, 90, 35), 72, 1.0)
put(crash(), 72, 0.8, -0.2)
groove(72, 88, arp=True, lvl=1.05)
pads(72, 88, 0.17)
for b in range(74, 88, 2):
    put(whoosh(0.4 * BEAT), b - 0.4, 0.45, 0.4 if b % 4 else -0.4)
    put(stab(CHORDS[chord_at(b)], 0.6), b, 0.24, to='verbsend')
    put(boom(0.5, 100, 50), b, 0.35)

# hero + end card
put(crash(), 88, 0.5)
groove(88, 95.5, kick_on=True, clap_on=False, hats=True, bassline=True, arp=True, lvl=0.7)
pads(88, 96, 0.2, 2400)
put(reverse_swell(1.5 * BEAT), 94.5, 1.0)
put(boom(4.0, 70, 24), 96, 1.0, to='verbsend')
put(crash(4), 96, 0.7)
put(pad((45, 52, 57, 60, 64), 12 * BEAT, 1400, 0.05), 96, 0.3, to='verbsend')
for i, m in enumerate((81, 84, 88, 93)):
    put(blip(m, 1.2), 97 + i * 1.5, 0.22, -0.4 + i * 0.27, to='verbsend')

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
mix *= fade[:, None] * 0.93

os.makedirs(os.path.join(os.path.dirname(__file__), 'out'), exist_ok=True)
path = os.path.join(os.path.dirname(__file__), 'out', 'soundtrack.wav')
with wave.open(path, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype('<i2').tobytes())
print('wrote', path, f'{N / SR:.1f}s')
