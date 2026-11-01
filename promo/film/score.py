"""The CAHON film's sound, on onetake's palette (scripts/sfx_palette.py): one room, playful materials, music under it.

    python3 score.py  → sfx.wav    (beat times come from events.json, dumped from comp.html's __events())

Cold open: no music, the mascot's hops and the red ✕ on each wrong file, a sad little fall, a spinner.
ENTER: a bright chord and the groove starts (made here from scratch: no samples, no licence), 116 BPM.
Every answer gets one sound: a glass "found" chime with the ✓. Music plays all the way through (soft and sad in the
cold open, bright from ENTER) and ends on a chord as the name is written.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.environ.get("ONETAKE", os.path.expanduser("~/onetake")), "scripts"))
from sfx_palette import SR, Score, air, bubble, glass, sub, wobble, wood  # noqa: E402

E = json.load(open(os.path.join(HERE, "events.json")))
T, CL, DUR = E["T"], E["CLICK"], E["DUR"]
ENTER, WRITE = T["enter"], T["end"] + 2.3
rng = np.random.default_rng(11)
s = Score(dur=DUR, T60=1.0)
place = s.place


def click(t, gain=0.26):
    place(wood(240, 0.08), t, gain, 0.0, 0.2)
    place(wood(190, 0.07), t + 0.06, gain * 0.7, 0.0, 0.2)


def keys(t0, n, cps):
    for i in range(n):
        if rng.uniform() < 0.35:
            continue
        place(wood(170 + rng.uniform(-20, 20), 0.08), t0 + i / cps, 0.08 * rng.uniform(0.7, 1.3), -0.05, 0.15)


def found(t, f=1046):  # the ✓: one bright two-note chime
    place(glass(f, 1.0, 0.7), t, 0.2, 0.25, 0.45)
    place(glass(f * 1.5, 1.0, 0.5), t + 0.07, 0.14, 0.3, 0.45)


# ── cold open: the mascot checks three files, all wrong
place(bubble(420, 0.24), 0.02, 0.22, -0.2, 0.3)
for tc in E["CHECK"]:
    place(bubble(460 + rng.uniform(-30, 30), 0.22), tc - 0.35, 0.24, 0.0, 0.3)   # the hop
    place(wood(130, 0.14), tc + 0.22, 0.36, 0.1, 0.25)                           # ✕
    place(sub(90, 0.25), tc + 0.22, 0.18, 0.1, 0.2)
place(wobble(140, 0.6), 1.7, 0.35, 0.0, 0.3)          # "?"
place(bubble(380, 0.26), 2.4, 0.22, -0.2, 0.3)         # hop to the scan
place(air(0.5, 300, 1800, 1.3), 2.75, 0.22, 0.2, 0.4)  # the scan slides in
place(sub(70, 0.6), 3.6, 0.3, 0.0, 0.3)                # can't read it
for i in range(3):                                     # note, link, key pop up...
    place(bubble(560 + i * 80, 0.2), 4.55 + i * 0.12, 0.22, -0.3 + i * 0.3, 0.3)
place(air(0.7, 2600, 300, 1.2, 0.3), 5.2, 0.32, 0.0, 0.5)   # ...and slip away
place(bubble(330, 0.3), 5.5, 0.22, 0.3, 0.3)           # hop to the bar
for k in range(3):                                     # the spinner
    place(glass(1760, 0.12, 0.2), 5.7 + k * 0.28, 0.03, 0.3, 0.05)
# ── ENTER
place(bubble(300, 0.3), ENTER - 0.45, 0.3, 0.2, 0.3)   # the jump
place(sub(60, 0.7), ENTER, 0.45, 0.0, 0.35)
place(air(0.9, 3000, 200, 1.1, 0.25), ENTER + 0.05, 0.4, 0.0, 0.5)
found(ENTER + 0.05, 784)
# ── in the app: clicks, a few keys, one sound per answer
for k in ("box1", "box2", "box3", "box4", "ocr", "excel", "date", "d30", "add", "dir", "choose"):
    click(CL[k])
keys(CL["box1"] + 0.4, 9, 6)
keys(CL["box2"] + 0.4, 6, 4)
keys(CL["box3"] + 0.4, 10, 6)
keys(CL["box4"] + 0.4, 7, 5)
place(air(0.6, 400, 2400, 1.3, 0.5), T["pay1"] - 0.1, 0.26, -0.3, 0.4, pan_to=-0.1)   # the line draws
found(T["pay1"] + 0.15)
place(bubble(520, 0.24), T["pay2"] + 0.15, 0.3, 0.1, 0.3)                              # the lens lands
found(T["pay2"] + 0.5, 1175)
place(bubble(600, 0.22), CL["ocr"] + 0.05, 0.24, 0.3, 0.3)                             # the paper rises
for k in range(2):                                                                     # the beam
    place(air(0.3, 800, 2400, 2.0, 0.5), CL["ocr"] + 0.4 + k * 1.18, 0.07, 0.3, 0.3)
place(air(0.5, 2200, 500, 1.4, 0.3), T["read"] + 0.1, 0.24, 0.2, 0.4)                  # it flies into the text
found(T["read"], 1046)
found(T["read"] + 0.2, 1397)
for i in range(3):                                                                     # badges pop
    place(bubble(500 + i * 90, 0.2), T["type4"] + 1.2 + i * 0.12, 0.22, -0.2 + i * 0.2, 0.3)
place(wobble(170, 0.4), CL["excel"] + 0.4, 0.3, 0.0, 0.3)                              # Excel lands in its chip
for k in range(4):                                                                     # the calendar flips
    place(wood(300 + k * 30, 0.05), CL["date"] + 0.5 + k * (CL["d30"] - CL["date"] - 0.4) / 4, 0.12, 0.2, 0.15)
found(T["pay4"])
place(air(0.6, 300, 2000, 1.3, 0.5), CL["choose"] + 0.05, 0.3, -0.2, 0.4, pan_to=-0.4)  # the folder flies
place(wobble(150, 0.5), CL["choose"] + 0.75, 0.32, -0.3, 0.3)                          # lands
found(T["pay5"], 1046)
found(T["pay5"] + 0.25, 1568)
# ── the end
place(air(0.7, 200, 1800, 1.1, 0.5), T["end"] + 0.4, 0.3, 0.0, 0.6)
place(bubble(300, 0.3), T["end"] + 1.5, 0.3, 0.2, 0.3)
place(bubble(380, 0.3), T["end"] + 2.1, 0.36, 0.3, 0.3)
for i in range(5):
    place(wood(210 + i * 12, 0.08), WRITE + i * 0.1, 0.22, -0.1 + i * 0.05, 0.2)
place(sub(48, 1.2), WRITE + 0.5, 0.42, 0.0, 0.3)

# ── music, from ENTER
BPM, n_total = 116, len(s.dry)
BEAT, t_all = 60 / BPM, np.arange(n_total) / SR


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
bar, t, k = 4 * BEAT, ENTER, 0
while t < WRITE - 0.01:
    chord = [note(n) for n in prog[k % 4]]
    add(t, pad(chord, bar + 0.2), 0, 0.02)
    for b in range(8):
        tb = t + b * BEAT / 2
        if tb >= WRITE:
            continue
        add(tb, tone(chord[(b * 2) % 3] * 2, 0.35, 10), -0.3 if b % 2 else 0.3, 0.045)   # a bouncy pluck
        if b % 2 == 0:
            n = int(0.3 * SR); tt = np.arange(n) / SR
            add(tb, np.sin(2 * np.pi * np.cumsum(50 + 80 * np.exp(-tt * 30)) / SR) * np.exp(-tt * 10), 0, 0.15 if b % 4 == 0 else 0.08)
        else:
            n = int(0.05 * SR); add(tb, rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 90), 0.4, 0.02)  # hat
    t += bar
    k += 1
for i, n in enumerate(("C3", "G3", "E4", "G4", "C5")):
    add(WRITE + 0.5 + i * 0.03, tone(note(n), 2.0, 2.2, 0.2), (i - 2) * 0.2, 0.08)
# the cold open has music too: soft and a little sad (A minor), no drums, until the mascot jumps
sad = [["A3", "C4", "E4"], ["F3", "A3", "C4"], ["D3", "F3", "A3"], ["E3", "G#3", "B3"]]
note_sharp = lambda n: note(n.replace("#", "")) * (2 ** (1 / 12) if "#" in n else 1)
for i, chord in enumerate(sad):
    t0 = i * ENTER / 4
    fs = [note_sharp(n) for n in chord]
    add(t0, pad(fs, ENTER / 4 + 0.4), 0, 0.022)
    for b in range(4):
        add(t0 + b * ENTER / 16, tone(fs[b % 3] * 2, 0.6, 5), -0.25 if b % 2 else 0.25, 0.035)
music *= np.clip((DUR - 0.6 - t_all) / 1.2, 0, 1)[:, None]   # music all the way through; it only fades at the very end
s.dry += music
s.write(os.path.join(HERE, "sfx.wav"), peak_db=-3.5)
