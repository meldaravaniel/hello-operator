# IR Breakbeam Sensor Setup (Rotary Pulse Switch)

This guide covers wiring the Adafruit IR Breakbeam sensors as the pulse switch interface for the rotary dial on a Raspberry Pi 4.

Original documentation: https://learn.adafruit.com/ir-breakbeam-sensors

---

## How it works

A rotary dial generates digits by opening and closing a pulse switch as the dial returns to home position. The number of interruptions encodes the digit (1 pulse = 1, 10 pulses = 0).

Rather than mounting the emitter and receiver across a physical gap and relying on something passing through the beam, the pulse switch is wired **in series with the IR emitter LED**. When the switch is closed (dial at rest), the LED is powered and the receiver sees the beam. When the switch opens on each pulse, the LED goes dark and the receiver sees no beam — simulating a blocked beam without anything needing to pass between the sensors.

```
Pi 3.3V ── R (150Ω) ── IR emitter LED ── pulse switch ── GND

receiver signal ── GPIO 27
```

hello-operator reads these as:

| Switch state | LED | Receiver output | Meaning |
|---|---|---|---|
| Closed (resting) | ON | HIGH (1) | Dial at rest |
| Open (pulsing) | OFF | LOW (0) | Pulse |

### Galvanic isolation

The optical link between emitter and receiver is the isolation barrier — the same principle as an optocoupler. The GPIO pin connects only to the receiver output; there is no electrical path from the pulse switch to the GPIO pin. Voltage spikes or contact bounce on the switch side do not reach the Pi.

---

## Parts needed

- Adafruit IR Breakbeam sensor pair (3mm or 5mm LED variant)
- 150Ω resistor (for 3.3V supply) — see note below
- 6 jumper wires (female-to-female)
- The rotary dial's pulse switch contacts (wired to the emitter circuit, not GPIO)

> **Resistor value:** The current-limiting resistor goes in series with the emitter LED, not the receiver. For a 3.3V supply and a typical IR LED forward voltage of ~1.2V at 20mA: R = (3.3 − 1.2) / 0.020 ≈ 105Ω — use a 150Ω resistor (slightly conservative, slightly dimmer, fine for close-range use). If you power the emitter from 5V instead, use a 180–220Ω resistor.

---

## Pinout

**Emitter (2 wires + pulse switch)**

| Wire colour | Function |
|---|---|
| Red | Power — connects to 3.3V via the 150Ω resistor |
| Black | Ground — connects via the pulse switch contacts |

The pulse switch is wired in the ground leg of the emitter circuit: one switch contact to the emitter's black wire, the other contact to GND on the Pi. Either leg (power or ground) works electrically; the ground leg is slightly simpler to wire.

**Receiver (3 wires)**

| Wire colour | Function |
|---|---|
| Red | Power — 3.3V |
| Black | Ground |
| White / Yellow | Signal output (open-collector — reads HIGH at rest, LOW when beam is off) |

> **Note:** The receiver output is open-collector. A pull-up resistor is required. hello-operator enables the Raspberry Pi's internal pull-up in software (`GPIO.PUD_UP`), so **no external resistor is needed** on the receiver signal wire.

---

## Wiring to the Raspberry Pi

### Emitter circuit

| Connection | From | To |
|---|---|---|
| 3.3V → 150Ω resistor → emitter red | Pi pin 1 (3.3V) | Emitter red wire (via resistor) |
| Emitter black → pulse switch → GND | Emitter black wire | One pulse switch contact; other contact to Pi GND (pin 6, 9, 14, 20, 25, 30, 34, or 39) |

### Receiver circuit

| Sensor pin | Raspberry Pi | Physical pin |
|---|---|---|
| Red (power) | 3.3V | Pin 1 or 17 |
| Black (GND) | Ground | Any ground pin above |
| White / Yellow (signal) | GPIO 27 | Pin 13 |

> **GPIO pin:** The default pulse switch pin is GPIO 27 (`PULSE_SWITCH_PIN = 27` in `src/constants.py`). If you wire to a different pin, update that constant.

> **Tip:** Use [pinout.xyz](https://pinout.xyz) to locate physical pin positions on your Pi revision.

> **5V receiver output warning:** Some breakbeam receiver modules designed for 5V operation output a 5V logic signal. The Pi's GPIO pins are 3.3V-tolerant only — a 5V signal will damage them. Power the receiver from the Pi's 3.3V rail (not 5V) to keep the output signal at 3.3V. If your sensor requires 5V to operate, add a voltage divider (e.g. 10kΩ / 20kΩ) or a level shifter on the receiver signal wire before it reaches GPIO.

---

## Physical mounting

The emitter and receiver still need to face each other, but no gap or moving mechanism is required between them. They can be mounted anywhere convenient — even close together or pointing at a static reflector — because the switching happens electrically, not physically.

1. Mount the emitter and receiver so they have line of sight to each other.
2. Wire the emitter into the pulse switch circuit as described above.
3. Connect the receiver signal wire to GPIO 27.
4. Do **not** remove or bypass the pulse switch contacts — the switch is now the active part of the circuit.

Secure both sensors to prevent them from shifting; even though no physical interception is needed, the emitter and receiver still need to maintain alignment with each other.

---

## Verify signal with a multimeter or oscilloscope

Before connecting to the Pi, confirm the sensor is working:

1. Power the emitter circuit (3.3V → resistor → emitter LED → switch → GND) and the receiver from the Pi.
2. Connect a 10kΩ resistor from the receiver signal wire to 3.3V as a temporary external pull-up.
3. Measure voltage on the receiver signal wire:
   - Switch closed → LED on → beam received → ~3.3V
   - Switch open (manually lift one contact) → LED off → ~0V
4. Remove the temporary resistor before relying on the Pi's internal pull-up.

---

## Smoke test with hello-operator

With the sensor wired to GPIO 27 and the Pi booted:

```python
import RPi.GPIO as GPIO
import time

PIN = 27
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Watching GPIO 27 — open the pulse switch to test. Ctrl+C to stop.")
last = GPIO.input(PIN)
while True:
    val = GPIO.input(PIN)
    if val != last:
        print("PULSE (switch open)" if val == 0 else "resting (switch closed)")
        last = val
    time.sleep(0.001)
```

Run this script and manually open and close the pulse switch contacts (or dial a number). You should see `PULSE (switch open)` on each opening and `resting (switch closed)` when closed. Dial the digit 1 and confirm exactly one pulse is reported.

---

## Troubleshooting

**Signal always LOW (reads as constant pulsing)**
The LED is not lighting up. Check that the emitter is receiving power, the resistor is in place, and the pulse switch contacts are currently closed. If the switch contacts are open at rest, the LED will never light.

**Signal always HIGH (no pulses detected)**
The receiver never sees a dark period. Check that the pulse switch contacts actually open when the dial moves. Confirm the emitter and receiver are still aligned (receiver must see the emitter's beam when the switch is closed).

**Erratic or noisy signal**
Contact bounce on the pulse switch may cause rapid glitching around each transition. This is expected for mechanical contacts and is handled by `PULSE_DEBOUNCE` in `src/constants.py`. Tune that constant if pulses are being over- or under-counted.

**Signal voltage reads ~1.5V instead of 0V or 3.3V**
The receiver output needs a pull-up. Confirm `GPIO.PUD_UP` is set in software. If testing outside of hello-operator, add a 10kΩ resistor from the signal wire to 3.3V.

**Ambient light interference**
The sensors are sensitive to strong IR sources including direct sunlight. Shield the receiver from direct ambient light or orient it so the only IR source it sees is the emitter.
