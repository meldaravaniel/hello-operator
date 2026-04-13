# Rotary Pulse Switch Setup

A rotary dial generates digits by opening and closing a pulse switch as the dial returns to home position. The number of openings encodes the digit (1 = 1, 10 = 0). hello-operator reads a HIGH GPIO level as "resting" and LOW as "pulsing."

Two wiring options are described below. Choose based on whether you want galvanic isolation from the phone's internal wiring.

| | Option A — IR Breakbeam | Option B — Direct wire |
|---|---|---|
| Parts | Breakbeam sensor pair + 150Ω resistor | 470Ω–1kΩ resistor |
| Isolation | Yes — optical barrier between switch and GPIO | No — switch contacts connect directly to Pi |
| Prerequisite | None | Switch must be physically disconnected from the phone's 48V loop circuit |

---

## Option A — IR Breakbeam sensor

### How it works

The pulse switch is wired **in series with the IR emitter LED**. When the switch is closed (dial at rest), the LED is powered and the receiver sees the beam. When the switch opens on each pulse, the LED goes dark — simulating a blocked beam without anything needing to pass between the sensors.

```
Pi 3.3V ── R (150Ω) ── IR emitter LED ── pulse switch ── GND

receiver signal ── GPIO 27 (pull-up)
```

| Switch state | LED | Receiver output | GPIO | Meaning |
|---|---|---|---|---|
| Closed (resting) | ON | HIGH | 1 | Dial at rest |
| Open (pulsing) | OFF | LOW | 0 | Pulse |

The optical link is the isolation barrier — the same principle as an optocoupler. There is no electrical path from the pulse switch to the GPIO pin. Voltage spikes or contact bounce on the switch side do not reach the Pi.

### Parts needed

- Adafruit IR Breakbeam sensor pair (3mm or 5mm LED variant)
- 150Ω resistor (for 3.3V supply) — see note below
- 6 jumper wires (female-to-female)
- The rotary dial's pulse switch contacts (wired to the emitter circuit, not GPIO)

> **Resistor value:** The current-limiting resistor goes in series with the emitter LED, not the receiver. For a 3.3V supply and a typical IR LED forward voltage of ~1.2V at 20mA: R = (3.3 − 1.2) / 0.020 ≈ 105Ω — use a 150Ω resistor (slightly conservative, fine for close-range use). If you power the emitter from 5V instead, use a 180–220Ω resistor.

### Pinout

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

### Wiring to the Raspberry Pi

**Emitter circuit**

| Connection | From | To |
|---|---|---|
| 3.3V → 150Ω resistor → emitter red | Pi pin 1 (3.3V) | Emitter red wire (via resistor) |
| Emitter black → pulse switch → GND | Emitter black wire | One pulse switch contact; other contact to Pi GND (pin 6, 9, 14, 20, 25, 30, 34, or 39) |

**Receiver circuit**

| Sensor pin | Raspberry Pi | Physical pin |
|---|---|---|
| Red (power) | 3.3V | Pin 1 or 17 |
| Black (GND) | Ground | Any ground pin above |
| White / Yellow (signal) | GPIO 27 | Pin 13 |

> **5V receiver output warning:** Some breakbeam modules designed for 5V operation output a 5V logic signal. The Pi's GPIO pins are 3.3V-tolerant only — a 5V signal will damage them. Power the receiver from the Pi's 3.3V rail to keep the output signal at 3.3V. If your sensor requires 5V to operate, add a voltage divider (e.g. 10kΩ / 20kΩ) or a level shifter on the receiver signal wire before it reaches GPIO.

### Physical mounting

The emitter and receiver still need to face each other, but no gap or moving mechanism is required between them. They can be mounted anywhere convenient because the switching happens electrically, not physically.

1. Mount the emitter and receiver so they have line of sight to each other.
2. Wire the emitter into the pulse switch circuit as described above.
3. Connect the receiver signal wire to GPIO 27.
4. Do **not** remove or bypass the pulse switch contacts — the switch is the active part of the circuit.

Secure both sensors to prevent them from shifting; the emitter and receiver still need to maintain alignment with each other.

---

## Option B — Direct wire

If the pulse switch contacts have been physically disconnected from the phone's 48V loop circuit, they are just a bare mechanical switch and can connect directly to the Pi with a single series resistor.

### Prerequisite: isolate the switch from 48V

Vintage telephone internals run 48VDC loop current. The pulse switch contacts are normally in series with this circuit. **Before wiring to the Pi, confirm the switch contacts carry no line voltage:**

1. Disconnect the phone from the telephone line jack.
2. Physically disconnect (desolder or unclip) the pulse switch wires from the telephone's main circuit board or line terminals.
3. With a multimeter set to DC voltage, measure across the two switch contacts. The reading should be ~0V. If it is not, the switch is still connected to a live circuit — do not proceed.

Once the contacts are isolated, they are a safe low-voltage switch with no path back to 48V.

### How it works

The rotary pulse switch is normally closed at rest and opens briefly on each pulse. The circuit connects one contact to the Pi's 3.3V rail through a series resistor; the other contact connects to the GPIO pin. An internal pull-down holds the GPIO LOW when the switch opens.

```
Pi 3.3V ── [470Ω–1kΩ] ── (pulse switch) ── GPIO 27 (pull-down)
                                             │
                                          ~50kΩ internal pull-down
                                             │
                                            GND
```

| Switch state | GPIO | Meaning |
|---|---|---|
| Closed (resting) | HIGH (~3.3V) | Dial at rest |
| Open (pulsing) | LOW (pulled to GND) | Pulse |

### Series resistor

A series resistor between 470Ω and 1kΩ is required. It:
- Limits current if the GPIO pin is ever misconfigured as a logic output (without it, 3.3V would short directly to the pin)
- Provides a small amount of RC filtering against contact bounce

The resistor has no meaningful effect on signal integrity at low frequencies. Current through the resistor when the switch is closed: 3.3V ÷ (1kΩ + 50kΩ internal) ≈ 64μA — well within the Pi's GPIO ratings. The GPIO reads a clean HIGH (~3.27V) with a 1kΩ resistor in this divider.

If you want a more reliable pull-down than the Pi's internal ~50kΩ (useful if the switch leads are long), add an external 10kΩ resistor from GPIO 27 to GND alongside the internal pull-down. An external pull-down also lets you leave the GPIO configured as `GPIO.PUD_OFF` if preferred.

### Wiring to the Raspberry Pi

| Connection | From | To |
|---|---|---|
| 3.3V → series resistor → switch contact A | Pi pin 1 (3.3V) | Switch contact A (via 470Ω–1kΩ resistor) |
| Switch contact B → GPIO 27 | Switch contact B | Pin 13 (GPIO 27) |

Polarity of the switch contacts does not matter — it is a simple mechanical switch.

> **GPIO pin:** The default pulse switch pin is GPIO 27 (`PULSE_SWITCH_PIN = 27` in `src/constants.py`). If you wire to a different pin, update that constant.

> **Tip:** Use [pinout.xyz](https://pinout.xyz) to locate physical pin positions on your Pi revision.

### Required code change in `main.py`

The breakbeam receiver (Option A) uses an open-collector output that requires a **pull-up**. The direct connection (Option B) requires a **pull-down**. These are incompatible, so one line in `src/main.py` must be changed before running hello-operator with a direct-wired switch.

Find the `build_gpio_handler()` function and change the pulse pin setup from `GPIO.PUD_UP` to `GPIO.PUD_DOWN`:

```python
# Option A (breakbeam) — default
GPIO.setup(PULSE_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Option B (direct wire) — change to this
GPIO.setup(PULSE_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
```

Only the pulse pin needs to change. The hook switch (`HOOK_SWITCH_PIN`) keeps `GPIO.PUD_UP` regardless of which option you use for the pulse switch.

---

## Verify signal before connecting to the Pi

For either option, confirm the circuit is working correctly before relying on hello-operator:

**Option A (breakbeam):**
1. Power the emitter circuit (3.3V → resistor → LED → switch → GND) and the receiver from the Pi.
2. Add a temporary 10kΩ pull-up from the receiver signal wire to 3.3V.
3. Measure voltage on the receiver signal wire: switch closed → ~3.3V; switch open → ~0V.
4. Remove the temporary resistor before connecting to GPIO.

**Option B (direct):**
1. With the Pi powered off, measure resistance across the switch contacts: closed = ~0Ω, open = ∞.
2. Power the Pi. Measure voltage at the GPIO pin (with pull-down enabled in software): switch closed → ~3.3V; switch open → ~0V.

---

## Smoke test with hello-operator

With the sensor wired to GPIO 27 and the Pi booted:

```python
import RPi.GPIO as GPIO
import time

PIN = 27
GPIO.setmode(GPIO.BCM)

# Option A (breakbeam):
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Option B (direct wire) — use this line instead:
# GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

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
- *Option A:* The LED is not lighting up. Check emitter power, the resistor, and that the pulse switch contacts are currently closed. If the contacts are open at rest the LED will never light.
- *Option B:* The GPIO is floating. Confirm the pull-down is active (check `GPIO.PUD_DOWN` in the smoke test). Check that the switch contact B wire is connected to GPIO 27, not left floating.

**Signal always HIGH (no pulses detected)**
- *Option A:* The receiver never sees a dark period. Check that the pulse switch contacts actually open when the dial moves. Confirm emitter and receiver are aligned.
- *Option B:* The switch contacts may not be opening, or the 3.3V side is disconnected. With the switch open, the GPIO should float LOW via the pull-down.

**Erratic or noisy signal**
Contact bounce on the pulse switch may cause rapid glitching around each transition. This is expected for mechanical contacts and is handled by `PULSE_DEBOUNCE` in `src/constants.py`. Tune that constant if pulses are being over- or under-counted.

**Signal voltage reads ~1.5V instead of 0V or 3.3V**
- *Option A:* The receiver output needs a pull-up. Confirm `GPIO.PUD_UP` is set. If testing outside hello-operator, add a 10kΩ resistor from the signal wire to 3.3V.
- *Option B:* Weak or missing pull-down. Confirm `GPIO.PUD_DOWN` is set, or add an external 10kΩ to GND.

**Ambient light interference (Option A only)**
The sensors are sensitive to strong IR sources including direct sunlight. Shield the receiver from direct ambient light or orient it so the only IR source it sees is the emitter.

**Switch contacts still read non-zero voltage after isolation (Option B)**
The switch has not been fully isolated from the phone's 48V circuit. Trace the wires and confirm both contacts are disconnected from all telephone circuitry before connecting to the Pi.
