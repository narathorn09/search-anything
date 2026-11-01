"""The CAHON film's sound, on onetake's palette (scripts/sfx_palette.py): one room, few events, music under it.

    python3 score.py  → sfx.wav

No music in the cold open (the system search fails in silence: keys, a spinner, a thud).
At ENTER (3.1 s) a light groove starts, made here from scratch (no samples, no licence), 120 BPM.
It drops out for the dead-still hold on the highlight, comes back, and ends on a chord as the name is written.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.environ.get("ONETAKE", os.path.expanduser("~/onetake")), "scripts"))
from sfx_palette import SR, Score, air, bubble, glass, pan_of, sub, wood  # noqa: E402

DUR = 31.6
ENTER, WRITE, LAND = 3.1, 29.0, 28.6
rng = np.random.default_rng(11)
s = Score(dur=DUR, T60=1.0)
place = s.place

# ── cold open: the system search ───────────────────────────────────────────
for i in range(9):  # "สัญญาเช่า" typed
    place(wood(175 + rng.uniform(-20, 20), 0.08), 0.35 + i / 11, 0.12 * rng.uniform(0.7, 1.2), -0.05, 0.15)
for k in range(8):  # the spinner ticking
    place(glass(1760, 0.12, 0.2), 1.05 + k * 0.1, 0.03, 0.2, 0.2)
place(sub(52, 0.9), 1.85, 0.5, 0.0, 0.35)  # "ไม่พบรายการ"
for i, t in enumerate((2.0, 2.3, 2.6)):  # the three questions
    place(sub(78 - i * 6, 0.45), t, 0.38, 0.0, 0.25)
# ── ENTER: the box becomes CAHON's ─────────────────────────────────────────
place(air(0.9, 3000, 200, 1.1, 0.25), ENTER - 0.05, 0.5, 0.0, 0.5)
place(glass(784, 1.4, 0.7), ENTER + 0.05, 0.22, -0.1, 0.6)
place(glass(1175, 1.4, 0.5), ENTER + 0.08, 0.16, 0.1, 0.6)
# ── the hand in the app: clicks are wood, a few keys, whips are air ─────────
for t in (4.3, 6.6, 8.0, 12.7, 13.5, 18.8, 19.4, 20.0, 22.8, 24.3):
    place(wood(240, 0.08), t, 0.26, 0.0, 0.2)
    place(wood(190, 0.07), t + 0.06, 0.18, 0.0, 0.2)
for t0, n, cps in ((4.4, 9, 9), (8.2, 6, 8), (11.5, 10, 11), (17.4, 7, 10)):
    for i in range(n):
        if rng.uniform() < 0.4:
            continue
        place(wood(170 + rng.uniform(-20, 20), 0.08), t0 + i / cps, 0.08 * rng.uniform(0.7, 1.3), -0.05, 0.15)
for t, p in ((8.1, -0.4), (9.55, 0.3), (11.05, -0.3), (17.35, -0.4), (18.25, 0.3), (19.35, -0.2), (20.25, 0.2)):
    place(air(0.38, 300, 2600, 1.3, 0.4), t - 0.12, 0.30, p, 0.4, pan_to=-p)
place(bubble(520, 0.24), 9.6, 0.30, -0.1, 0.3)          # the highlight inside the file
place(glass(1046, 1.0, 0.6), 14.9, 0.2, 0.3, 0.5)        # OCR done
place(glass(1568, 1.0, 0.5), 14.95, 0.14, 0.3, 0.5)
for t in (18.25, 19.35, 20.05):                          # the burst
    place(sub(70, 0.4), t, 0.3, 0.0, 0.25)
place(bubble(480, 0.24), 26.5, 0.28, -0.2, 0.3)         # the new folder is scanned
# ── the end ────────────────────────────────────────────────────────────────
place(air(0.7, 200, 1800, 1.1, 0.5), 27.4, 0.35, 0.0, 0.6)  # pull back
place(bubble(380, 0.3), LAND, 0.36, 0.3, 0.3)                # the mascot lands on the box
for i in range(5):                                           # C A H O N
    place(wood(210 + i * 12, 0.08), WRITE + i * 0.09, 0.22, -0.1 + i * 0.05, 0.2)
place(sub(48, 1.4), WRITE + 0.45, 0.45, 0.0, 0.45)

# ── music, from ENTER ──────────────────────────────────────────────────────
BPM = 120
BEAT = 60 / BPM
n_total = len(s.dry)
t_all = np.arange(n_total) / SR


def note(name):
    names = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return 440.0 * 2 ** ((names[name[0]] + 12 * (int(name[-1]) + 1) - 69) / 12)


def tone(f, dur, decay, harm=0.3):
    n = int(dur * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * t) + harm * np.sin(4 * np.pi * f * t)) * np.exp(-t * decay) * np.minimum(1, t / 0.005)


def pad(fs, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 1.004 * t) for f in fs)
    return x * np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.4)


music = np.zeros((n_total, 2))


def add(t, sig, pan=0.0, g=1.0):
    i = int(t * SR)
    if i >= n_total:
        return
    sig = sig[: n_total - i] * g
    music[i:i + len(sig), 0] += sig * np.sqrt(0.5 * (1 - pan))
    music[i:i + len(sig), 1] += sig * np.sqrt(0.5 * (1 + pan))


prog = [["C4", "E4", "G4"], ["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "B3", "D4"]]
bar = 4 * BEAT
t = ENTER
k = 0
REST = (9.6, 10.6)  # the dead-still hold: the music breathes out
while t < WRITE - 0.01:
    chord = [note(n) for n in prog[k % 4]]
    add(t, pad(chord, bar + 0.2), 0, 0.022)
    for b in range(8):
        tb = t + b * BEAT / 2
        if REST[0] <= tb < REST[1] or tb >= WRITE:
            continue
        add(tb, tone(chord[b % 3] * 2, 0.4, 9), -0.3 if b % 2 else 0.3, 0.05)
        if b % 2 == 0:
            n = int(0.3 * SR); tt = np.arange(n) / SR
            kick = np.sin(2 * np.pi * np.cumsum(50 + 80 * np.exp(-tt * 30)) / SR) * np.exp(-tt * 10)
            add(tb, kick, 0, 0.16 if b % 4 == 0 else 0.09)
    t += bar
    k += 1
for i, n in enumerate(("C3", "G3", "E4", "G4", "C5")):  # the name: a last chord that rings out
    add(WRITE + 0.45 + i * 0.03, tone(note(n), 3.0, 1.1, 0.2), (i - 2) * 0.2, 0.08)
music *= np.minimum(1, (DUR - t_all) / 1.2)[:, None].clip(0, 1)
s.dry += music
s.write(os.path.join(HERE, "sfx.wav"), peak_db=-3.5)
