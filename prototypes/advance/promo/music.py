"""Soundtrack for the Orbit promo (v18.6), synthesised from scratch on the film's beat grid (132 BPM).

    uv run --with numpy --with scipy python promo/music.py   ->  promo/out/soundtrack.wav

One key, one loop. Everything is in C major / A minor on a warm vi–IV–I–V loop, voiced so every chord keeps E on top:
Am7 (A C E G) · Fmaj7 (F A C E) · Cadd9 (C E G D) · G6 (G B D E). The two lifts — 「So，我们做了一个 Assistant」 (film b28)
and the kit reveal of the end card (film b119) — are IV → V → I cadences onto a wide, bright Cadd9; the 「Orbit·知音」
reveal in 20-orbit and the persona reveal also land on I, and the recommendations peak is a deceptive V → Am9.
Every pitched cue (badges, plucks, stabs, arps, bells, letters, entry notes) is quantised to the chord sounding at its
beat (`q()` / `tone()`), there are no glides, semitone rubs or chromatic slides, and rapid events (word settles, bubble
pops, keystrokes, counter ticks, dial ticks, flap rolls) are soft unpitched textures under the groove, so they never form a
melody. The petal-by-petal flower changes are gentle rolled chords; the closing stroke is a rising filtered swell.
The v17.7 Agent-dot morphs get their own 'morph' bus: a light chord-tone bell / pluck for a single morph, an airy
breath for rapid ones (tails, caret pulses, ticks, petal sweeps), a soft knock for the pointer press and pin stabs, a
chord-tone shimmer for the spark and a low swell on the root for orb splits / merges; the run prints each cue's margin
under the rest of the mix (≥ 10 dB).

SHIFT-aware: every cue below is written in its scene file's own beats inside `section('<scene>')`; put(), the chord
timeline, the groove spans and the pad-level points all add SHIFT[scene] (the same table as promo.js). Chords change
on whole or half film beats where an event lands and pads crossfade across every change, so a cue that moves a little
still sits on the right harmony; the groove is laid on the absolute film grid from per-section spans (a later span wins
an overlap, a gap < 4 beats left by a SHIFT is bridged, except the 1-beat BREATH before 「So，」). END is the
close's own END (CLOSE_END) + SHIFT of 60-close; the groove stops on agent ✓4 (LAST) and the last Cadd9 + C ring out to END.
v18.6: back to the v17.7 sound (groove, kick, bass, pads, arp16, crash levels, plain master: high-pass, normalise, soft
clip) with every cue kept on the v18.5 picture (SHIFT, TURN0, PIT / ARR / EV / PO, CUT, the new landings). Dropped from
v18.1–18.5: the master gain arc and EQ shelves, the pad side-chains (lead, typing), the kick / clap / open-hat removal
around picture hits, the hat muting while typing and the lead-forward ×4.4 mix. The motif lead stays as a quiet hook
(×1, no shelf, no ping-pong) that rides the groove; the keystrokes are +7.5 dB over v17.7's keys bus (dry) so every typed
character reads. Coherence: the groove runs continuously from b7 to agent ✓4 — the only breath is the v17.7 one before
「So，」; the DIMV and payoff breaths are gone (their swells lead into the hits on the grid) and the end resolves G → C on
agent ✓4 with a final button, the Cadd9 and a C2 pedal ringing into the fade.
"""
import os
import wave

import numpy as np
from scipy import signal

SR = 48000
BPM = 132
BEAT = 60 / BPM
# = SHIFT in promo.js: each scene plays this many beats later (the integrator fills these in; all cues follow)
SHIFT = {'10-intro': 0, '15-redesign': 6.9, '20-orbit': 11.3, '30-persona': 16.9, '40-recs': 22.9, '50-tools': 31.7, '60-close': 37.7}
TURN0 = 80.4                  # scenes/60-close.js TURN0 (v18.5: 81.0 -> 80.4, the wordmark turn lands at film 118.1–118.3); every close cue after it follows
CLOSE_END = 94.0              # = END of 60-close in its own beats (unchanged: the film stays 131.7 beats)
FADE0 = 92.2                  # v18.5 fixed (no longer TURN0 + 11.2): the groove stops here; the last Cadd9 and C ring out into the fade
END = CLOSE_END + SHIFT['60-close']   # film beats: 131.7 = 59.86 s, must stay < 60 s
TAIL = 1.0                     # seconds of silence after END, so the mux never cuts a sample short
N = int((END * BEAT + TAIL) * SR)
rng = np.random.default_rng(7)
BUS = {}   # name -> (L, R), for sidechain and reverb sends
SH = 0     # SHIFT of the section being written
SCENE = ''


def section(name):
    global SH, SCENE
    SH = SHIFT[name]
    SCENE = name


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
BREATHS = []     # (film b0, film b1): deliberate 1-beat drops before a peak (no groove, never bridged)
EXT = {'Am': {2}, 'F': {7, 2}, 'C': {9}, 'G': {9}, 'C+': {9}, 'F/C': {7}, 'Am+': {2}}   # lead-safe colour tones (9ths / 6ths)


def breath(b0, b1):
    BREATHS.append((b0 + SH, b1 + SH))


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


def lq(m, b):
    """Lead quantiser: chord tones plus the chord's safe 9th / 6th, so the motif E G A C keeps its shape over every chord."""
    ch = chord_f(b + SH)
    pcs = set(PCS[ch]) | EXT.get(ch, set())
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
    click += bp(noise(d), 2500, 5000) * np.exp(-t / 0.006) * 0.25 * 10 ** (-18 / 20) * 4   # v18.7 a 6 ms 2.5–5 kHz beater click (heard on laptop speakers)
    return np.tanh(hp(body + click, 35) * 1.5)                             # v18.8 35 Hz HPF on the kick only, before the drive (no phase overshoot)


def tom(m, d=0.32):
    t = tt(d)
    f = midi(m) * (1 + 0.5 * np.exp(-t * 30))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)
    return np.tanh(1.4 * (body + 0.25 * bp(noise(d), 1500, 4500) * np.exp(-t * 60)))


def clap():
    d = 0.35
    t = tt(d)
    env = np.zeros_like(t)
    for k, o in enumerate((0, 0.011, 0.022)):
        env += (t >= o) * np.exp(-(t - o).clip(0) * (90 if k < 2 else 16))
    n = noise(d)
    return (bp(n, 900, 2600) + 0.6 * bp(n, 2600, 5000)) * env * 0.8    # v18.7 a little 2.6–5 kHz snap (v18.8 .35 → .6)


def hat(open_=False):
    d = 0.3 if open_ else 0.06
    t = tt(d)
    n = noise(d)
    return (hp(n, 7500, 4) + 0.3 * bp(n, 3000, 6000)) * np.exp(-t * (12 if open_ else 70)) * (0.42 if open_ else 0.34) * 10 ** (2 / 20)   # v18.7 + a touch of 3–6 kHz; v18.8 +2 dB


def shaker(mid=False):
    if mid:                                                                 # v18.8 the 16th shaker sits lower (2.5–7 kHz): laptop-speaker pulse
        return bp(noise(0.06), 2500, 7000) * np.exp(-tt(0.06) * 70)
    return bp(noise(0.08), 5000, 11000) * np.exp(-tt(0.08) * 50)


def blip(m, d=0.5):
    t = tt(d)
    f = midi(m)
    s = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    return s * np.exp(-t * 8) * np.minimum(1, t * 300)


def pluck(m, d=0.4):
    t = tt(d)
    s = saw(midi(m), t, (-6, 6))
    return (lp(s, 2200) + 0.4 * bp(s, 2500, 5000)) * np.exp(-t * 10) * np.minimum(1, t * 300)   # v18.7 a little presence (v18.8 .18 → .4)


def bass_note(m, d):
    t = tt(d)
    s = saw(midi(m), t, (-5, 5), phases=(0, .25)) + 0.6 * np.sin(2 * np.pi * midi(m) * t)
    env = np.minimum(1, t * 300) * np.exp(-t * 2.2) * np.clip((d - t) * 60, 0, 1)
    x = lp(s, 480, 4)
    x = np.tanh(2.5 * x) / np.tanh(2.5)                                   # v18.7 soft harmonic saturation, so the line is heard on small speakers …
    x = x + 10 ** (-12 / 20) * lp(saw(2 * midi(m), t, (-4, 4)), 900)      # … plus its octave at −12 dB (120–400 Hz)
    x = x + 10 ** (-14 / 20) * bp(np.tanh(3 * s), 700, 2500)              # v18.8 a parallel 0.7–2.5 kHz drive layer at −14 dB: the bass rhythm on laptop speakers
    return x * env * 0.9                                                    # low band kept at the v17.7 level


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
    return np.tanh(hp(body + hit, 35) * 1.3)                              # v18.8 35 Hz HPF, before the drive


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


def lead(m, d=0.6, cutoff=3000):
    """The one melodic voice: sine + .3 triangle + a little 2nd/3rd harmonic (so laptops carry it), 15 ms attack, 5 Hz / 6 cent vibrato."""
    t = tt(d + 0.35)
    vib = 2 ** (6 / 1200 * np.sin(2 * np.pi * 5 * t) * np.clip(t / 0.25, 0, 1))
    ph = np.cumsum(midi(m) * vib) / SR
    tri = 2 * np.abs(2 * (ph % 1) - 1) - 1
    s = np.sin(2 * np.pi * ph) + 0.3 * tri + 0.22 * np.sin(4 * np.pi * ph) + 0.08 * np.sin(6 * np.pi * ph)
    env = np.minimum(1, t / 0.015) * np.exp(-t * 0.9) * np.clip((d + 0.35 - t) / 0.35, 0, 1) ** 2
    return lp(s, cutoff) * env


M = (76, 79, 81, 76)            # the motif, from the AG badges: E5 G5 A5 (held) E5
M_T = (0, 0.5, 1.0, 2.0)        # onsets in beats; A is held
Q_N, Q_T = (76, 79, 81, 79, 76, 74), (0, 0.5, 1.0, 2.5, 3.0, 3.5)   # v18.5 the theme's antecedent: E G A(held) G E D, open on D
R_N, R_T = (76, 79, 81, 84, 83, 81), (0, 0.5, 1.0, 2.0, 2.5, 3.0)   # … and its consequent: E G A C B A, closed


def motif(b, gain, notes=M, times=M_T, scale=1.0, octave=0, held=None, cutoff=3000, pan=0.1):
    """Play a motif phrase on the lead (scene beats); each note quantised by lq(), durations run to the next onset."""
    for k, (m, o) in enumerate(zip(notes, times, strict=True)):
        bk = b + o * scale
        nxt = (times[k + 1] - o) * scale if k + 1 < len(times) else (held or 1.5)
        put(lead(lq(m + 12 * octave, bk), nxt * BEAT, cutoff), bk, gain, pan, to='lead')


def settle(g=1.0):
    """A word steps in and settles: a soft unpitched click with a small low body."""
    t = tt(0.1)
    return (hp(noise(0.1), 4000) * np.exp(-t * 120) * 0.35 + np.sin(2 * np.pi * 120 * t) * np.exp(-t * 40) * 0.5) * g


def sweep_pad(ms, d, rel):
    """A pad that swells while its low-pass opens (400 Hz → 4.5 kHz) over d seconds, then releases over rel seconds."""
    t = tt(d + rel)
    s = sum(saw(midi(m), t, (-10, -3, 4, 11)) for m in ms) / np.sqrt(len(ms)) / 2
    p = np.clip(t / d, 0, 1)
    a, b, c = lp(s, 400), lp(s, 1350), lp(s, 4500)
    out = np.where(p < .5, a * (1 - 2 * p) + b * 2 * p, b * (2 - 2 * p) + c * (2 * p - 1))
    return out * p ** 1.6 * np.clip((d + rel - t) / rel, 0, 1) ** 2


def grain(b0, b1, n, gain):
    """Dust: sparse unpitched clicks."""
    for _ in range(n):
        put(tick(), b0 + (b1 - b0) * rng.random(), gain * (0.4 + 0.6 * rng.random()), rng.random() * 1.6 - 0.8, to='verbsend')


def shimmer(b0, dur, n, gain, base=84):
    """Glitter made of chord tones only, scattered over dur beats."""
    for i in range(n):
        b = b0 + dur * (i / n) ** 0.7 + 0.03 * rng.random()
        put(blip(tone(b, int(rng.integers(0, 4)), base), 0.15), b, gain * (0.5 + 0.5 * rng.random()), rng.random() * 1.4 - 0.7, to='verbsend')


def hash01(i, seed=1):
    """= hash01 in scenes/00-kit.js."""
    x = np.sin(i * 127.1 + seed * 311.7) * 43758.5453
    return x - np.floor(x)


def type_on(k0, text, seed):
    """= typeOn in scenes/10-intro.js: the scene beats of each typed character (K[0] = k0, then .22–.28 apart)."""
    K = [k0]
    for k in range(1, len(text)):
        K.append(K[-1] + 0.22 + 0.06 * hash01(k, seed))
    return K


def keystroke(bright=1.0, full=0.0):
    """One soft key press, unpitched: a short band-passed noise click + a tiny low thump; full > 0 = the send key."""
    d = 0.09
    t = tt(d)
    click = bp(noise(d), 1800 * bright, 5200 * bright) * np.exp(-t * (520 - 180 * full)) * np.minimum(1, t * 4000)
    thump = np.sin(2 * np.pi * (115 - 20 * full) * t) * np.exp(-t * (90 - 30 * full)) * (0.35 + 0.45 * full)
    return click * 0.8 + thump


def keys(K, gain=0.45, pan=-0.1):
    """A keystroke on every beat in K, each a little different in level, brightness and timing (≤ 8 ms)."""
    for b in K:
        jit = (rng.random() - 0.5) * 2 * 0.008 / BEAT
        put(keystroke(0.8 + 0.4 * rng.random()), b + jit, gain * (0.7 + 0.5 * rng.random()), pan + 0.1 * (rng.random() - 0.5), to='keys')


def send_key(b, gain=0.58, pan=-0.1):
    put(keystroke(0.9, 1.0), b, gain, pan, to='keys')


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


def roll(b0, n, gain, gap=0.1, base=60, d=1.0, soft=False):
    """A rolled chord of chord tones (petals opening); soft = bells instead of plucks."""
    for i in range(n):
        m = tone(b0, i, base)
        put(bell(m, d) * 0.8 if soft else pluck(m, d), b0 + i * gap, gain, -0.4 + 0.8 * i / max(1, n - 1), to='verbsend')


def groove(b0, b1, style='four', lvl=1.0, kick_on=True, clap_on=True, hats=True, bass=True, arp16=False, bed=0.0):
    GROOVE.append((b0 + SH, b1 + SH, dict(style=style, lvl=lvl, kick_on=kick_on, clap_on=clap_on, hats=hats,
                                         bass=bass, arp16=arp16, bed=bed)))


def peak(b, ch, gain=1.0, crash_gain=1.0, boom_gain=1.0, kick_gain=1.0):
    """An energy peak: boom + kick + chord stab + crash (stab voiced from the chord itself).
    v18.7 boom_gain: the two feature peaks keep a lighter sub boom so their transient does not set the normalisation
    (the whole film would drop with it); they read loud through stab, crash and the pickup instead."""
    v = CH[ch][0]
    put(boom(3.0), b, 0.5 * gain * boom_gain, to='verbsend')
    put(kick(0.6, 1.2), b, 0.9 * gain * kick_gain, to='kick')
    put(stab(v + (v[0] - 12,), 2.2), b, 0.34 * gain, to='verbsend')
    put(crash(3.0), b, 0.32 * gain * crash_gain, 0.2)
    put(crash(2.5), b, 0.22 * gain * crash_gain, -0.3)


AG = (64, 67, 69, 72, 76)   # the five Agent badges cc / cx / gm / ds / cp: E G A C E (Am7 / Cadd9 tones)
LETTERS = (76, 79, 81, 84, 81, 79, 76)   # the 7-letter phrase E G A C | A G E, the same at both wordmark moments


def words(beats, gain, pan=0.0):
    """Word-by-word type (v17.5): each phrase opens in .24 beat and settles — a soft unpitched tick with a little body."""
    for k, b in enumerate(beats):
        put(settle(), b + 0.03, gain, pan + 0.12 * (k % 3 - 1))


# ================= 10-intro: 1a 用 AI Agent，正在成为每个人的日常 (b0–6.6) · 1b 从想法到交付 (b7–11.8) · 1c We Are Redesigning Everything
section('10-intro')
chords((0, 'Am'), (7, 'F'), (11.25, 'C'), (13.5, 'G'))                    # v18.6 back to the v17.7 loop: 1c rides V into 1d's vi
padlvl(0, 0.24, 800)
padlvl(3.5, 0.32, 1300)                                                     # v18.7 the pad swells and opens while the line is read (b3.5–6.9) …
padlvl(6.0, 0.34, 1800)
padlvl(6.9, 0.26, 1500)
padlvl(7.0, 0.15, 1300)
padlvl(13.2, 0.15, 1600)
put(bass_note(33, 6.6 * BEAT), 0, 0.38, to='duck')
grain(0, 6.6, 24, 0.05)
for i, m in enumerate(AG):                                                  # the cluster pops (b0.2 + .12 i): E G A = the motif's first statement,
    put(blip(q(m + 12, 0.2), 0.6), 0.2 + 0.12 * i, 0.11 if i < 3 else 0.06, -0.6 + 0.3 * i, to='verbsend')   # the last two pops stay under the words
put(lead(lq(81, 0.5), 2.1 * BEAT, 2000), 0.5, 0.035, 0.0, to='lead')       # the first line is sung: A under 「AI Agent，正在成为每个人的」
put(lead(lq(76, 2.6), 0.9 * BEAT, 2000), 2.6, 0.035, 0.0, to='lead')       # … resolving to E on 「日常」
words((0.5,), 0.07)                                                         # 「AI Agent，」 wipes in (b0.4 + .1, v18.1 one step)
words((1.1, 1.5, 1.95), 0.1)                                                # 「正在」「成为」「每个人的」, each with its settle
put(kick(0.3, 0.7), 2.6, 0.3, to='kick')                                    # 「日常」 stamps in (b2.3) and hits (b2.6)
put(blip(tone(2.6, 2, 64), 0.8), 2.6, 0.06, 0.1, to='verbsend')
for b_ in (3.55, 4.2, 4.85, 5.5, 6.15):                                     # the pen breathes while the line is read (v17.7)
    put(kick(0.25, 0.3), b_, 0.1, to='kick')
    put(shaker(), b_ + 0.02, 0.05, 0.4)
put(riser(2.0 * BEAT, 300, 3000), 5.0, 0.16, to='verbsend')                  # prepares the groove's entry on b7 (v18.7 longer, louder: the build rises into 「从想法」)
for k in range(6):                                                          # v18.7 grid hats on the 8ths (b4.0–6.5), rising, so the 132 BPM pulse is set before b7
    put(hat(False), 4.0 + 0.5 * k, 0.04 + 0.024 * k, -0.3)
for k in range(4):                                                          # … and 16ths over 6.0–6.75
    put(hat(False), 6.0 + 0.25 * k, 0.1 + 0.027 * k, 0.3)
put(bass_note(33, 0.4 * BEAT), 6.5, 0.3, to='duck')
put(bass_note(33, 2.4 * BEAT), 4.0, 0.4, to='duck')                         # v18.7 … over a held A1, no hit
arp(4.0, 6.9, 0.25, 0.035, base=69, span=5, accel=1.0)                      # … and a soft 16th arpeggio fades in under it                        # v18.7 a bass pickup into b7 (no hit)
motif(3.5, 0.034, notes=Q_N, times=(0, 0.5, 1.0, 2.5, 3.0, 3.25), held=0.25, cutoff=2400)   # v18.5 the theme's first half (Q), its open D leans into G at b7.0
put(swell(0.6 * BEAT), 6.0, 0.26)
put(whoosh(0.8 * BEAT), 6.6, 0.12, -0.2)                                    # the lines leave, the pen turns over (∪ → ∩)
groove(7.0, 13.2, clap_on=False, lvl=0.66)                                  # light four on the floor (v17.7)
put(puff(0.8), 7.35, 0.04, 0.0, to='verbsend')                              # v18.5 the box grows out of the pills as title + dots rise (b7.35–8.1)
put(swell(0.75 * BEAT), 7.35, 0.1)
words((6.95, 7.25), 0.09)                                                   # v18.5 「从想法」 match-cuts in on b6.95, 「到交付」 b7.25
K1 = type_on(7.2, '做一个记账 App', 31)                                       # typed key by key (typeOn), b7.2–9.16
S1 = K1[-1] + 0.22                                                          # sent b9.38
K2 = type_on(S1 + 0.17, '写份路演稿', 32)                                    # b9.55–10.54
S2 = K2[-1] + 0.22                                                          # sent b10.76
keys(K1 + K2)
put(lead(lq(79, 7.0), 2.35 * BEAT, 2400), 6.95, 0.04, 0.0, to='lead')        # v18.3 the line sits above the keys: G on 「从想法」 …
put(lead(lq(81, 9.38), 2.0 * BEAT, 2400), 9.38, 0.04, 0.0, to='lead')      # … A on send 1, through the second prompt
put(lead(lq(84, 11.35), 2.3 * BEAT, 2600), 11.35, 0.045, 0.0, to='lead')   # C as the icons burst, carried into 「We」
for b_ in (S1, S2):                                                         # sends: a fuller press
    send_key(b_)
pops((7.85, 7.9, 8.1, 8.8, S1 + 0.15, 10.1, 10.45, S2 + 0.15), 0.11)   # v18.7 .07 → .11       # bubbles rise out of the dots (prompts and sends)
pops((11.7, 11.95, 12.65, 12.8, 13.0), 0.035, 0.7)                          # and retract after the burst (softer, darker)
put(swell(0.6 * BEAT), 10.75, 0.32)                                         # b11.35 the App icons burst out
arp(11.35, 11.75, 0.0333, 0.07, base=72, span=6)                            # one quick upward chord run as they spray
put(pad(CH['C'][0], 1.6 * BEAT, 2800, 0.1, 0.8), 11.35, 0.07, to='verbsend')
shimmer(11.6, 1.0, 8, 0.025)                                                # the halo draws in (b11.6–12.6)
put(whoosh(0.9 * BEAT), 12.95, 0.13, 0.3)                                    # v18.4 the dot slides left into the caret (b13.05–13.65), one long whoosh
groove(13.2, 18.7, lvl=0.82)
for k, b_ in enumerate((13.65, 14.3, 14.8, 15.3)):                          # We (v18.5 b13.65) / Are / Redesigning / Everything
    put(stab(tuple(tone(b_, j, 60) for j in range(3)) + (tone(b_, k, 67),), 0.7 if k < 3 else 1.4), b_, 0.17 + 0.02 * k, -0.15 + 0.1 * k, to='verbsend')
    put(lead(lq(M[0] + (0, 3, 5, 8)[k], b_), (0.5 if k < 3 else 1.6) * BEAT), b_, 0.04, 0.0, to='lead')   # the quiet hook doubles the rise
    put(settle(), b_ + 0.03 if k else 13.75, 0.06, -0.15 + 0.1 * k)        # v18.5 We: the caret forms + ripples on b13.75
put(boom(1.6, 46, 30), 15.3, 0.12, to='verbsend')                           # 「Everything」 + the gloss land
put(crash(2.0), 15.3, 0.14, 0.25)
for b_ in (14.0, 14.5, 15.0, 15.5, 15.85, 16.35, 16.8, 17.25, 17.8, 18.3):  # the caret breathes at rest
    put(tick(), b_, 0.025, 0.5)
put(riser(3.2 * BEAT, 400, 3000), 15.4, 0.06, to='verbsend')                # the icons turn outward (b15.3–18.7)
put(whoosh(0.9 * BEAT), 18.5, 0.14, -0.2)                                   # and fly out (b18.6)
put(lead(lq(76, 17.4), 2.5 * BEAT, 2400), 17.4, 0.055, 0.0, to='lead')      # v18.3 E hands the line into 1d's A (film b20.0)
LPF = [(18.2 + SH, 18.8 + SH, 19.2 + SH, 19.9 + SH, 520)]                   # low-pass dip at the turn into 1d

# ================= 15-redesign: 1d 但，人与 Agent 的交互本身，也需要被重新定义 (b12.8–20.7) · 1e So，我们做了一个 Assistant (b20.6–26.4)
section('15-redesign')
chords((12.6, 'Am'), (15.6, 'F'), (18.6, 'G'), (20.6, 'C+'))               # vi → IV → V → the lift on I as 「So，」 lands (film 19.5 / 22.5 / 25.5 / 27.5)
padlvl(11.8, 0.15, 1300)
padlvl(15.6, 0.16, 1600)
padlvl(18.6, 0.17, 1900)
padlvl(19.85, 0.10, 2400)
padlvl(20.6, 0.20, 2600)
padlvl(25.8, 0.18, 2200)
groove(11.8, 19.85, style='half', lvl=0.82, bed=0.24)                      # v17.7 half time under 1d, into the breath before 「So，」
motif(13.1, 0.042, notes=(81, 79, 76, 74), times=(0, 2, 4, 6), held=2.0, cutoff=2000)   # 1d answers: A G E D, one per 2 beats
put(tick(0.9), 11.8, 0.03, 0.0)                                             # v18.3 the caret falls (.24 beat) …
put(key_click(), 12.04, 0.08, 0.0)
put(tick(1.1), 12.04, 0.05, 0.1)                                          # … and rounds straight into the pill key (b12.04)
put(puff(0.8), 12.5, 0.04, 0.0, to='verbsend')                              # the box grows out of the dots (b12.5)
put(tick(1.0), 12.5, 0.06, -0.1)
put(blip(tone(12.5, 0, 72), 0.4), 12.5, 0.07, -0.1, to='verbsend')
put(swell(0.5 * BEAT), 12.35, 0.14)                                         # v18.5 「但，」 blurs in from film b19.25: a soft attack, no hit …
put(bell(tone(12.35, 0, 69), 1.6), 12.31, 0.055, 0.0, to='verbsend')      # v18.7 .035 → .055: 「但，」 rises out of the dots (film b19.25)
put(pluck(tone(12.85, 0, 72), 0.5), 12.85, 0.07, 0.0, to='verbsend')      # v18.7 「但，」 whole: a clear pitched onset
put(kick(0.35, 0.6), 12.85, 0.15, to='kick')                                 # … and settles alone, the dots flinch (softer)
put(stab(tuple(tone(12.8, j, 57) for j in range(3)), 0.9), 12.85, 0.08, 0.0, to='verbsend')
words((13.12,), 0.1)                                                        # 「人与 Agent 的」 (v18.5 b13.15)
put(tick(1.3), 13.15, 0.08, -0.1)                                            # v18.3 a clear onset ahead of the next key (b13.47)
put(blip(tone(13.4, 1, 72), 0.4), 13.15, 0.1, 0.1, to='verbsend')
words((13.85,), 0.08)                                                       # 「交互本身，」
keys(type_on(12.95, '请你修改', 41) + type_on(14.55, 'fix', 42)                # typed key by key (typeOn), as 15-redesign
     + type_on(15.8, '请你继续', 43) + type_on(17.15, '看清需求', 44))          # 看清需求 is never sent
for b_ in (13.95, 15.26, 16.78):                                            # sends: a fuller press
    send_key(b_)
FIX = [14.1, 14.55, 15.08, 15.41, 15.96, 16.25, 16.5, 16.73, 16.93, 17.12]
for k, b_ in enumerate(FIX):                                                # corrections pile up: denser, a touch brighter
    put(puff(1.0 + 0.04 * k), b_, 0.055 + 0.004 * k, -0.6 + 0.12 * (k % 11), to='verbsend')
words((15.1,), 0.08)                                                        # 「也需要被」
put(kick(0.4, 0.9), 15.9, 0.28, to='kick')                                  # 「重新定义」 drops in and lands (b15.9)
put(stab(tuple(tone(15.9, j, 60) for j in range(4)), 1.2), 15.9, 0.12, 0.1, to='verbsend')
pops((17.88, 18.21, 18.76, 19.05, 19.3, 19.53, 19.7, 19.75), 0.03, 0.7)     # the stream rolls back, the last ones newest first
put(riser(2.6 * BEAT, 300, 6000), 18.0, 0.24, to='verbsend')                # into the drop on 「So，」 (b20.6)
put(whoosh(0.6 * BEAT), 20.1, 0.07, 0.2)                                    # the lines leave, the box sinks, the ring opens
put(swell(0.6 * BEAT), 20.0, 0.4)
breath(19.85, 20.6)                                                         # the pre-drop breath (film b26.75–27.5): no groove
peak(20.6, 'C+', 1.0)                                                       # 「So，」 lands in the ring centre — first peak (film b27.5)
motif(20.6, 0.07, notes=M[:3], times=(0, 0.85, 1.02), held=0.85)  # E on 「So，」, G on 「我们做了一个」 (21.45), A on 「Assistant」 (21.62), held into Redesign
motif(23.6, 0.07, times=(0, 0.5, 1.0, 2.0), held=0.75)                     # again after the cuts: E on the everyone glow (23.6), A held, back to E at 25.6
words((21.42,), 0.06)                                                       # 「我们做了一个」 (b21.45)
put(pluck(tone(21.62, 3, 72), 0.6), 21.62, 0.08, 0.2, to='verbsend')        # 「Assistant」 (b21.62)
put(settle(0.8), 21.5, 0.05, -0.1)                                          # 「So，」 settles in its slot (b21.5)
for k, b_ in enumerate((22.5, 22.9, 23.3)):                                 # Redesign / Agent Workflow / for everyone (hard cuts, v18.2 CUT)
    put(stab(tuple(tone(b_, j, 64) for j in range(3)) + (tone(b_, 2 + k, 67),), 0.6), b_, 0.11, -0.2 + 0.2 * k, to='verbsend')
groove(20.6, 21.62, style='half', lvl=0.9, arp16=True)                      # the drop breathes while the line assembles
groove(21.62, 26.4, lvl=1.0, arp16=True)
put(hat(True), 21.62, 0.24, 0.25)
for j in range(3):                                                           # 「everyone」 glows (b23.6): a soft bell chord
    put(bell(tone(23.6, 2 + j, 72), 1.6), 23.6, 0.035, -0.3 + 0.3 * j, to='verbsend')
put(blip(tone(23.6, 0, 84), 0.6), 23.6, 0.09, 0.0, to='verbsend')          # v18.3 a clear landing on the glow (film b30.5)
put(lp(kick(0.3, 0.6), 500), 23.6, 0.2, to='kick')
shimmer(21.0, 0.7, 14, 0.035)                                               # the dashed circle draws from the beads (b21.0–21.7)
put(whoosh(0.6 * BEAT), 25.8, 0.08, 0.2)                                    # the lines spread out, the circle brightens

# ================= 20-orbit: ring → spiral → 45° icon → kit reveal 「Orbit·知音」 + subtitle → turn back → flip (b21.6–33.8)
section('20-orbit')
chords((21.7, 'Am'), (23.7, 'F'), (25.7, 'C'), (29.7, 'G'))                 # film 33 / 35 / 37 / 41: the wordmark reads on I
padlvl(21.6, 0.16, 1700)
padlvl(24.6, 0.18, 2000)
padlvl(26.25, 0.19, 2400)
padlvl(29.5, 0.17, 2000)
put(swell(0.6 * BEAT), 21.4, 0.2)                                           # the ring tightens and speeds up
groove(21.6, 24.6, clap_on=False, lvl=0.84)
arp(22.2, 24.6, 0.5, 0.07, base=69, span=6, accel=0.25)                     # the spiral grows and rises, the spin speeds up
for m, b_, d_ in ((79, 22.2, 1.2), (81, 23.4, 1.2), (88, 24.6, 1.4)):          # v18.3 the line climbs with it: G A → E6 on the icon
    put(lead(lq(m, b_), d_ * BEAT, 2400), b_, 0.04, 0.0, to='lead')
put(riser(1.3 * BEAT, 400, 3000), 23.3, 0.08, to='verbsend')                # it stands up into the 45° icon
put(boom(2.0, 46, 30), 24.6, 0.18, to='verbsend')                           # the icon stands (b24.6) and turns at once
put(bell(tone(24.6, 0, 84), 2.6), 24.6, 0.09, 0.0, to='verbsend')
put(whoosh(2.2 * BEAT), 24.6, 0.1, -0.2)                                    # the kit turn (×1.5, 2.2 beats), the O slides left
groove(24.6, 29.5, style='half', lvl=0.8, bed=0.2)                          # half time while the wordmark reads (v17.7)
for k in range(7):                                                          # 「rbit·知音」 rise one by one (b26.25 + .242 k)
    b_ = 26.25 + 0.242 * k
    put(bell(lq(LETTERS[k], b_), 1.6), b_, 0.05 - 0.003 * k, -0.45 + 0.15 * k, to='verbsend')
    put(lead(lq(LETTERS[k], b_), (0.242 if k < 6 else 1.5) * BEAT), b_, 0.035, 0.0, to='lead')
    put(settle(), b_, 0.05, -0.45 + 0.15 * k)                               # each letter's own small attack (v18.1; v18.6 .04 → .05, every letter a clear onset)
put(bell(tone(26.7, 0, 60), 2.4), 26.7, 0.05, 0.0, to='verbsend')           # 「你的 AI 协作复盘助手」 floats in (b26.7)
shimmer(26.7, 0.8, 6, 0.02)
for k in range(7):                                                          # the letters retract, last first (b29.5, ×1.5)
    put(tick(), 29.5 + 0.161 * k, 0.03, 0.45 - 0.15 * k)
put(whoosh(1.7 * BEAT), 30.0, 0.08, 0.2)                                    # the O turns back into the icon (b30.0–31.7)
groove(29.5, 33.0, clap_on=False, lvl=0.84)
for b_, g in ((26.7, 0.09), (29.5, 0.07)):                                # v18.3 landings: subtitle (film b38.0), retract (b40.8)
    if b_ < 29:                                                             # v18.7 no small kick at film 40.80: it flammed the 41.0 groove kick
        put(lp(kick(0.3, 0.5), 450), b_, g * 2.2, to='kick')
    put(blip(tone(b_, 1, 79), 0.5), b_, g, 0.15, to='verbsend')
put(whoosh(1.3 * BEAT), 31.7, 0.12, 0.2)                                    # the flip onto the compass (b31.7–33.0)
put(lead(lq(81, 29.5), 2.2 * BEAT), 29.5, 0.06, 0.0, to='lead')             # bridge (film b40.8–45): A on the retract …
put(lead(lq(76, 31.7), 1.5 * BEAT), 31.7, 0.06, 0.0, to='lead')             # … E on the flip, handing over to persona's motif
# v18.7 the flip (film b44.3) no longer takes a small kick (it flammed the 44.0 groove kick); settle + tick + blip carry it
put(settle(0.9), 33.0, 0.06, 0.0)
put(tick(1.5), 33.0, 0.07, 0.15)                                            # v18.5 a bright top on the flip (film b44.3)
put(blip(tone(33.0, 2, 84), 0.4), 33.0, 0.05, -0.1, to='verbsend')

# ================= 30-persona: compass, bud, title, the scrolling analysis column, petal-by-petal changes, reveal (b25.7–45.4)
section('30-persona')
chords((28.1, 'Am'), (32.6, 'F'), (37.1, 'G'), (41.1, 'C'))                # film 45 / 49.5 / 54 / 58: the type is revealed on I
padlvl(26.4, 0.17, 1900)
padlvl(28.1, 0.17, 2100)
padlvl(41.4, 0.25, 2800)                                                    # v18.7 .19 → .25: the pad opens with the reveal
padlvl(44.6, 0.16, 2000)
for k in range(16):                                                         # the dial's ticks draw on (b26.5–27.7)
    put(tick(), 26.5 + 1.2 * k / 16, 0.03, -0.6 + 0.08 * k)
groove(26.4, 28.1, style='half', clap_on=False, lvl=0.84)
put(swell(0.6 * BEAT), 27.5, 0.32)
groove(28.1, 35.6, lvl=0.96, arp16=False)                                   # v17.7 full groove from film b45, no breath before DIMV …
groove(35.6, 41.6, lvl=0.96, arp16=True)                                     # … v18.7 the 16ths enter with the first letter tile: the reveal builds by adding layers
motif(29.1, 0.05, notes=Q_N[:5], times=(0, 0.75, 1.0, 2.0, 3.0), held=1.0)            # v18.5 a rising sequence in dotted rhythm: Q on Am …
motif(33.1, 0.055, notes=(77, 81, 84, 81, 77), times=(0, 0.75, 1.0, 2.0, 3.0), held=1.0)   # … a step up on F …
motif(37.1, 0.06, notes=R_N[:5], times=(0, 0.75, 1.0, 2.0, 2.5), held=0.8)   # … then R on G: E G A C B …
motif(40.4, 0.06, notes=(84, 86), times=(0, 0.6), held=0.6)                 # … B C D step up through the breath into E6 at DIMV
put(lead(lq(76, 28.1), 1.0 * BEAT), 28.1, 0.05, 0.0, to='lead')             # v18.3 E on the dial, into the augmented motif
put(lead(lq(88, 41.60), 2.8 * BEAT), 41.60, 0.09, 0.0, to='lead')          # and the climb tops out on E6 at DIMV
put(crash(2.0), 28.1, 0.12, -0.2)
put(tick(0.9), 27.92, 0.04, 0.3)                                          # v18.5 the badges orbit out and land (b27.94)
put(settle(0.8), 28.4, 0.05, 0.0)                                           # v18.2: the dial settles (b28.4)
roll(28.6, 5, 0.06, 0.25, 64, 1.2)                                          # the bud slows and lands (b29.6)
words((28.97,), 0.08)                                                       # 「读懂你的 Agent 协作人格」 masks in (b29.0)
put(tick(1.0), 29.0, 0.05, -0.1)
for k in range(15):                                                         # 从每个会话里，认出你的协作方式 decodes (15 chars, .04 apart)
    put(key_click(), 29.1 + 0.04 * k, 0.025, 0.2)
put(whoosh(1.4 * BEAT), 32.8, 0.1, -0.3)                                    # the compass slides left (b32.8–34.2)
put(whoosh(0.5 * BEAT), 33.8, 0.04, 0.4)                                    # a link draws to the column
shimmer(34.3, 0.96, 10, 0.02)                                               # the sectors flash in turn
for k, tk in enumerate((35.88, 37.09, 38.30, 39.52)):                       # each letter tile locks: a tick + a chord tone
    for j in range(5):
        put(key_click(), tk - 1.2 * np.sqrt((j + 1) / 6), 0.03, 0.35)       # the flap rolls, slowing
    put(tick(1.4), tk, 0.08, 0.3)
    put(blip(tone(tk, k + 1, 76), 0.4), tk, 0.06, 0.3, to='verbsend')
for s, L in ((35.58, 2.1), (37.68, 2.0), (39.68, 2.0)):                     # SIFT → DIFT → DIMT → DIMV, petal by petal:
    roll(s + 0.14 * L + 0.08, 5, 0.05, 0.11 * L, 60, 2.0, soft=True)        # each change a gentle rolled chord
put(swell(0.6 * BEAT), 40.98, 0.3)
peak(41.60, 'C', 1.1, 1.0, boom_gain=0.45 * 0.95 / 1.1, kick_gain=0.75 * 0.95 / 1.1)   # v18.8 .95 → 1.1 (boom / kick kept at their v18.7 level, out of the normaliser)                                                 # v18.7 reveal: DIMV readable (b41.60 = film 58.5) — the first core-feature peak
for b_, g in ((40.85, 0.14), (41.1, 0.2), (41.35, 0.26), (41.6, 0.34)):     # a 1-beat clap pickup into it, landing with the peak
    put(clap(), b_, g, 0.0, to='verbsend')
put(hat(True), 41.6, 0.3, 0.25)
put(crash(2.5) * np.clip(tt(2.5) / 0.15, 0, 1) ** 2, 41.6, 0.5, -0.15)      # v18.8 the reveal opens wider than the payoffs before it (150 ms bloom: body, not a normaliser-setting transient)
put(sweep_pad(tuple(m + 12 for m in CH['C'][0]), 2.4 * BEAT, 1.0 * BEAT), 41.6, 0.1, to='verbsend')   # v18.7 a held bright C under the reveal (body, not transient)
groove(41.6, 45.4, lvl=1.12, arp16=True, bed=0.24)                         # v18.7 the reveal adds a shaker layer on top of the full groove
put(swell(0.6 * BEAT), 32.2, 0.12)                                          # v18.7 the title FLIPs (film b49.7): a light swell, no hit
words((41.67, 41.82), 0.05, 0.3)                                            # 指挥家 The Conductor · its one-liner
for k, b_ in enumerate((42.27, 42.47)):                                     # 优势 / 盲点 rise in
    put(blip(tone(b_, 2 + k, 76), 0.4), b_, 0.035, 0.35, to='verbsend')
put(whoosh(1.1 * BEAT), 45.0, 0.1, 0.3)                                     # the column leaves, the dial shrinks away

# ================= 40-recs: peel into the column, intro card, six recommendations + two counters (b38.5–63.1) — peak on the last
section('40-recs')
chords((39.1, 'F'), (43.1, 'G'), (45.1, 'Am'), (49.1, 'F'), (53.1, 'C'), (57.1, 'G'), (59.6, 'Am+'), (63.1, 'G'))   # film 62 … 82.5: V → deceptive Am9 on the payoff (v18.4 PO = 59.6)
padlvl(38.5, 0.17, 2000)
padlvl(40.0, 0.16, 1900)
padlvl(45.1, 0.17, 2200)
padlvl(57.1, 0.18, 2600)
padlvl(59.1, 0.15, 2000)
padlvl(59.6, 0.21, 2700)
padlvl(62.6, 0.20, 2500)
for k in range(5):                                                          # the badges peel off the rim row by row (b38.5 + .14 k)
    b_ = 38.5 + 0.14 * k
    put(blip(tone(b_, 4 - k, 72), 0.4), b_, 0.045, -0.4 + 0.2 * k, to='verbsend')
put(whoosh(1.7 * BEAT), 38.5, 0.06, -0.4)                                   # and glide into the column
put(lp(kick(0.3, 0.5), 450), 38.5, 0.18, to='kick')                         # v18.3 landing on the peel (film b61.4)
put(blip(tone(39.85, 3, 79), 0.5), 39.85, 0.08, 0.1, to='verbsend')         # and on line 1 (film b62.75)
put(settle(1.0), 39.85, 0.08, 0.0)
motif(38.5, 0.06, notes=(76, 79, 81), times=(0, 0.5, 1.35), held=2.0)       # bridge (film b61.4–67.9): E on the peel, G on the glide, A on line 1
motif(42.7, 0.05, notes=(84, 81, 79, 76, 74), times=(0, 0.5, 1.0, 1.5, 2.0), held=0.3)   # v18.5 the answer falls C A G E D (inversion of the rise), into the entries at 45.0
groove(39.4, 45.1, style='half', lvl=0.86, arp16=True, bed=0.2)             # the intro card reads over half time
for r, b_ in enumerate((39.85, 39.99, 40.13)):                              # each top row writes one line out of a link:
    put(whoosh(0.3 * BEAT), b_ - 0.3, 0.03, -0.5)                           # 02 · 优化建议 / 根据你的使用习惯，智能推荐 / 提高效率
    put(pluck(tone(b_, 2 + r, 67), 0.8), b_, 0.07, -0.2 + 0.2 * r, to='verbsend')
put(bell(tone(40.0, 4, 72), 2.4), 40.0, 0.05, 0.0, to='verbsend')
shimmer(40.1, 0.8, 6, 0.018)
for w in (41.6, 42.7, 43.8):                                                # the column breathes in three soft waves
    roll(w, 5, 0.02, 0.12, 72, 1.2, soft=True)
put(whoosh(1.1 * BEAT), 44.5, 0.06, -0.3)                                   # the card moves into the eyebrow slot
for b_ in (44.85, 45.0, 45.1, 45.2, 45.35):                                 # the counters come in
    put(tick(), b_, 0.03, 0.45)
PIT, ARR0 = 2.6, 46.0                                                       # = PIT / ARR in scenes/40-recs.js (v18.3: 2.6-beat cards)
ARR = [ARR0 + PIT * n for n in range(6)]
EV = [ARR[n] - (1.9 if n else 1.4) + 0.4 for n in range(6)]                # = EV = LIVE[n][0] + .4: entry n emitted (link, word, counter)
for n, e in enumerate(EV):
    put(whoosh(0.5 * BEAT), e - 0.4, 0.04, -0.5)                            # the links draw to the card (air, no pitch)
    m_ = (AG + (74,))[n] + 12                                        # the entries spell the motif E G A C E → D6 (the 9th over V)
    d_ = (EV[n + 1] - e - 0.1) if n < 5 else (59.6 - e)                      # v18.3 legato: each note runs into the next entry
    put(pluck(lq(m_, e), 0.6), e, 0.09, -0.2, to='verbsend')
    put(lead(lq(m_, e), (d_ * 0.55 if n < 5 else d_) * BEAT), e, 0.06 if n < 5 else 0.085, 0.0, to='lead')
    if n < 5:                                                              # a passing tone halfway, so the phrase keeps rising
        mp = ((AG + (74,))[n + 1] + 12 + m_) // 2
        put(lead(lq(mp, e + d_ * 0.55), d_ * 0.45 * BEAT + 0.05), e + d_ * 0.55, 0.05, 0.0, to='lead')
    if n < 5:                                                              # v18.5 the share rolls from the ✓ (RL = EV + .4)
        put(tick(1.2), e + 0.4, 0.05, 0.45)
        counter(e + 0.4, 1.2)
groove(45.1, 63.4, lvl=0.98, arp16=True)                                    # v17.7 full groove through the entries and the payoff (no breath)
groove(63.4, 64.3, style='half', lvl=0.86, arp16=True, bed=0.2)             # the column leaves on half time, into 03
put(swell(0.85 * BEAT), 58.75, 0.32)
peak(59.6, 'Am+', 0.95, 0.6)                                                # the payoff lands: centred % counters + 提高效率 (PO + POD, film b85.25)
put(lead(lq(81, 59.6), 2.0 * BEAT), 59.6, 0.085, 0.0, to='lead')            # the motif's A on the peak (film b82.5) …
put(lead(lq(79, 61.6), 1.0 * BEAT), 61.6, 0.075, 0.0, to='lead')            # … answered G …
put(lead(lq(76, 62.6), 0.8 * BEAT), 62.6, 0.07, 0.0, to='lead')             # … E, so the line keeps moving under the static payoff
put(bell(lq(88, 60.25), 2.0), 60.25, 0.06, 0.1, to='verbsend')              # v18.4 the payoff is fully composed (film b83.15): a bell …
put(pluck(lq(81, 60.25), 0.6), 60.25, 0.07, -0.1, to='verbsend')            # … and a pluck landing
counter(59.7, 0.8, 8, 0.05)
put(whoosh(1.1 * BEAT), 63.4, 0.12, 0.2)                                    # the column drifts out into the orb (film b86.3)
put(stab(tuple(tone(63.4, j, 55) for j in range(4)), 1.4), 63.4, 0.1, 0.0, to='verbsend')   # V under the held A (the 9th), resolving to Am at film b86.8
put(settle(0.9), 59.7, 0.07, 0.15)                                          # 提高效率 wipes in orange (PO + .1)
put(puff(0.8), 63.2, 0.045, -0.5, to='verbsend')                            # and closes into a stack (b63.2)
put(tick(1.2), 63.175, 0.12, -0.5)                                         # v18.4 sync: the stack closes as the orb morph starts (scene 63.15–63.2, film b86.05–86.1)
put(tick(1.3), 63.6, 0.08, 0.0)                                             # v18.6 the column has closed into one circle (film b86.5)
put(tick(1.0), 63.8, 0.04, -0.5)                                            # the stack hands on to the merge (b63.8)

# ================= 50-tools: merge, session trajectory, studio (b55.0–75.2)
section('50-tools')
chords((55.3, 'Am'), (59.3, 'F'), (62.3, 'G'), (64.8, 'C'), (67.55, 'F'), (71.3, 'G'), (73.3, 'C'))   # 验证 ✓ and done land on I; v18.6 on the film's half-beat grid (SHIFT 31.7: film 87 / 91 / 94 / 96.5 / 100.5 / 103 / 105)
padlvl(55.0, 0.19, 1700)                                                    # v18.7 .16 → .19: the 03 entry is not a trough
padlvl(62.3, 0.19, 1900)
padlvl(65.0, 0.19, 2100)
padlvl(67.3, 0.16, 1800)
padlvl(68.8, 0.17, 2000)
put(whoosh(1.4 * BEAT, down=True), 55.0, 0.24, 0.0)                         # five dots merge into one
put(whoosh(0.8 * BEAT), 54.6, 0.08, -0.2)                                   # v18.4 the trajectory track grows out (film b86.5)
put(tick(1.0), 54.8, 0.045, -0.2)
groove(55.0, 68.8, style='half', lvl=0.86, arp16=True, bed=0.26)            # v17.7 half time under the trajectory (v18.6 .82 → .86: never under v17.7) …
groove(68.8, 73.75, lvl=1.0, arp16=True)                                    # … four on the floor from the press …
groove(73.75, 75.2, lvl=1.2, arp16=True, bed=0.24)                          # … v18.7 the floor stays four through done ✓ (the peak no longer eases into half time)
peak(73.75, 'C', 1.2, 0.8, boom_gain=0.45 / 1.2, kick_gain=0.7 / 1.2)   # v18.8 1.0 → 1.2: the loudest moment of the film (boom / kick unchanged)                                                  # the second core feature's peak: done ✓ (film b105.45), v18.7 up to a full peak
put(riser(3.4 * BEAT, 300, 6000), 70.3, 0.16, to='verbsend')                # v18.7 prepared by a riser …
for k, b_ in enumerate((72.85, 73.1, 73.35, 73.6)):                         # … and a clap pickup into it
    put(clap(), b_, 0.12 + 0.06 * k, 0.0, to='verbsend')
padlvl(73.75, 0.27, 2900)                                                   # v18.7 .21 → .27: the pad opens with done ✓
put(sweep_pad(tuple(m + 12 for m in CH['C'][0]), 2.4 * BEAT, 1.0 * BEAT), 73.75, 0.1, to='verbsend')   # v18.7 a held bright C under the peak (body, not transient)
put(swell(0.8 * BEAT), 55.2, 0.12)                                          # the orb grows into the card (film b86.9–87.7), no hit
put(lp(swell(0.46 * BEAT), 6000) + 0.5 * bp(swell(0.46 * BEAT), 300, 900), 67.15, 0.16, 0.0)   # v18.4 the cards are drawn into the orb (film b98.85–99.35): a reverse, suck-in swell that cuts just before the b67.65 pluck
put(pluck(tone(68.1, 2, 72), 0.5), 68.1, 0.08, 0.1, to='verbsend')         # 开始生成 pops out (film b99.8)
put(blip(tone(67.15, 1, 79), 0.6), 67.15, 0.05, 0.1, to='verbsend')       # v18.5 开始生成 grows out of the orb (film b98.85)
put(tick(1.3), 68.1, 0.07, 0.1)
motif(55.1, 0.05, scale=2.0, held=2.0, cutoff=3000)                         # v18.5 half speed, back in the E5 range (no octave drop: 03 must not sound like a drop-out)
put(lead(lq(79, 61.1), 2.0 * BEAT, 3000), 61.1, 0.05, 0.0, to='lead')       # G bridges the two statements
motif(63.1, 0.05, notes=Q_N[:4], times=(0, 0.5, 1.0, 2.5), scale=1.0, held=3.2, cutoff=3000)   # v18.5 Q's first half answers it, G held to the press
for k, b_ in enumerate((55.4, 57.8, 60.0, 62.3)):                           # phase pills pop on the playhead: 探索 / 规划 / 实施 / 部署
    put(pluck(tone(b_, (0, 1, 2, 0)[k], 72 if k < 3 else 64), 0.5), b_, 0.06, -0.3 + 0.15 * k, to='verbsend')
    put(puff(), b_, 0.03, -0.3 + 0.15 * k, to='verbsend')
    put(pluck(tone(b_, (0, 1, 2, 0)[k] + 1, 84), 0.5), b_, 0.05, 0.3 - 0.15 * k, to='verbsend')   # v18.5 a light high pluck per pill
put(tick(1.2), 55.4, 0.06, -0.3)                                            # v18.3 探索 pops on the replay start
put(swell(1.2 * BEAT), 62.65, 0.08)                                         # 连续失败 4 次: the critical glow
for j, g in enumerate((0.08, 0.05)):                                        # 验证 ✓ (b65.0): C-chord bell
    put(bell(tone(65.0, 2 * j + 1, 72), 1.8), 65.0, g, 0.3, to='verbsend')
put(puff(), 65.0, 0.03, 0.3, to='verbsend')
put(tick(1.5), 66.6, 0.09, 0.2)                                           # v18.5 the orb leaves the playhead (b66.6)
put(whoosh(0.55 * BEAT), 66.6, 0.04, 0.2)
put(whoosh(1.4 * BEAT), 67.0, 0.1, -0.3)                                    # trajectory out, studio in (b67.1 / 67.3)
put(tick(1.0), 67.25, 0.05, -0.3)                                           # v18.3: the old accent leaves (b67.25)
put(settle(1.0), 67.61, 0.14, 0.1)                                          # v18.4 one landing for 「04 · 生成工坊」 (b67.57), 开始生成 growing (67.6) and the card in the orb (67.65)
put(puff(0.9), 67.75, 0.065, 0.3, to='verbsend')                             # the new accent comes in (b67.75)
put(tick(1.3), 67.76, 0.2, 0.3)                                           # v18.5 one click between the accent (67.75) and the button's full fill (67.8)
put(whoosh(0.7 * BEAT), 68.2, 0.05, 0.1)                                   # the camera pushes in on 开始生成 (b68.2)
arp(68.5, 68.8, 0.1, 0.05, base=72, span=3)                                 # the .3-beat hover: a rising up-beat into the press
put(press(), 68.8, 0.22, 0.2)
for k, (b_, g) in enumerate(((66.8, 0.08), (67.05, 0.11), (67.3, 0.14))):  # v18.8 03 → 04: a 16th clap + tom fill (film 98.5 / 98.75 / 99.0) …
    put(clap(), b_, g, 0.0, to='verbsend')
    put(tom((45, 48, 52)[k]), b_, g * 3.4, -0.3 + 0.3 * k, to='verbsend')
put(kick(0.5, 0.8), 67.55, 0.45, to='kick')                                 # … an anticipated push on film 99.25 (「04 · 生成工坊」), with the F root a quarter early
put(bass_note(CH['F'][1], BEAT * 0.45), 67.55, 0.62 * 0.86, to='duck')
put(lp(kick(0.3, 0.6), 500), 68.8, 0.22, to='kick')                        # v18.3 the press is felt                                               # the dot presses 开始生成
for m, b_, d_ in ((81, 68.8, 1.1), (79, 69.95, 2.65), (76, 72.6, 1.15), (84, 73.75, 1.5)):   # the studio's answer: A (press) G E C (done ✓, on I)
    put(lead(lq(m, b_), d_ * BEAT), b_, 0.06, 0.0, to='lead')
put(blip(tone(68.8, 0, 72), 0.4), 68.8, 0.07, 0.2, to='verbsend')
for b_ in (68.95, 69.45, 69.95, 72.85, 73.3):                               # run steps (soft ticks)
    put(tick(1.2), b_, 0.06, 0.3)
put(tick(0.9), 71.7, 0.05, -0.2)                                             # v18.4 the pin dot (film b103.4)
put(bell(tone(72.6, 2, 84), 2.4), 72.6, 0.08, 0.1, to='verbsend')         # v18.5 已写入 ✓ (film b104.3): the 04 value point, bell …
put(pluck(tone(72.6, 0, 72), 0.6), 72.6, 0.09, -0.1, to='verbsend')       # … + pluck
# v18.7 no kick at 72.6 (film 104.30): it smeared the 104.0 groove kick; bell + pluck carry 已写入 ✓
for k in range(1, 26):                                                      # SKILL.md typed at an even rate (b70.05–72.65)
    put(key_click(), 70.05 + k / 10, 0.03 + 0.015 * rng.random(), 0.3 * (rng.random() - 0.5))
for j, g in enumerate((0.1, 0.07, 0.045)):                                  # ✓ done (b73.75): C-chord bell
    put(bell(tone(73.75, 2 * j, 72), 2.0), 73.75, g, 0.1, to='verbsend')
put(whoosh(1.1 * BEAT), 73.9, 0.06, 0.2)                                    # the cards shrink into the dot (b73.9)
put(tick(0.9), 74.2, 0.05, -0.2)                                            # v18.6 the 04 title leaves (b74.2)
for b_ in (74.25, 74.75):                                                   # v18.8 open hats ride the done ✓ lift
    put(hat(True), b_, 0.12, 0.25)
put(tick(1.2), 67.58, 0.06, 0.1)                                            # v18.6 the card lands in the circle (blink 67.55), 04 headline 67.57, button 67.6
put(hp(swell(0.45 * BEAT), 1500), 73.9, 0.2, 0.0)                           # v18.5 SKILL.md is sucked into the orb (film b105.6–106.05): a short bright rise …
put(lp(kick(0.3, 0.7), 500), 74.35, 0.2, to='kick')                          # … and lands hard (film b106.0)
put(press(), 74.35, 0.12, 0.0)

# ================= 60-close: ring → compass → ring → the curve is drawn → 45° icon → wordmark → tagline → fade (b69.2–94.8)
section('60-close')
chords((68.8, 'F'), (70.8, 'Am'), (75.3, 'F'), (78.3, 'G'), (TURN0 - 0.1, 'C+'), (TURN0 + 3.9, 'F/C'), (TURN0 + 5.4, 'G'), (TURN0 + 6.04, 'C+'))   # v18.6 on the film's half-beat grid (SHIFT 37.7: film 106.5 / 108.5 / 113 / 116 / 118 / 122 / 123.5), the last on agent ✓4   # v18.3 V → I lands on agent ✓4   # IV → V → I onto the wordmark
padlvl(69.2, 0.17, 1700)
padlvl(71.04, 0.18, 2000)
padlvl(75.6, 0.15, 1500)
padlvl(78.6, 0.18, 2100)
padlvl(TURN0, 0.19, 2300)
padlvl(TURN0 + 0.1, 0.22, 2400)
padlvl(TURN0 + 3.8, 0.20, 2000)
padlvl(TURN0 + 5.4, 0.20, 2200)
padlvl(FADE0, 0.22, 2000)
put(whoosh(1.0 * BEAT), 69.2, 0.12, -0.2)                                   # the merged dot spirals out
for i, m in enumerate(AG):                                                  # v18.3 the orb bursts (b69.25): the opening cluster pop as a callback
    put(blip(q(m + 12, 69.25), 0.6), 69.25 + 0.06 * i, 0.13, -0.6 + 0.3 * i, to='dry')   # v18.5 louder and dry (clear of 106.0's echo)
put(lp(kick(0.3, 0.5), 450), 69.25, 0.2, to='kick')
put(lead(lq(79, 69.25), 1.75 * BEAT), 69.25, 0.05, 0.0, to='lead')          # v18.3 G carries the burst into the compass E
put(lead(lq(76, 74.2), 1.4 * BEAT), 74.2, 0.05, 0.0, to='lead')             # E as it folds back, into the stroke
shimmer(69.4, 1.6, 12, 0.03)                                                # the ring draws on behind the dots
groove(69.2, 75.4, style='half', clap_on=False, lvl=0.8, bed=0.2) 
roll(71.04, 5, 0.08, 0.1, 60)                                               # the ring opens into the compass
put(lp(kick(0.3, 0.5), 400), 71.04, 0.18, to='kick')
roll(71.44, 4, 0.04, 0.08, 69)                                              # your type's flower
put(blip(tone(72.64, 3, 76), 0.6), 72.64, 0.04, 0.2, to='verbsend')         # the type code is lit
motif(71.04, 0.06, notes=(76, 79, 81), times=(0, 0.4, 1.6), held=1.5)        # the compass quotes the motif: E (ring opens) G (flower) A (type code)
motif(75.6, 0.06, notes=Q_N, times=Q_T, held=1.0)                            # v18.5 Q on the stroke, open on D over G
put(lead(lq(88, 80.2), 1.6 * BEAT), 80.2, 0.06, 0.0, to='lead')             # E6 as the icon stands, handed to the boom
put(swell(1.2 * BEAT), 74.2, 0.18)                                          # it folds back into the ring
put(whoosh(1.0 * BEAT), 75.3, 0.06, 0.3)                                    # the dots fly onto the pen head
groove(75.4, 80.2, style='half', clap_on=False, lvl=0.84, bed=0.2)  # v18.8 half time keeps kick on 1 and 3 under the stroke (no 2.2 s drop-out) …         # the pulse stays, the floor drops out (v18.6 .74 → .84, bed .2: never under v17.7)
put(sweep_pad(tuple(m + 12 for m in CH['F'][0]), 3.0 * BEAT, 0.4 * BEAT), 75.6, 0.12, to='verbsend')   # the curve is drawn
arp(75.6, 78.6, 0.5, 0.055, base=67, span=6, accel=0.25)                    # (b75.6–78.6): a rising swell following the stroke
put(riser(3.0 * BEAT, 300, 5000), 75.6, 0.14, to='verbsend')
put(pluck(lq(76, 75.6), 0.4), 75.6, 0.08, 0.0, to='verbsend')              # v18.4 the stroke starts on a fast attack (film b113.3)
put(tick(1.5), 75.6, 0.09, 0.0)                                             # v18.5 a bright attack on the first stroke
put(hat(False), 75.6, 0.12, 0.2)
put(sweep_pad(tuple(m + 12 for m in CH['G'][0]), 3.0 * BEAT, 0.6 * BEAT), 78.6, 0.07, to='verbsend')   # the slow push (film b116.3–119.3) …
put(riser(3.0 * BEAT, 200, 2500), 78.6, 0.06, to='verbsend')                # … a slow rising swell into the turn
put(whoosh(1.6 * BEAT), 78.6, 0.1, -0.2)                                    # it turns and tilts into the 45° icon
for k in range(5):                                                          # v18.8 stroke → turn: a 16th clap roll (film 116.75–117.75) into the icon at 117.9
    put(clap(), 79.05 + 0.25 * k, 0.05 + 0.0225 * k, 0.0, to='verbsend')
TAG0 = TURN0 + 4.0
LAST = TAG0 + 1.4 + 0.64                                                    # agent ✓4: the last strong beat (film b124.74)
TD = 0.0                                                                     # K.words hard-cuts each tagline word at TAG0 + .2 k (2 frames); the agent row morphs at TAG_AG + .16 k
put(boom(2.4, 48, 28), 80.2, 0.2, to='verbsend')                            # the icon stands (b80.2)
put(stab(tuple(tone(80.2, j, 62) for j in range(4)), 1.6), 80.2, 0.1, to='verbsend')
groove(80.2, TURN0 + 0.1, style='half', clap_on=False, lvl=0.76, bed=0.18)  # it breathes in the centre (v18.6 .7 → .76)
put(swell(0.5 * BEAT), TURN0 - 0.4, 0.3)
peak(TURN0 + 0.1, 'C+', 0.85, 0.8)                                          # the kit reveal turn (film b118.2) — under the two feature peaks
put(lead(lq(84, TURN0 + 0.1), 2.3 * BEAT), TURN0 + 0.1, 0.05, 0.0, to='lead')   # v18.3 C held from the turn into the letters (LET0)
groove(TURN0 + 0.1, LAST - 0.15, lvl=0.82, arp16=True, bed=0.18)                  # the groove runs under the end card to agent ✓4 (v17.7 .74, +.04 so it never sits under v17.7)
breath(LAST - 0.15, CLOSE_END)                                              # v18.7 the groove's last 16th is film 123.75: the button stands alone
for b_, g in ((LAST - 0.64, 0.18), (LAST - 0.39, 0.26)):                    # V → I clap pickup (film 123.5 / 123.75)
    put(clap(), b_, g, 0.0, to='verbsend')
put(kick(0.6, 1.0), LAST, 0.7, to='kick')                                   # the final button
put(crash(3.0), LAST, 0.12, 0.15)
put(stab(CH['C+'][0], 2.4), LAST, 0.14, to='verbsend')
padlvl(LAST, 0.26, 2300)
_d = (CLOSE_END - LAST) * BEAT
put(np.sin(2 * np.pi * midi(36) * tt(_d)) * np.clip(tt(_d) / 0.05, 0, 1) * np.exp(-tt(_d) * 0.35), LAST, 0.2, to='dry')   # a C2 pedal rings to END
for k in range(7):                                                          # 「rbit·知音」 rise (LET0 + .242 k): the same phrase as 20-orbit
    b_ = TURN0 + 2.475 + 0.242 * k
    put(bell(lq(LETTERS[k], b_), 1.4), b_, 0.045 - 0.002 * k, -0.45 + 0.15 * k, to='verbsend')
    put(lead(lq(LETTERS[k], b_), (0.242 if k < 6 else 0.07) * BEAT), b_, 0.035, 0.0, to='lead')   # v18.5 the last E hands straight to the tagline
for k in range(7):                                                          # An Assistant Redesign for everyone & every (TAG0 + .2 k)
    b_ = TAG0 + TD + 0.2 * k
    put(blip(tone(b_, k % 4, 72), 0.3), b_, 0.02, -0.45 + 0.15 * k, to='verbsend')
motif(TAG0 + TD, 0.05, notes=M[:3], times=M_T[:3], held=0.4)                     # the tagline starts the motif …
CLOSE_AG = (76, 79, 81, 76, 84)                                             # … and the 「agent」 dots (TAG0 + 1.4) finish it, resolving on C
for i, m in enumerate(CLOSE_AG):
    b_ = TAG0 + 1.4 + TD + 0.16 * i if i < 4 else LAST
    put(blip(lq(m, b_) if i < 4 else 72, 0.7 if i < 4 else 3.0), b_, 0.14, -0.6 + 0.3 * i, to='verbsend')   # v18.7 .1 → .14
put(lead(lq(83, TAG0 + 1.4 + TD), (LAST - TAG0 - 1.4 - TD) * BEAT), TAG0 + 1.4 + TD, 0.04, 0.0, to='lead')   # v18.3 the leading tone over V …
put(lead(84, (CLOSE_END - LAST - 0.4) * BEAT), LAST, 0.06, 0.0, to='lead')   # v18.5 B5 steps up to C6 …
put(lead(72, (CLOSE_END - LAST - 0.4) * BEAT), LAST, 0.03, 0.0, to='lead')   # … with C5 under it   # … resolving to the root C5 on agent ✓4   # the last motif note rings out over the fade
put(bell(lq(84, LAST), 6.0), LAST, 0.04, 0.1, to='verbsend')
put(sweep_pad(tuple(m + 12 for m in CH['C'][0]), 5.0 * BEAT, 2.5 * BEAT), TAG0 + 3.0, 0.035, to='verbsend')   # soft swell under the push-in
FADE = (FADE0 + SH, END)                                                    # FADE0 = 92.2: everything decays to 0 by END


# ================= v17.7 Agent-dot morphs: soft cues on the 'morph' bus (scene beats per section), ≥ 10 dB under the lead
def m_air(d=0.14, lo=3500, hi=9000):
    """Rapid morphs (ticks, caret pulses, tails, petal sweeps): an airy breath, unpitched, no attack."""
    t = tt(d)
    return bp(noise(d), lo, hi) * np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2 * 0.5


def m_click():
    """The studio pointer press / a pin stab: a small soft knock."""
    t = tt(0.08)
    return bp(noise(0.08), 1200, 4200) * np.exp(-t * 260) * 0.45 + np.sin(2 * np.pi * 150 * t) * np.exp(-t * 70) * 0.35


def m_low(m, d):
    """Orb splits / merges: a low soft swell on the chord root, rising then dying away (sine + octave, no attack)."""
    t = tt(d)
    f = midi(m)
    env = np.sin(np.pi * np.clip(t / d, 0, 1) ** 0.6) ** 2
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)) * env


def m_blink(m, d=0.32):
    """v18.6 R2 「圆形 + 闪烁」: a dot blinks (soft glow flash + ≤ 1.12 pulse) — a short airy chord-tone ping, v17.6 style:
    a sine + soft octave with an 6 ms rise and a quick decay, under a 60 ms breath of air. No tail, no whoosh."""
    t = tt(d)
    f = midi(m)
    env = np.clip(t / 0.006, 0, 1) * np.exp(-t * 16)
    tone_ = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)) * env
    air = bp(noise(d), 4000, 10000) * np.sin(np.pi * np.clip(t / 0.06, 0, 1)) ** 2 * 0.35
    return tone_ + air


def mcue(b, kind, i=0):
    pan = (-0.5, 0.3, -0.2, 0.5, 0.0)[i % 5]
    if kind == 'bell':                                       # a single morph: a light high bell on a chord tone
        put(bell(tone(b, (i + 2) % 4, 84), 0.9), b, 0.022, pan, to='morph')
    elif kind == 'pluck':                                    # a single morph, drier
        put(blip(tone(b, (i + 1) % 4, 79), 0.3), b, 0.028, pan, to='morph')
    elif kind == 'air':
        put(m_air(), b - 0.1, 0.09, pan, to='morph')
    elif kind == 'click':
        put(m_click(), b, 0.08, pan, to='morph')
    elif kind == 'spark':                                    # a gentle shimmer of chord tones
        for k in range(5):
            bk = b + 0.12 * k
            put(blip(tone(bk, k % 4, 88), 0.15), bk, 0.011 * (1 - 0.12 * k), -0.4 + 0.2 * k, to='morph')
    elif kind == 'blink!':                                   # v18.7 a FIX blink in 1d, +4 dB so it reads over the half-time groove
        put(m_blink(tone(b, (i + 2) % 4, 84)), b, 0.054, pan, to='morph')
    elif kind in ('blink', 'blink+'):                        # v18.6 a dot (or all five) blinks: one soft chord-tone ping
        put(m_blink(tone(b, (i + 2) % 4, 84)), b, 0.034 if kind == 'blink' else 0.06, pan, to='morph')   # blink+: the one circle (50-tools), over the half-time bed
    elif kind == 'gen':                                      # v18.7 a generation breath: a very soft high ping per SKILL.md line
        put(m_blink(tone(b, (i + 2) % 4, 84), 0.22), b, 0.016, pan, to='morph')
    elif kind == 'low':                                      # orb split / merge
        put(m_low(tone(b, 0, 36), 1.4 * BEAT), b - 0.3 if b + SH >= 0.3 else b, 0.05, 0.0, to='morph')


MCUES = []   # (scene, [film beats]) for the level report
_GL = ['---', 'name: pr-wrapup', 'description: 合并前收尾。触发 review，只修 P0/P1，', '  最多两轮，之后合并并删除分支', '---', '# PR 收尾',
       '1. 确认 CI 通过、review 为 Completed', '2. 只处理 P0 / P1；其余回复理由', '3. 第二轮后仍有意见：停止并汇报', '4. 合并方式沿用仓库约定（merge commit）',
       '5. 合并后删除远端与本地分支', '', '## 不要做', '- 不要为 P2 意见开启新一轮 review']   # = GEN.Skill.lines (src/js/48-a9-studio.js)
_GW = [0]
for _l in _GL:
    _GW.append(_GW[-1] + 2 + len(_l))
GEN_LB = [70.05 + (72.65 - 70.05) * (w + 1) / _GW[-1] for w in _GW[:-1]]   # = 50-tools lineB(): each line's breath


def mcues(spec):
    MCUES.append((SCENE, [b + SH for b, _ in spec]))
    for i, (b, kind) in enumerate(spec):
        mcue(b, kind, i)


section('10-intro')
mcues([(0.2, 'low'), (0.82, 'blink'), (1.5, 'blink'), (1.95, 'blink'), (2.45, 'blink'), (6.95, 'blink'), (7.0, 'blink'),
       (K1[0], 'pluck'), (7.85, 'blink'), (8.1, 'blink'), (8.8, 'blink'), (S1 + 0.15, 'blink'), (K2[0], 'pluck'),
       (10.1, 'blink'), (10.45, 'blink'), (S2 + 0.15, 'blink'), (11.35, 'blink'), (11.7, 'blink'), (13.0, 'air')])
# v18.6 R1/R2: the opening ONE circle swells low (0.2); every dot event is a blink (round + flash, no tails): the landing
# (0.62), cp on 「成为」「每个人的」, all on 「日常」, cx on 「从」, the box growing (7.0), each bubble pop (T(6.05) / T(6.3) /
# 7.85 / 8.8 / sends + .15 / 10.1 / 10.45), the icon burst (11.35) and the box sinking (T(9.3) = 11.7); the caret takes
# a dot on BX + .12 and S1 + .1 (a dry pluck)
# v18.7 D1/D2: the merged 17-series badge opens from 0.35 (the 0.2 swell carries it), the four land-blink at 0.82 (was .62);
# the caret ride-ins (cc on K1[0] = 7.2, cx on K2[0] ≈ 9.55) take the dry pluck; lift + round (S + .05) sits in the send blink
section('15-redesign')
mcues([(11.8, 'air'), (12.04, 'pluck'), (12.36, 'blink!'), (12.75, 'pluck'), (13.95, 'blink!'), (14.1, 'blink!'), (14.35, 'pluck'),
       (14.55, 'blink!'), (15.08, 'blink!'), (15.41, 'blink!'), (15.6, 'pluck'), (15.9, 'blink!'), (16.25, 'blink!'), (16.5, 'blink!'),
       (16.73, 'blink!'), (16.93, 'blink!'), (17.12, 'blink!'), (20.42, 'blink'),
       (21.0, 'air'), (22.5, 'air'), (22.9, 'air'), (23.3, 'air'), (23.6, 'spark')])   # v18.6 R2: caret falls (11.8) → round dots (12.04) → blinks on every pop / send / landing; the 1e beads (21.0–23.6) unchanged   # v18.2: circle from the beads b21.0, bead steps on CUT, glow CUT[2] + .3
section('20-orbit')
mcues([(21.6, 'air'), (23.3, 'bell'), (25.25, 'pluck'), (26.25, 'air'), (26.7, 'air'), (30.45, 'pluck'),
       (32.1, 'bell'), (33.0, 'spark')])
section('30-persona')
mcues([(28.6, 'blink+'), (29.3, 'blink'), (29.5, 'bell')]           # v18.7 D1: the bud blinks (all), the bloom blinks soft
      + [(b_, 'blink') for b_ in (35.77, 35.88, 36.18, 36.65, 36.74)]        # v18.7 D3: each sweep blinks the round badges it passes (no petals)
      + [(b_, 'blink') for b_ in (37.75, 37.92, 38.31, 38.40, 38.64)]
      + [(b_, 'blink') for b_ in (39.71, 40.07, 40.34, 40.78)]
      + [(41.42, 'blink+')])                                         # the reveal: the ring glows, one ping
section('40-recs')
mcues([(39.5, 'blink'), (39.64, 'blink'), (39.78, 'blink'),
       (41.6, 'blink'), (42.7, 'blink'), (43.8, 'blink')]                # v18.7 D1: intro rows and the three waves blink (no bullets)
      + [x for e in EV for x in ((e - 0.4, 'blink'), (e + 0.4, 'air'))]  # the linked badge blinks, ✓ tick beside it (2.6-beat EV grid)
      + [(63.5, 'low')])                                                   # v18.7 D2: cc grows the five arcs (b63.2–63.65): the swell starts on 63.2                                     # v18.6 R1: the column closes into ONE circle (b63.6)                                                     # v18.2: bullets → round badges (b62.8)
section('50-tools')
mcues([(55.3, 'low'), (56.35, 'blink+'), (57.45, 'blink+'), (59.65, 'blink+'), (61.95, 'blink+'), (64.65, 'blink+'),
       (67.58, 'blink+'), (69.9, 'blink+'), (74.3, 'blink+')]   # v18.7: the press is press() + kick (no pointer knock); the wire leaves at 69.9 (was 69.35)
      + [(b_, 'gen') for b_ in GEN_LB])                          # v18.7 D2: the badge breathes with each SKILL.md line it writes   # v18.6 R1: one circle — wire out, the four pins (KN − .35), card in, press, SKILL.md in
section('60-close')
mcues([(69.2, 'low')] + [(69.7 + 0.05 * k, 'blink') for k in range(4)]   # v18.7 AGD.open: four badges grow out of the arcs and blink in turn
      + [(71.95, 'blink+'), (71.95, 'bell')] + [(72.64 + 0.12 * k, 'air') for k in range(5)]   # all five blink (was the petal close); glow sweep
      + [(75.55, 'blink'), (78.6, 'bell'), (79.1, 'air')]            # gm blinks on the pen (no comet head)
      + [(TURN0 + 2.475 + 0.2 * k, 'air') for k in range(5)]
      + [(TURN0 + 5.4 + 0.16 * k, 'air') for k in range(5)]
      )
put(m_low(tone(FADE0, 0, 36), 1.4 * BEAT), FADE0 + 0.25, 0.017, 0.0, to='morph')   # v18.7 merge (92.2) + AGD.seal (92.45–93.45): the low swell under the gather
MCUES.append((SCENE, [FADE0 + 0.7 + SH]))   # (no ping when the merged badge stands at b93.44: the mix has faded, any ping sat < 10 dB under it)


# ---------------- render the grid layers: groove, pads ----------------
rng = np.random.default_rng(7)   # v18.7 the groove's noise (hats, claps, crashes) no longer depends on how many cues came before it
def render_groove():
    spans = [list(g) for g in GROOVE]                   # definition order: a later span wins an overlap
    by_start = sorted(spans, key=lambda s: s[0])
    for cur, nxt in zip(by_start[:-1], by_start[1:], strict=True):   # bridge a small gap a SHIFT leaves between sections
        if 0 < nxt[0] - cur[1] < 4 and not any(b0 - 1e-6 <= cur[1] <= b1 + 1e-6 for b0, b1 in BREATHS):
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
    for bi, p in zip(steps, owner, strict=True):        # v18.6: the v17.7 groove, untouched by picture hits or typing
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
            putf(pluck((tones[0], tones[1], tones[2], tones[1])[k], BEAT * 0.4), bi, 0.07 * lvl, 0.6 if k % 2 else -0.6, to='verbsend')   # v18.7 wider
            putf(shaker(True), bi, 0.03 * lvl, -0.45 if k % 2 else 0.45)    # v18.8 a 16th shaker inside the arp16 spans (2–6 kHz pulse)
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
        i0 = at(start)
        for pn in (-0.7, 0.7):                           # v18.7 two independently phased voices, one each side: L/R correlation ~.9, mono level kept
            sig = pad(CH[c][0], d, cut, att=xover * BEAT, rel=xover * BEAT)
            g = gain[i0:i0 + len(sig)]
            putf(sig[:len(g)] * g, start, 0.72, pn, to='duckverb')


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

ld_l, ld_r = bus('lead')
LG = 1.0                                                 # v18.6 the motif is a quiet hook riding the groove (v18.3–18.5 ×4.4 dropped)
KG = 10 ** (7.5 / 20)                                    # keys: every typed character clearly heard, dry, the groove untouched
BUS['verbsend'] = (BUS['verbsend'][0] + ld_l * 0.35, BUS['verbsend'][1] + ld_r * 0.35)
out_l = bus('dry')[0] + ld_l * LG + bus('keys')[0] * KG + bus('morph')[0] + bus('kick')[0] + bus('verbsend')[0] + (bus('duck')[0] + bus('duckverb')[0]) * duck
out_r = bus('dry')[1] + ld_r * LG + bus('keys')[1] * KG + bus('morph')[1] + bus('kick')[1] + bus('verbsend')[1] + (bus('duck')[1] + bus('duckverb')[1]) * duck
send_l = bus('verbsend')[0] + bus('duckverb')[0] * duck * 0.6 + bus('morph')[0] * 0.5
send_r = bus('verbsend')[1] + bus('duckverb')[1] * duck * 0.6 + bus('morph')[1] * 0.5
out_l += signal.fftconvolve(send_l, ir)[:N] * 0.3
out_r += signal.fftconvolve(send_r, np.roll(ir, 211))[:N] * 0.3

mix = np.stack([out_l, out_r])
KEYS = np.stack(bus('keys')) * KG   # for the level report below
MORPH = np.stack(bus('morph'))
for b0, b1, b2, b3, fc in LPF:                      # low-pass automation: zero-phase copy, crossfaded in and out
    w = np.interp(np.arange(N), [at(b0), at(b1), at(b2), at(b3)], [0, 1, 1, 0], left=0, right=0)
    sos = signal.butter(2, fc, 'low', fs=SR, output='sos')
    mix = mix * (1 - 0.8 * w) + signal.sosfiltfilt(sos, mix) * 0.8 * w
mix = hp(mix, 25)                                      # v18.6 the v17.7 master: no shelves, bells or gain arc
norm = 1.12 / (np.max(np.abs(mix)) + 1e-9)          # v18.8 the top 12 % of the few hit transients go into the soft clip (out peak .87), not the whole mix down
_a = np.max(np.abs(mix), 0)
print('pre-norm peak %.3f; loudest beats:' % _a.max(), ', '.join('b%d %.2f' % (b, _a[at(b):at(b + 1)].max() / _a.max()) for b in sorted(range(int(END)), key=lambda b: -_a[at(b):at(b + 1)].max())[:6]))   # v18.7: which hits set the normalisation
mix *= norm
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
    print(f'  {name:12s} b{b0:5.1f}-{b1:5.1f}  peak {np.max(np.abs(seg)):.3f}  rms {20 * np.log10(np.sqrt(np.mean(seg ** 2))):6.1f} dBFS')
# the typing passages (film beats): keys alone vs everything else, after the same normalisation + drive gain
for name, b0, b1 in (('1b typing', 7.2, 10.8), ('1d typing', 12.95 + 6.9, 17.95 + 6.9)):
    i0, i1 = at(b0), at(b1)
    kr = np.sqrt(np.mean((KEYS[:, i0:i1] * norm * 1.6 / np.tanh(1.6) * 0.85) ** 2))
    tr = np.sqrt(np.mean(mix[:, i0:i1] ** 2))
    print(f'  {name}: keys {20 * np.log10(kr):6.1f} dBFS, full mix {20 * np.log10(tr):6.1f} dBFS, keys under mix by {20 * np.log10(tr / kr):5.1f} dB')
# the dot-morph cues: each one's level vs everything else in a ±.3-beat window (must stay ≥ 10 dB under)
G = norm * 1.6 / np.tanh(1.6) * 0.85
worst = []
for name, cues in MCUES:
    for fb in cues:
        i0, i1 = at(max(0, fb - 0.3)), at(fb + 0.3)
        mr = np.sqrt(np.mean((MORPH[:, i0:i1] * G) ** 2)) + 1e-12
        tr = np.sqrt(np.mean(((mix[:, i0:i1]) - MORPH[:, i0:i1] * G) ** 2)) + 1e-12
        worst.append((20 * np.log10(tr / mr), name, fb))
worst.sort()
print('  dot morphs: %d cues, quietest margin %.1f dB under the mix (%s film b%.2f), median %.1f dB' % (
    len(worst), worst[0][0], worst[0][1], worst[0][2], worst[len(worst) // 2][0]))
