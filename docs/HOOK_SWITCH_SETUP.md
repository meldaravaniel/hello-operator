# Hook Switch Setup (Handset Detect)

This guide covers wiring the rotary phone's hook switch to the Raspberry Pi 4 so that hello-operator can detect when the handset is lifted or replaced.

---

## How it works

A rotary phone's hook switch is a simple mechanical switch actuated by the handset cradle. When the handset sits on the cradle, its weight depresses the hook, holding the switch contacts **open**. When the handset is lifted, a spring pushes the hook up and the contacts **close**.

hello-operator wires one switch terminal to GPIO and the other to GND, with the Pi's internal pull-up resistor enabled in software. The result:

| Handset position | Switch | GPIO 17 |
|---|---|---|
| On cradle (hook depressed) | Open | HIGH (pulled up) |
| Lifted (hook released) | Closed | LOW (shorted to GND) |

No external power, resistors, or optocoupler are needed. The hook switch is a passive mechanical contact — it only connects GPIO to GND and draws the Pi's internal pull-up current (~65µA), well within safe limits.

---

## Parts needed

- The rotary phone's existing hook switch (already inside the phone body)
- 2 jumper wires (female-to-female, or stripped wire if soldering directly)

---

## Wiring

Connect the two hook switch terminals to the Pi's GPIO header. Polarity does not matter — the switch just shorts the two terminals together.

| Hook switch terminal | Raspberry Pi | Physical pin |
|---|---|---|
| Terminal 1 | GPIO 17 | Pin 11 |
| Terminal 2 | Ground | Pin 6, 9, 14, 20, 25, 30, 34, or 39 |

> **GPIO pin:** The default hook switch pin is GPIO 17 (`HOOK_SWITCH_PIN = 17` in `src/constants.py`). If you wire to a different pin, update that constant.

> **Tip:** Use [pinout.xyz](https://pinout.xyz) to locate physical pin positions on your Pi revision.

The pull-up is enabled in software — no external resistor is needed on either terminal.

---

## Finding the hook switch inside the phone

Hook switch location varies by phone model, but the contacts are always in the cradle area where the handset rests. Common arrangements:

- **Lever-actuated contacts** — a plastic or metal lever rides on the hook plunger; the contacts are a pair of metal fingers that open and close as the lever moves.
- **Push-button contacts** — a small button is depressed by the handset's weight; contacts are underneath.
- **Multi-pole switch** — some phones have a multi-pole hook switch that disconnects several circuits at once. You only need the pair of contacts that open when the handset is down and close when it is lifted. Use a multimeter in continuity mode to identify the correct pair.

To locate the right pair of contacts:
1. Remove the phone's base cover (typically two to four screws on the bottom).
2. Set a multimeter to continuity mode.
3. With the handset **on** the cradle, probe pairs of terminals on the switch until you find one that shows **open** (no continuity).
4. Lift the handset — the same pair should now show **closed** (continuity).
5. That is the pair to wire.

---

## Verify with a multimeter

Before connecting to the Pi:

1. Set your multimeter to continuity or resistance mode.
2. Probe the two identified switch terminals.
3. Handset on cradle → open circuit (no continuity / infinite resistance).
4. Handset lifted → closed circuit (continuity / near-zero resistance).

If the result is reversed (closed on cradle, open when lifted), you have either identified a normally-closed contact pair or a different pole of the switch. Find the correct pair before wiring.

---

## Smoke test with hello-operator

With the switch wired to GPIO 17 and the Pi booted:

```python
import RPi.GPIO as GPIO
import time

PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Watching GPIO 17 — lift and replace the handset. Ctrl+C to stop.")
last = GPIO.input(PIN)
while True:
    val = GPIO.input(PIN)
    if val != last:
        print("LIFTED" if val == 0 else "on cradle")
        last = val
    time.sleep(0.005)
```

Lift and replace the handset several times. You should see clean `LIFTED` and `on cradle` transitions with no spurious events between them. If you see rapid flickering around each transition, the contacts are bouncing — this is handled by `HOOK_DEBOUNCE` in `src/constants.py` (default 50ms); increase it if bouncing persists.

---

## Troubleshooting

**Always reads LOW (always appears lifted)**
Either the switch contacts are wired to two GND pins, or the contacts are permanently closed. Re-check which terminal pair you identified: the correct pair is open when the handset is down.

**Always reads HIGH (never detects lift)**
The switch contacts are not connecting GPIO to GND when the handset is lifted. Check for a broken wire, a loose terminal connection, or a misidentified contact pair (you may have the normally-closed pair that opens on lift).

**Spurious events — flickering between LIFTED and on cradle**
Contact bounce on the hook switch mechanism. Increase `HOOK_DEBOUNCE` in `src/constants.py` (try 0.1s) and re-run the smoke test. If the problem persists, add a 100nF ceramic capacitor across the two switch terminals to suppress bounce in hardware.

**hello-operator fires HANDSET_LIFTED immediately on startup**
The handset was off the cradle when the Pi booted, or the wiring is reversed (switch closed at rest). Confirm the handset is seated on the cradle, then recheck which contact pair reads open when the handset is down.
