# IR Breakbeam Sensor Setup (Rotary Pulse Switch)

This guide covers wiring the Adafruit IR Breakbeam sensors as the optocoupler for the rotary dial pulse switch on a Raspberry Pi 4.

Original documentation: https://learn.adafruit.com/ir-breakbeam-sensors

---

## How it works

A rotary dial generates digits by opening and closing a pulse switch as the dial returns to home position. The number of interruptions encodes the digit (1 pulse = 1, 10 pulses = 0).

The IR breakbeam replaces a mechanical switch contact. The emitter shines a continuous beam of infrared light at the receiver. A wheel or tab on the dial mechanism passes through the gap on each pulse, briefly blocking the beam. Each interruption is one pulse.

hello-operator reads these as:

| Beam state | Receiver output | Meaning |
|---|---|---|
| Intact | HIGH (1) | Resting — dial not pulsing |
| Broken | LOW (0) | Pulse — beam is blocked |

---

## Parts needed

- Adafruit IR Breakbeam sensor pair (3mm or 5mm LED variant)
- 5 jumper wires (female-to-female)
- A way to mount the emitter and receiver on opposite sides of the dial mechanism's pulse wheel

---

## Pinout

**Emitter (2 wires)**

| Wire colour | Function |
|---|---|
| Red | Power — 3.3V or 5V |
| Black | Ground |

**Receiver (3 wires)**

| Wire colour | Function |
|---|---|
| Red | Power — 3.3V or 5V |
| Black | Ground |
| White / Yellow | Signal output (open-collector — reads HIGH at rest, LOW when beam is blocked) |

> **Note:** The receiver output is open-collector. A pull-up resistor is required. hello-operator enables the Raspberry Pi's internal pull-up in software (`GPIO.PUD_UP`), so **no external resistor is needed**.

---

## Wiring to the Raspberry Pi

Connect both sensors to the Pi's 40-pin GPIO header. Use 3.3V for power — this keeps the signal levels consistent and draws less current (9mA vs 20mA at 5V).

| Sensor | Sensor pin | Raspberry Pi | Physical pin |
|---|---|---|---|
| Emitter | Red (power) | 3.3V | Pin 1 or 17 |
| Emitter | Black (GND) | Ground | Pin 6, 9, 14, 20, 25, 30, 34, or 39 |
| Receiver | Red (power) | 3.3V | Pin 1 or 17 |
| Receiver | Black (GND) | Ground | (any ground pin above) |
| Receiver | White / Yellow (signal) | GPIO 27 | Pin 13 |

> **GPIO pin:** The default pulse switch pin is GPIO 27 (`PULSE_SWITCH_PIN = 27` in `src/constants.py`). If you wire to a different pin, update that constant.

> **Tip:** Use [pinout.xyz](https://pinout.xyz) to locate the physical pin positions on your Pi revision.

---

## Physical mounting

The emitter and receiver must face each other directly across a gap, with the rotary dial's pulse wheel passing through that gap.

1. Identify the pulse wheel on your rotary dial mechanism — this is the toothed or tabbed wheel that opens and closes the original pulse switch contacts as the dial returns to home.
2. Remove or bypass the original pulse switch contacts.
3. Mount the emitter on one side of the wheel's travel path and the receiver on the other, aligned so the beam passes cleanly through the gap in the wheel at rest.
4. Verify alignment: the receiver signal wire should read HIGH (3.3V) with the beam clear and drop to near 0V each time a tab passes through.

Secure both sensors so they cannot shift — even a small misalignment will cause missed pulses or constant triggering.

---

## Verify signal with a multimeter or oscilloscope

Before connecting to the Pi, confirm the sensor is working:

1. Power the emitter and receiver from the Pi's 3.3V and GND pins.
2. Connect a 10kΩ resistor from the receiver signal wire to 3.3V (temporary external pull-up).
3. Measure voltage on the signal wire:
   - Beam clear → ~3.3V
   - Beam blocked (pass your finger through) → ~0V
4. Remove the temporary resistor before connecting to the Pi (the Pi's internal pull-up takes over).

---

## Smoke test with hello-operator

With the sensor wired to GPIO 27 and the Pi booted:

```python
import RPi.GPIO as GPIO
import time

PIN = 27
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Watching GPIO 27 — break the beam to test. Ctrl+C to stop.")
last = GPIO.input(PIN)
while True:
    val = GPIO.input(PIN)
    if val != last:
        print("BEAM BROKEN" if val == 0 else "beam clear")
        last = val
    time.sleep(0.001)
```

Run this script and pass the dial wheel (or your finger) through the beam. You should see `BEAM BROKEN` on each interruption and `beam clear` when the path is open.

---

## Troubleshooting

**Signal always LOW (beam appears always broken)**
Check that the emitter is powered and the two sensors are aligned. A misaligned emitter will not reach the receiver.

**Signal always HIGH (beam never breaks)**
Confirm the sensor wires are not swapped between emitter and receiver. Verify that the pulse wheel actually passes through the beam gap during a dial stroke.

**Missed pulses during dialing**
The sensors may be partially misaligned, causing glancing interruptions that are too short to register. Adjust mounting until the signal drops cleanly to 0V on each pulse. Also ensure `PULSE_DEBOUNCE` in `src/constants.py` is tuned for your mechanism.

**Ambient light interference**
The sensors are sensitive to strong IR sources including direct sunlight. Mount the sensors shielded from direct light, or orient them so ambient light does not shine straight into the receiver.
