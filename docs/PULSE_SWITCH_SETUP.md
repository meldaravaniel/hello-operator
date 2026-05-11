# Rotary Pulse Switch Setup

A rotary dial generates digits by opening and closing a pulse switch as the dial returns to home position. The number of openings encodes the digit (1 = 1, 10 = 0). hello-operator reads a HIGH GPIO level as "resting" and LOW as "pulsing."

If the pulse switch contacts have been physically disconnected from the phone's 48V loop circuit, they are just a bare mechanical switch and can connect directly to the Pi with a single series resistor.

## Prerequisite: isolate the switch from 48V

Vintage telephone internals run 48VDC loop current. The pulse switch contacts are normally in series with this circuit. **Before wiring to the Pi, confirm the switch contacts carry no line voltage:**

1. Disconnect the phone from the telephone line jack.
2. Physically disconnect (desolder or unclip) the pulse switch wires from the telephone's main circuit board or line terminals.
3. With a multimeter set to DC voltage, measure across the two switch contacts. The reading should be ~0V. If it is not, the switch is still connected to a live circuit — do not proceed.

Once the contacts are isolated, they are a safe low-voltage switch with no path back to 48V.

## How it works

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

## Series resistor

A series resistor between 470Ω and 1kΩ is required. It:
- Limits current if the GPIO pin is ever misconfigured as a logic output (without it, 3.3V would short directly to the pin)
- Provides a small amount of RC filtering against contact bounce

The resistor has no meaningful effect on signal integrity at low frequencies. Current through the resistor when the switch is closed: 3.3V ÷ (1kΩ + 50kΩ internal) ≈ 64μA — well within the Pi's GPIO ratings. The GPIO reads a clean HIGH (~3.27V) with a 1kΩ resistor in this divider.

If you want a more reliable pull-down than the Pi's internal ~50kΩ (useful if the switch leads are long), add an external 10kΩ resistor from GPIO 27 to GND alongside the internal pull-down. An external pull-down also lets you leave the GPIO configured as `GPIO.PUD_OFF` if preferred.

## Wiring to the Raspberry Pi

| Connection | From | To |
|---|---|---|
| 3.3V → series resistor → switch contact A | Pi pin 1 (3.3V) | Switch contact A (via 470Ω–1kΩ resistor) |
| Switch contact B → GPIO 27 | Switch contact B | Pin 13 (GPIO 27) |

Polarity of the switch contacts does not matter — it is a simple mechanical switch.

> **GPIO pin:** The default pulse switch pin is GPIO 27 (`PULSE_SWITCH_PIN = 27` in `src/constants.py`). If you wire to a different pin, update that constant.

> **Tip:** Use [pinout.xyz](https://pinout.xyz) to locate physical pin positions on your Pi revision.

## Verify signal before connecting to the Pi

Confirm the circuit is working correctly before relying on hello-operator:

1. With the Pi powered off, measure resistance across the switch contacts: closed = ~0Ω, open = ∞.
1. Power the Pi. Measure voltage at the GPIO pin (with pull-down enabled in software): switch closed → ~3.3V; switch open → ~0V.

---

## Smoke test with hello-operator

With the sensor wired to GPIO 27 and the Pi booted:

```python
import RPi.GPIO as GPIO
import time

PIN = 27
GPIO.setmode(GPIO.BCM)

GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

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
- The GPIO is floating. Confirm the pull-down is active (check `GPIO.PUD_DOWN` in the smoke test). Check that the switch contact B wire is connected to GPIO 27, not left floating.

**Signal always HIGH (no pulses detected)**
- The switch contacts may not be opening, or the 3.3V side is disconnected. With the switch open, the GPIO should float LOW via the pull-down.

**Erratic or noisy signal**
Contact bounce on the pulse switch may cause rapid glitching around each transition. This is expected for mechanical contacts and is handled by `PULSE_DEBOUNCE` in `src/constants.py`. Tune that constant if pulses are being over- or under-counted.

**Signal voltage reads ~1.5V instead of 0V or 3.3V**
- Weak or missing pull-down. Confirm `GPIO.PUD_DOWN` is set, or add an external 10kΩ to GND.

**Switch contacts still read non-zero voltage after isolation**
The switch has not been fully isolated from the phone's 48V circuit. Trace the wires and confirm both contacts are disconnected from all telephone circuitry before connecting to the Pi.
