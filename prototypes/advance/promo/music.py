"""Soundtrack for the Orbit promo (v17.3), synthesised from scratch on the film's beat grid (132 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

One key, one loop. Everything is in C major / A minor on a warm vi–IV–I–V loop, voiced so every chord keeps E on top:
Am7 (A C E G) · Fmaj7 (F A C E) · Cadd9 (C E G D) · G6 (G B D E). The two lifts — 「So，我们做了一个 Assistant」 (b18.2) and
the end card — are IV → V → I cadences onto a wide, bright Cadd9; the recommendations peak is a deceptive V → Am9.
Every pitched cue (badges, plucks, stabs, arps, bells, entry notes) is quantised to the chord sounding at its beat
(`q()` / `tone()`), there are no glides, semitone rubs or chromatic slides, and rapid events (bubble pops and shrinks,
typing, counter ticks, dial ticks, run logs) are soft unpitched textures under the groove, so they never form a melody.

SHIFT-aware: every cue below is written in its scene file's own beats inside `section('<scene>')`; put(), the chord
timeline, the groove spans and the pad-level points all add SHIFT[scene] (the same table as promo.js). Chords change on
bar lines (every 4 beats) and pads crossfade across every change, so a cue that moves by a beat still sits on the
right harmony; the groove is laid on the absolute film grid from per-section spans (a later span wins an overlap,
a gap < 4 beats left by a SHIFT is bridged, except the storyboard's pre-drop breath b17.8–18.2). END = 88 + SHIFT of
60-close; the fade runs over the last 1.8 beats.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 132
BEAT = 60 / BPM
# = SHIFT in promo.js: each scene plays this many beats later (the integrator fills these in; all cues follow)
SHIFT = {'10-intro': 0, '15-redesign': 6.9, '20-orbit': 11.3, '30-persona': 16.9, '40-recs': 22.9, '50-tools': 30.9, '60-close': 36.9}
END = 89 + SHIFT['60-close']   # film beats (scenes/60-close.js sets END = 89 in its own beats)
TAIL = 1.0                     # seconds of silence after END, so the mux never cuts a sample short
N = int((END * BEAT + TAIL) * SR)
rng = np.random.default_rng(7)
BUS = {}   # name -> (L, R), for sidechain and reverb sends
SH = 0     # SHIFT of the section being written


def section(name):
    global SH
    SH = SHIFT[name]


def bus(name):
    if name not in BUS:
        BUS[name] = (np.zeros(N), np.zeros(N))
    return BUS[name]


def at(fb):
    return int(round(fb * BEAT * SR))


def putf(sig, fb, gain=1.0, pan=0.0, to='dry'):
    """Place at a FILM beat."""
    l_, r_ = bus(to)
    i = at(fb)
    if i >= N or i < 0:
        return
    s = sig[: N - i] * gain
    l_[i:i + len(s)] += s * np.sqrt(0.5 * (1 - pan))
    r_[i:i + len(s)] += s * np.sqrt(0.5 * (1 + pan))


def put(sig, b, gain=1.0, pan=0.0, to='dry'):
    """Place at a SCENE beat of the current section."""
    putf(sig, b + SH, gain, pan, to)


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


def saw(f, t, detune=(0,), phases=None):
    out = np.zeros_like(t)
    for k, d in enumerate(detune):
        ff = f * 2 ** (d / 1200)
        out += 2 * ((t * ff + (rng.random() if phases is None else phases[k])) % 1) - 1
    return out / len(detune)


# ---------------- harmony ----------------
CH = {   # name -> (pad voicing, bass root, pitch classes for quantising)
    'Am': ((57, 60, 64, 67), 33),
    'F': ((53, 57, 60, 64), 29),
    'C': ((48, 55, 60, 62, 64), 36),
    'G': ((55, 59, 62, 64), 31),
    'C+': ((48, 55, 60, 64, 67, 72, 74, 76), 36),     # the lift: wide, bright Cadd9
    'Am+': ((45, 57, 60, 64, 67, 71, 76), 33),        # recommendations peak: Am9
    'F/C': ((48, 53, 57, 60, 64, 69), 36),            # end card plagal shimmer over a C pedal
}
PCS = {k: sorted({m % 12 for m in v[0]}) for k, v in CH.items()}
PROG = []        # (film beat, chord), filled per section
PADLVL = []      # (film beat, gain, cutoff) automation points for the pad layer
GROOVE = []      # (film b0, film b1, params) spans, a later one wins an overlap


def chords(*pairs):
    for b, c in pairs:
        PROG.append((b + SH, c))


def padlvl(b, gain, cutoff):
    PADLVL.append((b + SH, gain, cutoff))


def chord_f(fb):
    c = 'Am'
    for s, ch in sorted(PROG):
        if fb + 1e-9 >= s:
            c = ch
    return c


def q(m, b):
    """Quantise MIDI note m to the nearest tone of the chord sounding at scene beat b (ties go down)."""
    pcs = PCS[chord_f(b + SH)]
    return min((m + d for d in range(-6, 7) if (m + d) % 12 in pcs), key=lambda x: (abs(x - m), x))


def tone(b, k, base=72):
    """k-th chord tone at/above `base` for scene beat b (k may exceed the chord size: wraps up an octave)."""
    pcs = PCS[chord_f(b + SH)]
    out, m = [], base
    while len(out) <= k:
        if m % 12 in pcs:
            out.append(m)
        m += 1
    return out[k]


# ---------------- instruments ----------------
def kick(d=0.5, punch=1.0):
    t = tt(d)
    f = 46 + 110 * np.exp(-t * 38) * punch
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 6.5)
    click = hp(noise(d), 3000) * np.exp(-t * 400) * 0.25
    return np.tanh((body + click) * 1.5)


def clap():
    d = 0.35
    t = tt(d)
    env = np.zeros_like(t)
    for k, o in enumerate((0, 0.011, 0.022)):
        env += (t >= o) * np.exp(-(t - o).clip(0) * (90 if k < 2 else 16))
    return bp(noise(d), 900, 2600) * env * 0.8


def hat(open_=False):
    d = 0.3 if open_ else 0.06
    t = tt(d)
    return hp(noise(d), 7500, 4) * np.exp(-t * (12 if open_ else 70)) * (0.42 if open_ else 0.34)


def shaker():
    return bp(noise(0.08), 5000, 11000) * np.exp(-tt(0.08) * 50)


def blip(m, d=0.5):
    t = tt(d)
    f = midi(m)
    s = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    return s * np.exp(-t * 8) * np.minimum(1, t * 300)


def pluck(m, d=0.4):
    t = tt(d)
    return lp(saw(midi(m), t, (-6, 6)), 2200) * np.exp(-t * 10) * np.minimum(1, t * 300)


def bass_note(m, d):
    t = tt(d)
    s = saw(midi(m), t, (-5, 5), phases=(0, .25)) + 0.6 * np.sin(2 * np.pi * midi(m) * t)
    env = np.minimum(1, t * 300) * np.exp(-t * 2.2) * np.clip((d - t) * 60, 0, 1)
    return lp(s, 480, 4) * env


def pad(ms, d, cutoff=1800, att=0.5, rel=0.6):
    t = tt(d)
    s = sum(saw(midi(m), t, (-10, -3, 4, 11)) for m in ms) / np.sqrt(len(ms)) / 2
    env = np.clip(t / att, 0, 1) ** 1.5 * np.clip((d - t) / rel, 0, 1) ** 1.5
    return lp(s, cutoff, 2) * env


def stab(ms, d=0.9):
    t = tt(d)
    s = sum(saw(midi(m), t, (-8, 0, 8)) for m in ms) / len(ms)
    return lp(s, 2600) * np.exp(-t * 4) * np.minimum(1, t * 300)


def boom(d=3.0, f0=58, f1=28):
    t = tt(d)
    f = f1 + (f0 - f1) * np.exp(-t * 3)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.3)
    hit = lp(noise(d), 700) * np.exp(-t * 9) * 0.6
    return np.tanh((body + hit) * 1.3)


def crash(d=2.5):
    t = tt(d)
    return hp(noise(d), 5000, 2) * np.exp(-t * 1.6) * 0.45


def riser(d, f0=300, f1=4000):
    """Rising filtered noise (no pitched sweep, so nothing slides through odd intervals)."""
    t = tt(d)
    p = t / d
    n = noise(d)
    lo, mid, hi = bp(n, f0, f0 * 3), bp(n, f0 * 3, f1 / 2), hp(n, f1 / 2)
    sw = np.where(p < .5, lo * (1 - 2 * p) + mid * 2 * p, mid * (2 - 2 * p) + hi * (2 * p - 1))
    return sw * p ** 2.2


def whoosh(d=0.5, down=False):
    t = tt(d)
    p = t / d
    if down:
        p = 1 - p
    n = noise(d)
    return (bp(n, 400, 1600) * (1 - p) + hp(n, 2500) * p) * np.sin(np.pi * t / d) ** 2 * 0.7


def swell(d=1.0):
    t = tt(d)
    return hp(noise(d), 3000) * (t / d) ** 3 * 0.5


def tick(g=1.0):
    t = tt(0.04)
    return hp(noise(0.04), 5000) * np.exp(-t * 160) * 0.5 * g


def key_click():
    t = tt(0.03)
    return hp(noise(0.03), 3500) * np.exp(-t * 400) * 0.6


def puff(bright=1.0):
    """A bubble pops / shrinks: a soft air puff with a low round thump, unpitched."""
    t = tt(0.12)
    n = bp(noise(0.12), 900 * bright, 3200 * bright) * np.exp(-t * 45) * np.minimum(1, t * 900)
    return n * 0.7 + np.sin(2 * np.pi * 150 * t) * np.exp(-t * 50) * 0.35


def press():
    """A button press (send / click): a dry soft knock."""
    t = tt(0.12)
    return np.sin(2 * np.pi * 180 * t) * np.exp(-t * 55) * 0.6 + bp(noise(0.12), 1500, 5000) * np.exp(-t * 200) * 0.5


def bell(m, d=2.4):
    t = tt(d)
    f = midi(m)
    s = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * k) for r, a, k in
            ((1, 1, 1.5), (2.0, .4, 2.4), (3.0, .15, 3.5), (4.0, .08, 5.0)))     # harmonic partials only: no clangs
    return s * np.minimum(1, t * 300)


def grain(b0, b1, n, gain):
    """Dust: sparse unpitched clicks."""
    for _ in range(n):
        put(tick(), b0 + (b1 - b0) * rng.random(), gain * (0.4 + 0.6 * rng.random()), rng.random() * 1.6 - 0.8, to='verbsend')


def shimmer(b0, dur, n, gain, base=84):
    """Glitter made of chord tones only, scattered over dur beats."""
    for i in range(n):
        b = b0 + dur * (i / n) ** 0.7 + 0.03 * rng.random()
        put(blip(tone(b, int(rng.integers(0, 4)), base), 0.15), b, gain * (0.5 + 0.5 * rng.random()), rng.random() * 1.4 - 0.7, to='verbsend')


def typing(b0, n, dur, gain=0.07):
    """n characters typed evenly over dur beats (AGD.chat: character k at b0 + dur * k / n)."""
    for k in range(1, n + 1):
        put(key_click(), b0 + dur * k / n, gain * (0.8 + 0.4 * rng.random()), 0.15 * (rng.random() - 0.5))


def pops(beats, gain, bright=1.0):
    for b in beats:
        put(puff(bright), b, gain * (0.85 + 0.3 * rng.random()), -0.5 + rng.random(), to='verbsend')


def counter(b0, dur=1.2, n=10, gain=0.06):
    """A number rolling over dur beats (E.out): soft ticks, dense first."""
    for k in range(n):
        put(tick(), b0 + dur * (1 - (1 - k / n) ** (1 / 3)), gain * (1 - 0.6 * k / n), 0.45)


def arp(b0, b1, step, gain, base=72, span=5, accel=1.0, to='verbsend'):
    """Up-down chord-tone arpeggio on the sixteenth grid; accel < 1 shortens the step toward the end."""
    b, i = b0, 0
    while b < b1 - 1e-9:
        p = (b - b0) / max(1e-9, b1 - b0)
        k = i % (2 * span - 2)
        k = k if k < span else 2 * span - 2 - k
        put(pluck(tone(b, k, base), 0.3), b, gain * (0.75 + 0.35 * p), -0.4 + 0.2 * (i % 5), to=to)
        b += step * (1 + (accel - 1) * p)
        i += 1


def roll(b0, n, gain, gap=0.1, base=60, d=1.0):
    """A rolled chord of chord tones (petals opening)."""
    for i in range(n):
        put(pluck(tone(b0, i, base), d), b0 + i * gap, gain, -0.4 + 0.8 * i / max(1, n - 1), to='verbsend')


def groove(b0, b1, style='four', lvl=1.0, kick_on=True, clap_on=True, hats=True, bass=True, arp16=False, bed=0.0):
    GROOVE.append((b0 + SH, b1 + SH, dict(style=style, lvl=lvl, kick_on=kick_on, clap_on=clap_on, hats=hats,
                                         bass=bass, arp16=arp16, bed=bed)))


def peak(b, ch, gain=1.0, crash_gain=1.0):
    """An energy peak: boom + kick + chord stab + crash (stab voiced from the chord itself)."""
    v = CH[ch][0]
    put(boom(3.0), b, 0.5 * gain, to='verbsend')
    put(kick(0.6, 1.2), b, 0.9 * gain, to='kick')
    put(stab(v + (v[0] - 12,), 2.2), b, 0.34 * gain, to='verbsend')
    put(crash(3.0), b, 0.32 * gain * crash_gain, 0.2)
    put(crash(2.5), b, 0.22 * gain * crash_gain, -0.3)


AG = (64, 67, 69, 72, 76)   # the five Agent badges cc / cx / gm / ds / cp: E G A C E (Am7 / Cadd9 tones)

# ================= 10-intro: 1a 用 AI Agent (b0–4.2) · 1b 从想法到交付 (b4–8.8) · 1c We Are Redesigning Everything =========
section('10-intro')
chords((0, 'Am'), (4, 'F'), (8, 'C'))
padlvl(0, 0.20, 600)
padlvl(3.6, 0.20, 900)
padlvl(4.4, 0.15, 1300)
padlvl(8.6, 0.15, 1600)
put(bass_note(33, 4.2 * BEAT), 0, 0.32, to='duck')
grain(0, 4.2, 18, 0.05)
for i, m in enumerate(AG):                                                  # the badges pop (b0.2–1.2): Am7 tones
    put(blip(q(m + 12, 0.2), 0.6), 0.2 + 0.25 * i, 0.12, -0.6 + 0.3 * i, to='verbsend')
for b_ in (0.5, 0.9, 1.5, 2.1):                                             # words wipe in: soft low pulses
    put(kick(0.25, 0.4), b_, 0.18, to='kick')
put(kick(0.3, 0.7), 2.7, 0.3, to='kick')                                    # 「日常」 lands like a stamp
put(swell(0.6 * BEAT), 3.2, 0.3)
put(whoosh(0.6 * BEAT), 3.6, 0.12, -0.2)
groove(4.0, 8.6, clap_on=False, lvl=0.66)                                   # light four on the floor
typing(4.15, 9, 1.0)                                                        # 做一个记账 App
typing(5.45, 5, 0.55)                                                       # 写份路演稿
typing(6.25, 6, 0.65)                                                       # 生成产品官网
for b_ in (5.35, 6.15, 7.05):                                               # sends
    put(press(), b_, 0.08, -0.3)
pops((4.6, 5.05, 5.5, 5.85, 6.3, 6.35, 6.75, 7.2), 0.07)                    # bubbles rise out of the dots
pops((6.5, 6.9, 7.3, 7.75, 7.8, 7.9, 8.15, 8.4), 0.035, 0.7)                # and shrink back (softer, darker)
put(swell(0.6 * BEAT), 6.35, 0.32)                                          # b6.95 the App icons burst out
arp(6.95, 7.35, 0.0333, 0.07, base=72, span=6)                              # one quick upward chord run as they spray
put(pad(CH['F'][0], 1.6 * BEAT, 2800, 0.1, 0.8), 6.95, 0.07, to='verbsend')
shimmer(7.2, 1.0, 8, 0.025)                                                 # the halo draws in (b7.2–8.2)
put(whoosh(1.2 * BEAT), 8.4, 0.1, 0.3)                                      # the dots retreat to the edges
groove(8.6, 12.4, lvl=0.82)
for k, b_ in enumerate((8.8, 9.3, 9.8, 10.3)):                              # We / Are / Redesigning / Everything
    put(stab(tuple(tone(b_, j, 60) for j in range(3)) + (tone(b_, k, 67),), 0.7 if k < 3 else 1.4), b_, 0.17 + 0.02 * k, -0.15 + 0.1 * k, to='verbsend')
    put(kick(0.4, 1.0), b_, 0.28 if k < 3 else 0.42, to='kick')
put(crash(2.0), 10.3, 0.14, 0.25)
put(riser(1.3 * BEAT, 400, 3000), 10.4, 0.07, to='verbsend')                # the icons turn outward
put(whoosh(0.9 * BEAT), 11.7, 0.14, -0.2)                                   # and fly out
LPF = [(11.4 + SH, 12.2 + SH, 12.4 + SH, 13.2 + SH, 520)]                   # low-pass dips at the turn into 1d

# ================= 15-redesign: 1d 但，交互本身也需要被重新定义 (b12.4–17.8) · 1e So，我们做了一个 Assistant (b18.2–22) ====
section('15-redesign')
chords((12, 'F'), (16, 'G'), (18.2, 'C+'))                                  # IV → V → the lift on I
padlvl(12.4, 0.15, 1200)
padlvl(16.0, 0.17, 1700)
padlvl(17.9, 0.10, 2400)
padlvl(18.2, 0.20, 2600)
padlvl(21.6, 0.18, 2200)
groove(12.4, 17.8, style='half', lvl=0.82, bed=0.24)
typing(13.0, 4, 0.8)                                                        # 请你修改
typing(14.05, 3, 0.47)                                                      # fix
typing(14.82, 4, 0.58)                                                      # 请你继续
typing(15.8, 4, 0.9)                                                        # 看清需求 (never sent)
for b_ in (13.95, 14.67, 15.51):
    put(press(), b_, 0.08, -0.2)
FIX = [14.1, 14.4, 14.65, 14.82, 15.12, 15.28, 15.42, 15.54, 15.66, 15.76, 15.9, 16.05]
for k, b_ in enumerate(FIX):                                                # corrections pile up: denser, a touch brighter
    put(puff(1.0 + 0.04 * k), b_, 0.055 + 0.004 * k, -0.6 + 0.11 * (k % 11), to='verbsend')
pops(np.linspace(16.8, 17.5, 8), 0.03, 0.7)                                 # the rest shrink back, newest first
put(riser(2.6 * BEAT, 300, 6000), 15.6, 0.24, to='verbsend')                # into the drop
put(swell(0.6 * BEAT), 17.6, 0.4)
peak(18.2, 'C+', 1.0)                                                       # 「So，我们做了一个 Assistant」 — first peak
for k, b_ in enumerate((18.7, 19.15, 19.6)):                                # Redesign / Agent Workflow / for everyone
    put(stab(tuple(tone(b_, j, 64) for j in range(3)) + (tone(b_, 2 + k, 67),), 0.6), b_, 0.11, -0.2 + 0.2 * k, to='verbsend')
groove(18.5, 22.0, lvl=1.0, arp16=True)
put(hat(True), 18.5, 0.24, 0.25)
shimmer(19.2, 1.0, 14, 0.035)                                               # the dashed circle fades in
put(whoosh(0.6 * BEAT), 21.4, 0.08, 0.2)

# ================= 20-orbit: ring → spiral → Orbit mark → flip (b21.6–28.2) =================
section('20-orbit')
chords((22, 'Am'), (24, 'F'))
padlvl(22.0, 0.16, 1700)
padlvl(25.3, 0.18, 2000)
put(swell(2.2 * BEAT), 21.6, 0.3)                                           # ring tightens into the spiral
groove(22.0, 26.4, clap_on=False, lvl=0.84)
arp(22.4, 25.3, 0.5, 0.07, base=69, span=6, accel=0.25)                     # grows and rises, the spin speeds up
put(bell(tone(25.3, 0, 84), 2.6), 25.3, 0.12, 0.0, to='verbsend')           # the mark stands (b25.3): F-chord tones
put(bell(tone(25.3, 2, 72), 2.6), 25.3, 0.08, -0.2, to='verbsend')
put(boom(2.0, 46, 30), 25.3, 0.2, to='verbsend')
put(whoosh(1.5 * BEAT), 25.9, 0.12, 0.2)                                    # the flip to the top view
for k in range(16):                                                         # dial ticks drawn clockwise (b26.6–27.8)
    put(tick(), 26.6 + 1.2 * k / 16, 0.035, -0.6 + 0.08 * k)

# ================= 30-persona: compass, the scrolling analysis column, reveal (b26.4–41.2) =================
section('30-persona')
chords((26.4, 'G'), (28, 'Am'), (32, 'F'), (36, 'C'), (40, 'G'))
padlvl(26.4, 0.17, 1900)
padlvl(28.0, 0.17, 2100)
padlvl(40.6, 0.16, 2100)
groove(26.4, 28.0, style='half', clap_on=False, lvl=0.84)
put(swell(0.6 * BEAT), 27.4, 0.36)
groove(28.0, 41.2, lvl=0.96, arp16=True)                                    # full groove from b28
put(crash(2.0), 28.0, 0.12, -0.2)
roll(28.6, 5, 0.06, 0.25, 64, 1.2)                                          # the bud slows, lands on your type (b29.6)
for k in range(10):                                                         # 精准识别你的交互特征 decodes
    put(key_click(), 29.35 + 0.055 * k, 0.025, 0.2)
put(whoosh(1.4 * BEAT), 31.4, 0.1, -0.3)                                    # compass slides left (b31.4–32.8)
shimmer(32.6, 1.0, 10, 0.02)                                                # the sectors flash in turn
for k, tk in enumerate((33.7, 34.8, 35.9, 37.0)):                           # each evidence row locks: a tick + a chord tone
    for j in range(5):
        put(key_click(), tk - 1.2 * np.sqrt((j + 1) / 6), 0.03, 0.35)       # the flap rolls, slowing
    put(tick(1.4), tk, 0.08, 0.3)
    put(blip(tone(tk, k + 1, 76), 0.4), tk, 0.06, 0.3, to='verbsend')
put(swell(0.5 * BEAT), 37.5, 0.32)
put(kick(0.5, 1.1), 38.0, 0.45, to='kick')                                  # reveal: DIMV from the centre out
put(stab(tuple(tone(38.0, j, 64) for j in range(4)), 1.4), 38.0, 0.14, to='verbsend')
put(crash(2.0), 38.0, 0.1, 0.2)
roll(38.3, 4, 0.045, 0.15, 69, 1.0)                                         # petals change to your ratios
put(whoosh(1.0 * BEAT), 41.0, 0.12, 0.3)                                    # column leaves, the dial fades

# ================= 40-recs: six recommendations, two counters (b39.4–58.1) — peak on the last entry =================
section('40-recs')
chords((44, 'Am'), (48, 'F'), (52, 'C'), (54.5, 'G'), (56.5, 'Am+'))         # … V → deceptive Am9 at the peak
padlvl(41.0, 0.17, 2200)
padlvl(54.5, 0.18, 2600)
padlvl(56.5, 0.20, 2600)
groove(39.4, 56.5, lvl=0.98, arp16=True)
ARR = [41.5 + 3.0 * n for n in range(6)]                                    # entry n reaches the centre line
EV = [40.6 + 0.4] + [a - 1.9 + 0.4 for a in ARR[1:]]                         # its type word wipes in, its counter rolls
for n, e in enumerate(EV):
    put(whoosh(0.5 * BEAT), e - 0.3, 0.04, -0.5)                            # the links draw to the card (air, no pitch)
    if n < 5:
        put(pluck(tone(e, (0, 2, 1, 3, 2)[n], 72), 0.6), e, 0.09, -0.2, to='verbsend')
    counter(e, 1.2)
put(swell(0.5 * BEAT), 56.0, 0.3)
peak(56.5, 'Am+', 0.95, 0.6)                                                # Thinking reaches the centre
groove(56.5, 58.1, lvl=0.9, arp16=True)
put(whoosh(1.1 * BEAT), 57.0, 0.12, 0.2)                                    # the column speeds up and leaves

# ================= 50-tools: merge, session trajectory, studio (b55.0–72.2) =================
section('50-tools')
chords((55, 'Am'), (58, 'F'), (62, 'C'), (66, 'G'), (70, 'C'))
padlvl(55.0, 0.16, 1700)
padlvl(65.8, 0.17, 2000)
padlvl(70.6, 0.17, 2000)
put(whoosh(1.4 * BEAT, down=True), 55.0, 0.24, 0.0)                         # five dots merge into one
groove(55.0, 72.2, style='half', lvl=0.82, arp16=True, bed=0.2)             # half time under the trajectory and studio
for k, b_ in enumerate((55.6, 57.2, 58.65, 60.5, 62.5)):                    # phase pills on the playhead: 探索 … 验证
    put(pluck(tone(b_, (0, 1, 2, 1, 3)[k], 72), 0.5), b_, 0.06, -0.3 + 0.15 * k, to='verbsend')
    put(puff(), b_, 0.03, -0.3 + 0.15 * k, to='verbsend')
put(whoosh(1.4 * BEAT), 64.1, 0.1, -0.3)                                    # trajectory out, studio in
put(press(), 65.8, 0.16, 0.2)                                               # click 开始生成
put(blip(tone(65.8, 0, 72), 0.4), 65.8, 0.07, 0.2, to='verbsend')
for b_ in (65.95, 66.45, 66.95, 69.85, 70.3):                               # run steps (soft ticks)
    put(tick(1.2), b_, 0.06, 0.3)
for k in range(1, int(2.6 * 10)):                                           # SKILL.md typed at an even rate (b67.05–69.65)
    put(key_click(), 67.05 + k / 10, 0.035 + 0.015 * rng.random(), 0.3 * (rng.random() - 0.5))
for j, g in enumerate((0.1, 0.07, 0.045)):                                  # ✓ done (b70.75): C-chord bell
    put(bell(tone(70.75, 2 * j, 72), 2.0), 70.75, g, 0.1, to='verbsend')
put(whoosh(1.1 * BEAT), 71.1, 0.1, 0.2)                                     # cards shrink into the dot

# ================= 60-close: ring → compass → spiral → mark (b69.2–79) · end card (b80–89) =================
section('60-close')
chords((69.2, 'F'), (73.2, 'Am'), (75.4, 'F'), (77.0, 'G'), (80.0, 'C+'), (84.0, 'F/C'), (86.0, 'C+'))
padlvl(69.2, 0.17, 1700)
padlvl(77.0, 0.18, 2000)
padlvl(80.0, 0.22, 2200)
padlvl(86.0, 0.20, 1800)
put(whoosh(1.0 * BEAT), 69.2, 0.12, -0.2)                                   # the merged dot spirals out
shimmer(69.4, 1.6, 12, 0.03)                                                # the ring draws on
groove(69.2, 75.4, style='half', clap_on=False, lvl=0.72, bed=0.2)
roll(71.04, 5, 0.05, 0.1, 60)                                               # the ring opens into the compass
roll(71.6, 4, 0.04, 0.08, 69)                                               # your type's flower
put(swell(1.2 * BEAT), 74.2, 0.22)                                          # it folds back into the ring
groove(75.4, 78.0, kick_on=False, clap_on=False, lvl=0.74, bed=0.18)        # pulse stays, the floor drops out
arp(75.4, 78.0, 0.5, 0.06, base=67, span=6, accel=0.25)                     # the spiral grows and rises (as at b22.4)
put(riser(2.4 * BEAT, 300, 5000), 75.6, 0.18, to='verbsend')
put(boom(2.4, 48, 28), 78.2, 0.22, to='verbsend')                           # the mark stands
put(stab(tuple(tone(78.2, j, 62) for j in range(4)), 1.6), 78.2, 0.12, to='verbsend')
groove(78.0, 79.75, style='half', clap_on=False, lvl=0.7, bed=0.18)
put(swell(0.7 * BEAT), 79.3, 0.36)
peak(80.0, 'C+', 0.95, 0.8)                                                 # end card — third peak
groove(80.5, END - SH, lvl=0.74, arp16=True, bed=0.18)                      # groove runs under the end card
shimmer(80.0, 1.4, 8, 0.02)                                                 # 「Orbit」 comes out of the blur
for k, w in enumerate((0, .24, .48, .74, .98, 1.22, 1.46)):                 # An Assistant Redesign for everyone & every
    b_ = 80.9 + w
    put(blip(tone(b_, k % 4, 72), 0.3), b_, 0.03, -0.45 + 0.15 * k, to='verbsend')
for i, m in enumerate(AG):                                                  # 「agent」 (b82.62): the opening badges sweep the row
    b_ = 82.62 + 0.16 * i
    put(blip(q(m + 12, b_), 0.7), b_, 0.1, -0.6 + 0.3 * i, to='verbsend')
FADE = (END - 1.8, END)                                                     # everything decays to 0 by END


# ---------------- render the grid layers: groove, pads ----------------
def render_groove():
    spans = [list(g) for g in GROOVE]                   # definition order: a later span wins an overlap
    by_start = sorted(spans, key=lambda s: s[0])
    breath = (17.6 + SHIFT['15-redesign'], 18.0 + SHIFT['15-redesign'])
    for cur, nxt in zip(by_start[:-1], by_start[1:], strict=True):   # bridge a small gap a SHIFT leaves between sections
        if 0 < nxt[0] - cur[1] < 4 and not breath[0] <= cur[1] <= breath[1]:
            cur[1] = nxt[0]
    lo = min(s[0] for s in spans)
    hi = max(s[1] for s in spans)
    steps = np.arange(np.ceil(lo * 4 - 1e-9), np.ceil(hi * 4 - 1e-9)) / 4
    owner = []
    for b in steps:
        own = None
        for s in spans:
            if s[0] - 1e-9 <= b < s[1] - 1e-9:
                own = s[2]
        owner.append(own)
    for bi, p in zip(steps, owner, strict=True):
        if p is None:
            continue
        lvl, ph, frac = p['lvl'], bi % 4, bi % 1
        kicks = (0, 1, 2, 3) if p['style'] == 'four' else (0, 2.5)
        claps = (1, 3) if p['style'] == 'four' else (2,)
        if p['kick_on'] and any(abs(ph - k) < 1e-6 for k in kicks):
            putf(kick(), bi, (0.85 if p['style'] == 'four' else 0.72) * lvl, to='kick')
        if p['clap_on'] and any(abs(ph - k) < 1e-6 for k in claps):
            putf(clap(), bi, 0.42 * lvl, 0.0, to='verbsend')
        if p['hats']:
            if abs(frac - .5) < 1e-6:
                putf(hat(True), bi, 0.32 * lvl, 0.25)
            else:
                putf(hat(False), bi, (0.24 if frac == 0 else 0.15) * lvl, -0.3)
        ch = chord_f(bi)
        if p['bass'] and abs(frac - .5) < 1e-6:
            putf(bass_note(CH[ch][1] + (12 if ph in (1.5, 3.5) else 0), BEAT * 0.45), bi, 0.62 * lvl, to='duck')
        if p['arp16']:                                   # soft sixteenth chord-tone ostinato, the same shape all film
            tones = [m for m in range(72, 90) if m % 12 in PCS[ch]][:3]
            k = int(round(bi * 4)) % 4
            putf(pluck((tones[0], tones[1], tones[2], tones[1])[k], BEAT * 0.4), bi, 0.07 * lvl, 0.35 if k % 2 else -0.35, to='verbsend')
        if p['bed'] and abs(frac - .5) < 1e-6:
            putf(shaker(), bi, p['bed'] * 0.7, 0.5)
    # sustained sub under the half-time spans: one note per run of owned steps, split at chord changes
    cuts = sorted({s for s, _ in PROG})
    run0 = None
    for j in range(len(steps) + 1):
        p = owner[j] if j < len(steps) else None
        b = steps[j] if j < len(steps) else steps[-1] + .25
        prev = owner[j - 1] if j else None
        boundary = run0 is not None and (p is not prev or any(abs(b - c) < .13 for c in cuts))
        if boundary:
            d = (b - run0) * BEAT + 0.04
            t = tt(d)
            r = CH[chord_f(run0)][1] + 12
            x = np.sin(2 * np.pi * midi(r) * t) * np.clip(t * 12, 0, 1) * np.clip((d - t) * 12, 0, 1)
            putf(x, run0, prev['bed'], to='duck')
            run0 = None
        if run0 is None and p is not None and p['bed']:
            run0 = b


def render_pads():
    prog = sorted(PROG)
    pts = sorted(PADLVL)
    xs = [at(b) for b, _, _ in pts]
    gain = np.interp(np.arange(N), xs, [g for _, g, _ in pts])
    xover = 0.5                                          # beats each pad overlaps the next (crossfade)
    for i, (s, c) in enumerate(prog):
        e = prog[i + 1][0] if i + 1 < len(prog) else END
        if e <= s:
            continue
        cut = float(np.interp(at(s), xs, [f for _, _, f in pts]))
        start = max(0.0, s - xover / 2)
        d = (e - start + xover) * BEAT
        sig = pad(CH[c][0], d, cut, att=xover * BEAT, rel=xover * BEAT)
        i0 = at(start)
        g = gain[i0:i0 + len(sig)]
        putf(sig[:len(g)] * g, start, 1.0, to='duckverb')


render_groove()
render_pads()

# ---------------- mix ----------------
kl = bus('kick')[0]
kenv = np.abs(signal.hilbert(lp(kl, 120)))
duck = 1 - 0.6 * np.clip(lp(kenv, 12, 1) * 2.2, 0, 1)

ir_t = tt(2.4)
ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 2.6)
ir = lp(ir, 5500)
ir /= np.sqrt(np.sum(ir ** 2))

out_l = bus('dry')[0] + bus('kick')[0] + bus('verbsend')[0] + (bus('duck')[0] + bus('duckverb')[0]) * duck
out_r = bus('dry')[1] + bus('kick')[1] + bus('verbsend')[1] + (bus('duck')[1] + bus('duckverb')[1]) * duck
send_l = bus('verbsend')[0] + bus('duckverb')[0] * duck * 0.6
send_r = bus('verbsend')[1] + bus('duckverb')[1] * duck * 0.6
out_l += signal.fftconvolve(send_l, ir)[:N] * 0.3
out_r += signal.fftconvolve(send_r, np.roll(ir, 211))[:N] * 0.3

mix = np.stack([out_l, out_r])
for b0, b1, b2, b3, fc in LPF:                      # low-pass automation: zero-phase copy, crossfaded in and out
    w = np.interp(np.arange(N), [at(b0), at(b1), at(b2), at(b3)], [0, 1, 1, 0], left=0, right=0)
    sos = signal.butter(2, fc, 'low', fs=SR, output='sos')
    mix = mix * (1 - 0.8 * w) + signal.sosfiltfilt(sos, mix) * 0.8 * w
mix = hp(mix, 25)
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.6) / np.tanh(1.6)
p = np.clip((np.arange(N) - at(FADE[0])) / (at(FADE[1]) - at(FADE[0])), 0, 1)
mix *= 0.5 * (1 + np.cos(np.pi * p)) * 0.85         # cosine fade to exactly 0 at END, silence in the tail

os.makedirs(os.path.join(os.path.dirname(__file__), 'out'), exist_ok=True)
path = os.path.join(os.path.dirname(__file__), 'out', 'soundtrack.wav')
with wave.open(path, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype('<i2').tobytes())
print('wrote', path, f'{N / SR:.2f}s ({END} beats = {END * BEAT:.2f}s + {TAIL}s tail), peak {np.max(np.abs(mix)):.3f}')
# each scene's start in its own beats (+ SHIFT = film beats); a section runs to the next one's start
START = [('10-intro', 0), ('15-redesign', 11.8), ('20-orbit', 21.6), ('30-persona', 26.4), ('40-recs', 39.4),
         ('50-tools', 55.0), ('60-close', 69.2)]
FILM = [(n, b + SHIFT[n]) for n, b in START] + [('', END)]
for (name, b0), (_, b1) in zip(FILM[:-1], FILM[1:], strict=True):
    seg = mix[:, at(b0):at(b1)]
    print(f'  {name:12s} b{b0:5.1f}-{b1:5.1f}  peak {np.max(np.abs(seg)):.3f}  rms {np.sqrt(np.mean(seg ** 2)):.3f}')
