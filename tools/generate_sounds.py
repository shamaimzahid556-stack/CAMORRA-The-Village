"""Generates the CAMORRA ambient sound files (original, synthesised: no third-party recordings).

    pip install numpy scipy          (only needed to regenerate; the game itself does not need them)
    python tools/generate_sounds.py  (needs ffmpeg on PATH for the .mp3 one-shots)

Output goes to static/sounds/:
    dark-ambience.wav      loop   front page + role assignment: low drone, cold wind, whispers, scrapes
    night-ambience.wav     loop   crickets, night air, a faint low drone
    day-ambience.wav       loop   eerie morning: sparse cold birds, wind, a low drone
    tension-loop.wav       loop   voting + elimination: heartbeat and dissonant strings
    win-civilians.mp3      loop   joyful music: the nightmare is over
    win-mafia.mp3          loop   dark music: tolling bell, thunder, evil laughter, wolves
    owl-hoot.mp3 / wolf-howl.mp3 / crow-caw.mp3 / creak.mp3     random one-shot calls
    morning-bell.mp3       shot   funeral-style bell + crows (day begins)
    night-fall.mp3         shot   deep bell toll + wind swell (night begins)
    ui-click.mp3           shot   dark knock for every button
    role-reveal.mp3        shot   sting when a role card is shown / voting begins

Everything is generated from mathematical models (sine sweeps, FM, filtered noise, inharmonic
bell partials), so the files carry no copyright or licence obligations.
They are synthetic. If you prefer real recordings, replace a file with a recording of the same
name (any royalty-free source with a licence you have checked) and the game will use it unchanged.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 22050                       # ambience does not need more: everything here sits below 9 kHz
OUT = Path(__file__).resolve().parent.parent / "static" / "sounds"
rng = np.random.default_rng(20241)


# ---------------------------------------------------------------------------------- primitives
def tvec(dur):
    return np.arange(int(dur * SR)) / SR


def env(n, attack, release, curve=2.0):
    e = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    if a > 0:
        e[:a] = np.linspace(0, 1, a) ** curve
    if r > 0:
        e[-r:] *= np.linspace(1, 0, r) ** curve
    return e


def band(x, lo, hi):
    sos = butter(4, [lo, hi], btype="band", fs=SR, output="sos") if lo and hi else \
        butter(4, hi or lo, btype="low" if hi else "high", fs=SR, output="sos")
    return sosfilt(sos, x)


def lowpass(x, f):
    return sosfilt(butter(4, f, btype="low", fs=SR, output="sos"), x)


def circular_noise(n, lo, hi):
    """Band-limited noise built in the frequency domain, so its end joins its start seamlessly."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec[(f < lo) | (f > hi)] = 0
    out = np.fft.irfft(spec, n)
    return out / (np.max(np.abs(out)) + 1e-9)


def slow_wobble(n, rate, depth, phase=0.0):
    """Smooth amplitude wobble that is periodic over the buffer (rate must fit whole cycles)."""
    t = np.arange(n) / n
    return 1 - depth + depth * (0.5 + 0.5 * np.sin(2 * np.pi * (rate * t + phase)))


def add_wrapped(buf, sig, start, gain_l, gain_r):
    n = len(buf)
    idx = (np.arange(len(sig)) + start) % n
    np.add.at(buf[:, 0], idx, sig * gain_l)
    np.add.at(buf[:, 1], idx, sig * gain_r)


def pan_gains(p):
    return np.cos(p * np.pi / 2), np.sin(p * np.pi / 2)


def sweep(f0, f1, dur, harmonics=(1.0, 0.3), vibrato=(0, 0)):
    t = tvec(dur)
    f = f0 + (f1 - f0) * (t / dur)
    if vibrato[0]:
        f = f + vibrato[1] * np.sin(2 * np.pi * vibrato[0] * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return sum(a * np.sin((i + 1) * ph) for i, a in enumerate(harmonics))


def reverb(x, tail=1.5, wet=0.3, damp=3000):
    n = int(tail * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * tail / 4.5))
    ir = lowpass(ir, damp)
    ir[0] = 0
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    y = fftconvolve(x, ir)
    y = np.pad(y, (0, max(0, len(x) + n - len(y))))[: len(x) + n]
    return np.concatenate([x, np.zeros(n)]) * (1 - wet) + y * wet * 1.5


def normalise(x, peak=0.85):
    return x / (np.max(np.abs(x)) + 1e-9) * peak


def to_stereo(mono, p=0.5):
    l, r = pan_gains(p)
    return np.stack([mono * l, mono * r], axis=1)


# ---------------------------------------------------------------------------------- birds
def bird_phrase(kind, dist):
    """dist 0 (close) .. 1 (far): far birds are quieter and duller."""
    if kind == "tweet":
        parts = []
        for _ in range(rng.integers(2, 5)):
            f0 = rng.uniform(3000, 4300)
            d = rng.uniform(0.05, 0.10)
            c = sweep(f0, f0 + rng.uniform(500, 1300), d) * env(int(d * SR), 0.008, 0.03)
            parts += [c, np.zeros(int(rng.uniform(0.04, 0.09) * SR))]
        s = np.concatenate(parts)
    elif kind == "whistle":
        d = rng.uniform(0.22, 0.34)
        s = sweep(rng.uniform(3500, 4100), rng.uniform(2300, 2900), d, (1.0, 0.18), (6, 40)) * env(int(d * SR), 0.03, 0.08)
    elif kind == "trill":
        parts = []
        base = rng.uniform(3800, 4800)
        for i in range(rng.integers(9, 15)):
            d = 0.028
            c = sweep(base + (200 if i % 2 else -200), base + (350 if i % 2 else -50), d) * env(int(d * SR), 0.004, 0.012)
            parts += [c, np.zeros(int(0.014 * SR))]
        s = np.concatenate(parts)
    elif kind == "warble":
        d = rng.uniform(0.45, 0.7)
        t = tvec(d)
        fm = rng.uniform(18, 30)
        s = np.sin(2 * np.pi * np.cumsum(rng.uniform(2900, 3700) + 650 * np.sin(2 * np.pi * fm * t)) / SR) * \
            (0.6 + 0.4 * np.sin(2 * np.pi * 9 * t)) * env(len(t), 0.06, 0.12)
    else:                                                    # "coo": a soft dove call
        notes, parts = [rng.uniform(470, 520), rng.uniform(560, 620), rng.uniform(520, 570), rng.uniform(500, 540)], []
        for i, f in enumerate(notes):
            d = 0.32 if i == 1 else 0.22
            parts += [sweep(f * 0.98, f * 1.02, d, (1.0, 0.4, 0.12), (5, 4)) * env(int(d * SR), 0.05, 0.1), np.zeros(int(0.09 * SR))]
        s = np.concatenate(parts)
    s = s * (1 - 0.75 * dist) * rng.uniform(0.8, 1.0)
    return lowpass(s, 9500 - 6000 * dist)


# ---------------------------------------------------------------------------------- loops
def day_loop(dur=30):
    """An eerie morning: cold wind, a low drone, a few distant birds and three crows."""
    n = int(dur * SR)
    buf = np.zeros((n, 2))
    tt = np.arange(n) / SR
    wind = circular_noise(n, 80, 1100) * slow_wobble(n, 3, 0.65) * 0.14
    leaves = circular_noise(n, 2500, 7000) * (0.3 + 0.7 * np.abs(circular_noise(n, 0.2, 1.4))) * 0.008
    buf[:, 0] += wind + leaves
    buf[:, 1] += np.roll(wind, 4000) + np.roll(leaves, 7000)
    drone = (np.sin(2 * np.pi * loopf(55, dur) * tt) + 0.8 * np.sin(2 * np.pi * loopf(77.8, dur) * tt)) * slow_wobble(n, 2, 0.5) * 0.045
    buf += drone[:, None]
    kinds = ["tweet"] * 4 + ["whistle"] * 4 + ["warble"] * 2 + ["trill"]
    for _ in range(18):                                   # far fewer, farther, duller birds than a cheerful morning
        sig = bird_phrase(kinds[rng.integers(len(kinds))], rng.uniform(0.35, 1.0)) * 0.12
        add_wrapped(buf, sig, int(rng.uniform(0, dur) * SR), *pan_gains(rng.uniform(0.1, 0.9)))
    for t0 in (6.5, 15.0, 24.0):
        add_wrapped(buf, crow(int(rng.integers(2, 4)), 0.55) * 0.5, int(t0 * SR), *pan_gains(rng.uniform(0.15, 0.85)))
    return normalise(buf, 0.8)


def night_loop(dur=30):
    n = int(dur * SR)
    buf = np.zeros((n, 2))
    air = circular_noise(n, 60, 520) * slow_wobble(n, 2, 0.6) * 0.07
    buf[:, 0] += air
    buf[:, 1] += np.roll(air, 3000)
    t = np.arange(int(0.14 * SR)) / SR
    for fc, period, gain in [(3900, 0.43, 0.045), (4300, 0.51, 0.04), (4750, 0.37, 0.04), (5150, 0.58, 0.035),
                              (4500, 0.47, 0.03), (5400, 0.62, 0.025)]:
        pulses = np.zeros_like(t)
        for k in range(4):                                    # one cricket "chirp" = 4 quick pulses
            c = int((0.01 + 0.032 * k) * SR)
            w = int(0.022 * SR)
            pulses[c:c + w] += np.hanning(w)
        chirp = np.sin(2 * np.pi * fc * t) * pulses
        l, r = pan_gains(rng.uniform(0.1, 0.9))
        pos = rng.uniform(0, period)
        while pos < dur:
            add_wrapped(buf, chirp * gain * rng.uniform(0.75, 1.0), int(pos * SR), l, r)
            pos += period * rng.uniform(0.93, 1.07)
    tt = np.arange(n) / SR
    drone = (np.sin(2 * np.pi * 55 * tt) + np.sin(2 * np.pi * 55.5 * tt)) * 0.006
    buf += drone[:, None]
    return normalise(buf, 0.75)


# ---------------------------------------------------------------------------------- one-shots
def hoot(f0, dur, amp):
    t = tvec(dur)
    f = f0 * np.concatenate([np.linspace(0.93, 1.0, int(0.05 * SR)), np.ones(len(t) - int(0.05 * SR))])[:len(t)]
    f = f * (1 - 0.07 * (t / dur) ** 2) * (1 + 0.004 * np.sin(2 * np.pi * 5 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = sum(a * np.sin((i + 1) * ph) for i, a in enumerate([1.0, 0.5, 0.22, 0.09]))
    s += band(rng.standard_normal(len(t)), 600, 1800) * 0.05
    return s * env(len(t), 0.07, 0.14) * amp


def owl():
    out = np.zeros(int(6.0 * SR))
    for t0, d, a, f0 in [(0.15, 0.30, 0.7, 360), (0.62, 0.21, 0.6, 345), (0.98, 0.21, 0.6, 345), (1.45, 0.62, 1.0, 330)]:
        h = hoot(f0, d, a)
        i = int(t0 * SR)
        out[i:i + len(h)] += h
    out = lowpass(out, 2400)
    out = reverb(out, tail=1.6, wet=0.42, damp=2200)
    return normalise(out * env(len(out), 0.02, 1.0), 0.8)


def wolf():
    dur = 8.0
    t = tvec(dur)
    pts = [(0, 285), (0.6, 345), (2.4, 560), (3.4, 600), (5.0, 590), (7.0, 335), (8.0, 300)]
    f = np.interp(t, [p[0] for p in pts], [p[1] for p in pts])
    f = f + (0.8 + 1.2 * t / dur) * 7 * np.sin(2 * np.pi * 5.2 * t) + np.cumsum(rng.standard_normal(len(t))) * 0.02 - 0.0
    amp = np.interp(t, [0, 0.5, 1.5, 6.0, 7.2, 8.0], [0, 0.55, 1.0, 0.95, 0.4, 0]) * (1 + 0.06 * np.sin(2 * np.pi * 4.1 * t))

    def voice(fm, detune=1.0):
        ph = 2 * np.pi * np.cumsum(fm * detune) / SR
        s = np.zeros(len(t))
        for h in range(1, 11):
            formant = 0.2 + 0.8 * np.exp(-(((h * fm * detune) - 1150) / 750) ** 2)
            s += formant / h ** 1.05 * np.sin(h * ph)
        return s

    v1 = voice(f)
    v2 = np.roll(voice(f, 1.022), int(0.35 * SR)) * 0.5
    s = (v1 + v2) * amp + band(rng.standard_normal(len(t)), 600, 2500) * 0.035 * amp
    s = lowpass(s, 3400)
    s = reverb(s, tail=2.6, wet=0.45, damp=2500)
    return normalise(s * env(len(s), 0.05, 1.5), 0.8)


def bell(f, dur, amp=1.0):
    t = tvec(dur)
    out = np.zeros(len(t))
    for ratio, a, tau in [(0.5, 0.35, 0.55), (1.0, 1.0, 0.45), (1.2, 0.55, 0.32), (1.5, 0.33, 0.22), (2.0, 0.45, 0.20),
                          (2.5, 0.22, 0.14), (3.0, 0.16, 0.10), (4.1, 0.09, 0.07)]:
        out += a * np.sin(2 * np.pi * f * ratio * t + rng.uniform(0, 6.28)) * np.exp(-t / (dur * tau))
        out += 0.4 * a * np.sin(2 * np.pi * f * ratio * 1.003 * t) * np.exp(-t / (dur * tau))      # slow beating
    return out * env(len(t), 0.004, 0.2) * amp


def morning():
    """Day begins: a low funeral-style bell, crows and two cold birds."""
    out = np.zeros(int(8.0 * SR))
    for t0, a in ((0.0, 1.0), (2.4, 0.8)):
        b = bell(196.0, 5.0, a * 0.7)
        j = int(t0 * SR)
        out[j:j + len(b)] += b[: len(out) - j]
    for t0, dist in ((1.3, 0.35), (4.2, 0.5)):
        c = crow(2, dist) * 0.55
        j = int(t0 * SR)
        out[j:j + len(c)] += c[: len(out) - j]
    for t0 in (3.0, 5.6):
        s_ = bird_phrase("whistle", 0.5) * 0.25
        j = int(t0 * SR)
        out[j:j + len(s_)] += s_[: len(out) - j]
    out = reverb(lowpass(out, 6000), tail=2.2, wet=0.3)
    return normalise(out * env(len(out), 0.01, 1.8), 0.8)


def nightfall():
    out = np.zeros(int(6.5 * SR))
    b = bell(130.81, 5.5, 0.9)
    out[:len(b)] += b
    swell = lowpass(rng.standard_normal(len(out)), 450) * np.interp(np.arange(len(out)) / SR, [0, 1.5, 3.2, 6.5], [0, 0.35, 0.18, 0])
    out += swell * 0.5
    out = reverb(out, tail=2.2, wet=0.3, damp=2000)
    return normalise(out * env(len(out), 0.01, 1.5), 0.8)


# ---------------------------------------------------------------------------------- horror additions
def loopf(f, dur):
    """Round a frequency so a sine has a whole number of cycles in `dur` seconds (loops seamlessly)."""
    return max(1, round(f * dur)) / dur


def crow(n_caws=2, dist=0.4):
    parts = []
    for _ in range(n_caws):
        d = rng.uniform(0.32, 0.46)
        t = tvec(d)
        f = np.linspace(540, 360, len(t)) * (1 + 0.03 * np.sin(2 * np.pi * 55 * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        s = sum(np.sin(h * ph) / h ** 0.8 for h in range(1, 15))
        s = s * (0.7 + 0.3 * np.sign(np.sin(2 * np.pi * 70 * t))) + band(rng.standard_normal(len(t)), 500, 2500) * 0.5
        s = band(s, 350, 3200) * env(len(t), 0.02, 0.12)
        parts += [s, np.zeros(int(rng.uniform(0.18, 0.30) * SR))]
    s = np.concatenate(parts) * (1 - 0.7 * dist)
    return lowpass(s, 4500 - 2500 * dist)


def creak(dur=2.0):
    t = tvec(dur)
    f = 140 + 90 * np.sin(2 * np.pi * 0.45 * t) + 30 * np.sin(2 * np.pi * 1.3 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = sum(np.sin(h * ph) / h for h in range(1, 21))
    rate = 30 + 8 * np.sin(2 * np.pi * 0.9 * t) + 5 * np.sin(2 * np.pi * 2.3 * t)
    am = (0.5 + 0.5 * np.sin(2 * np.pi * np.cumsum(rate) / SR)) ** 3                  # stick-slip friction
    s = band(s * (0.25 + am), 250, 2200) * env(len(t), 0.15, 0.7)
    return normalise(reverb(s, tail=1.2, wet=0.25, damp=2500), 0.8)


def ui_click():
    t = tvec(0.22)
    thud = sweep(190, 55, 0.22) * np.exp(-t / 0.05)
    tick = band(rng.standard_normal(len(t)), 900, 3000) * np.exp(-t / 0.012) * 0.8
    return normalise(lowpass((thud + tick) * env(len(t), 0.001, 0.03), 4000), 0.8)


def role_reveal():
    n = int(3.8 * SR)
    out = np.zeros(n)
    sw = int(1.1 * SR)
    out[:sw] += band(rng.standard_normal(sw), 1500, 9000) * np.linspace(0, 1, sw) ** 3 * 0.5          # reversed-cymbal swell
    t = tvec(2.6)
    i = sw
    boom = sweep(70, 32, 2.6) * np.exp(-t / 0.8)
    out[i:i + len(boom)] += boom * 1.2
    cluster = (np.sin(2 * np.pi * 311.1 * t) + np.sin(2 * np.pi * 329.6 * t) + 0.6 * np.sin(2 * np.pi * 466.2 * t)) * np.exp(-t / 1.1) * 0.35
    out[i:i + len(cluster)] += cluster
    hit = bell(1180, 1.8, 0.35)
    out[i:i + len(hit)] += hit
    out = reverb(lowpass(out, 6500), tail=1.8, wet=0.3)
    return normalise(out * env(len(out), 0.01, 1.2), 0.85)


def dark_loop(dur=24):
    """Front page + role assignment: something is wrong in the village."""
    n = int(dur * SR)
    buf = np.zeros((n, 2))
    tt = np.arange(n) / SR
    d = np.zeros(n)
    for f, a in [(41.2, 0.5), (43.2, 0.4), (55.0, 0.3), (77.8, 0.18), (116.5, 0.08)]:
        d += a * np.sin(2 * np.pi * loopf(f, dur) * tt + rng.uniform(0, 6.28))
    buf += (d * slow_wobble(n, 2, 0.6) * 0.20)[:, None]
    w = circular_noise(n, 90, 1500) * slow_wobble(n, 3, 0.8) * 0.12
    buf[:, 0] += w
    buf[:, 1] += np.roll(w, 5000)
    for _ in range(9):                                     # faint whispers
        L = int(rng.uniform(0.35, 0.9) * SR)
        seg = band(rng.standard_normal(L), 1400, 4200) * np.hanning(L) * (0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(4, 7) * np.arange(L) / SR))
        add_wrapped(buf, seg * 0.03, int(rng.uniform(0, dur) * SR), *pan_gains(rng.uniform(0.1, 0.9)))
    for _ in range(5):                                     # metallic scrapes
        f = rng.uniform(900, 2300)
        L = int(2.2 * SR)
        t = np.arange(L) / SR
        s = sum(a * np.sin(2 * np.pi * f * r * t) for r, a in [(1, 1), (2.76, 0.5), (5.4, 0.25)]) * np.exp(-t / 0.5)
        add_wrapped(buf, s * 0.018, int(rng.uniform(0, dur) * SR), *pan_gains(rng.uniform(0.1, 0.9)))
    return normalise(buf, 0.75)


def thump(f0, f1, dur, amp):
    t = tvec(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (dur * 0.28)) * env(len(t), 0.003, 0.05) * amp


def tension_loop(dur=24):
    """Voting and elimination: a heartbeat under dissonant strings (mono)."""
    n = int(dur * SR)
    out = np.zeros(n)
    tt = np.arange(n) / SR
    for k in range(int(dur / 0.8)):                        # 75 beats per minute
        for sig, off in ((thump(70, 38, 0.22, 1.0), 0.0), (thump(62, 34, 0.20, 0.65), 0.28)):
            i = int((k * 0.8 + off) * SR)
            idx = (np.arange(len(sig)) + i) % n
            np.add.at(out, idx, sig)
    pad = sum(a * np.sin(2 * np.pi * loopf(f, dur) * tt) for f, a in [(146.8, 1.0), (155.6, 0.9), (233.1, 0.5), (329.6, 0.3)])
    out += pad * slow_wobble(n, 3, 0.55) * 0.07
    hi = (np.sin(2 * np.pi * loopf(1760, dur) * tt) + np.sin(2 * np.pi * loopf(1864.7, dur) * tt)) * (0.5 + 0.5 * np.sin(2 * np.pi * (9 * tt))) * 0.006
    out += hi
    return normalise(out, 0.75)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def add1(buf, sig, start):
    idx = (np.arange(len(sig)) + int(start * SR)) % len(buf)
    np.add.at(buf, idx, sig)


def tone(f, dur, amp, decay, kind="pluck"):
    t = tvec(dur)
    if kind == "pad":
        s = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.004 * t) + 0.25 * np.sin(4 * np.pi * f * t)) * env(len(t), 0.35, 0.5)
    elif kind == "glock":
        s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 3.0 * t) + 0.15 * np.sin(2 * np.pi * f * 5.4 * t)) * np.exp(-t / decay) * env(len(t), 0.002, 0.04)
    else:
        s = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(4 * np.pi * f * t) + 0.25 * np.sin(6 * np.pi * f * t)) * np.exp(-t / decay) * env(len(t), 0.004, 0.05)
    return s * amp


def win_civilians():
    """Joyful, major-key music (I-V-vi-IV twice, 100 BPM, 19.2 s loop): the nightmare is over."""
    beat = 0.6
    bar = 4 * beat
    n = int(8 * bar * SR)
    out = np.zeros(n)
    chords = [(48, [60, 64, 67]), (43, [59, 62, 67]), (45, [57, 60, 64]), (41, [57, 60, 65])] * 2
    for b, (bass, notes) in enumerate(chords):
        t0 = b * bar
        add1(out, tone(midi(bass), bar * 1.05, 0.55, 0.9), t0)
        for nt in notes:
            add1(out, tone(midi(nt), bar * 1.1, 0.16, 1, "pad"), t0)
        order = [notes[0], notes[1], notes[2], notes[1] + 12, notes[2], notes[1], notes[0] + 12, notes[1]]
        for k, nt in enumerate(order):
            add1(out, tone(midi(nt + 12), 0.5, 0.20, 0.30), t0 + k * beat / 2)
    melody = [
        [(0, 76, 1), (1, 79, 1), (2, 84, 1.5), (3.5, 83, 0.5)], [(0, 86, 1), (1, 83, 1), (2, 79, 2)],
        [(0, 81, 1), (1, 84, 1), (2, 88, 1.5), (3.5, 86, 0.5)], [(0, 84, 1), (1, 81, 1), (2, 77, 2)],
        [(0, 76, 0.5), (0.5, 79, 0.5), (1, 84, 1), (2, 88, 2)], [(0, 86, 1), (1, 91, 1), (2, 83, 1), (3, 86, 1)],
        [(0, 84, 1), (1, 81, 0.5), (1.5, 84, 0.5), (2, 88, 1), (3, 81, 1)], [(0, 83, 1), (1, 86, 1), (2, 79, 2)],
    ]
    for b, notes in enumerate(melody):
        for bt, nt, dur in notes:
            add1(out, tone(midi(nt), max(0.4, dur * beat * 1.4), 0.30, 0.55, "glock"), b * bar + bt * beat)
    for t0, kind in ((1.0, "tweet"), (4.2, "whistle"), (7.6, "tweet"), (11.0, "warble"), (14.4, "tweet"), (17.6, "whistle")):
        add1(out, bird_phrase(kind, 0.35) * 0.35, t0)
    for b in (0, 4):                                       # shimmer at the start of each half
        add1(out, bell(midi(96), 2.2, 0.10), b * bar)
    out = lowpass(out, 9000)
    return normalise(out, 0.8)


def single_laugh(n, f0, gap, seed_shift=0.0):
    total = int((n * gap + 0.9) * SR)
    out = np.zeros(total)
    for k in range(n):
        last = k == n - 1
        d = 0.38 if last else 0.13
        t = tvec(d)
        f = (f0 * (0.965 ** k)) * np.linspace(1.12, 0.88, len(t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        s = np.zeros(len(t))
        fm = float(np.mean(f))
        for h in range(1, 16):
            fh = h * fm
            form = np.exp(-((fh - 780) / 260) ** 2) + 0.7 * np.exp(-((fh - 1250) / 320) ** 2) + 0.12
            s += form / h ** 0.7 * np.sin(h * ph)
        s += band(rng.standard_normal(len(t)), 900, 3500) * 0.25 * np.exp(-t / 0.03)
        s *= env(len(t), 0.012, 0.05) * (1.15 if last else 1.0)
        i = int((k * gap + seed_shift) * SR)
        out[i:i + len(s)] += s[: max(0, total - i)]
    return out


def evil_laugh(n=7, f0=140.0, gap=0.2, vol=1.0):
    a = single_laugh(n, f0, gap)
    b = single_laugh(n, f0 * 0.79, gap, 0.015)
    mix = lowpass(a + 0.6 * b, 4200)
    mix = reverb(mix, tail=2.2, wet=0.35, damp=2600)[: len(a) + int(2.0 * SR)]
    return normalise(mix, 0.9) * vol


def win_mafia(dur=28):
    """Dark music: a tolling bell, thunder, evil laughter and wolves. Everything has ended."""
    n = int(dur * SR)
    out = np.zeros(n)
    tt = np.arange(n) / SR
    drone = sum(a * np.sin(2 * np.pi * loopf(f, dur) * tt) for f, a in [(36.7, 1.0), (51.9, 0.8), (73.4, 0.5), (103.8, 0.25)])
    out += drone * slow_wobble(n, 2, 0.5) * 0.10
    for t0 in (0.5, 7.5, 14.5, 21.5):
        add1(out, bell(98.0, 6.0, 0.75), t0)
    for t0, dd in ((6.0, 3.2), (19.0, 3.6)):                # thunder
        L = int(dd * SR)
        th = lowpass(rng.standard_normal(L), 170) * np.exp(-np.arange(L) / (SR * 1.1)) * env(L, 0.15, 0.5)
        add1(out, normalise(th, 0.7) * 0.9, t0)
    add1(out, evil_laugh(7, 140.0, 0.20, 0.85), 2.6)
    add1(out, evil_laugh(9, 130.0, 0.24, 1.0), 14.0)
    w = wolf()
    add1(out, w * 0.5, 8.8)
    add1(out, w * 0.38, 21.0)
    for t0 in (11.4, 24.5):                                 # dissonant stabs
        L = int(1.6 * SR)
        t = np.arange(L) / SR
        stab = sum(np.sin(h * 2 * np.pi * f * t) / h for f in (103.8, 146.8) for h in range(1, 12)) * np.exp(-t / 0.5)
        add1(out, lowpass(stab, 900) * 0.18, t0)
    for _ in range(8):
        L = int(rng.uniform(0.4, 0.9) * SR)
        seg = band(rng.standard_normal(L), 1400, 4200) * np.hanning(L) * 0.03
        add1(out, seg, rng.uniform(0, dur))
    out = lowpass(out, 8500)
    return normalise(out, 0.85)


# ---------------------------------------------------------------------------------- writing
def write_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    wavfile.write(path, SR, pcm)


def write_mp3(path, x, bitrate="80k"):
    tmp = path.with_suffix(".tmp.wav")
    write_wav(tmp, x)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-ac", "1", "-codec:a", "libmp3lame", "-b:a", bitrate, str(path)], check=True)
    tmp.unlink()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    write_wav(OUT / "day-ambience.wav", day_loop())
    write_wav(OUT / "night-ambience.wav", night_loop())
    write_wav(OUT / "dark-ambience.wav", dark_loop())
    write_wav(OUT / "tension-loop.wav", tension_loop())
    write_mp3(OUT / "owl-hoot.mp3", owl())
    write_mp3(OUT / "wolf-howl.mp3", wolf())
    write_mp3(OUT / "crow-caw.mp3", normalise(crow(3, 0.25), 0.8))
    write_mp3(OUT / "creak.mp3", creak())
    write_mp3(OUT / "morning-bell.mp3", morning())
    write_mp3(OUT / "night-fall.mp3", nightfall())
    write_mp3(OUT / "ui-click.mp3", ui_click(), "64k")
    write_mp3(OUT / "role-reveal.mp3", role_reveal())
    write_mp3(OUT / "win-civilians.mp3", win_civilians(), "96k")
    write_mp3(OUT / "win-mafia.mp3", win_mafia(), "96k")
    for p in sorted(OUT.glob("*")):
        print(f"{p.name:<22}{p.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    sys.exit(main())
