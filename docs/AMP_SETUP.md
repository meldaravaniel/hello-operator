# Adafruit MAX98357 I2S Amplifier Setup

This guide covers wiring and configuring the Adafruit MAX98357 I2S Class-D Mono Amplifier on a Raspberry Pi 4.

Original documentation: https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp?view=all

---

## Overview

The MAX98357 is a small I2S digital amplifier that delivers up to 3.2W into a 4Ω speaker from a 5V supply. It takes audio directly from the Pi's I2S bus — no USB audio adapter or 3.5mm jack needed. It requires no master clock (MCLK), making wiring straightforward.

---

## Parts needed

- Adafruit MAX98357 I2S amplifier breakout board
- A 4Ω or 8Ω speaker (3W or higher rated)
- 5 jumper wires (female-to-female or female-to-male depending on your setup)
- A 5V power supply capable of at least 800mA (the Pi's own 5V rail is fine for moderate volumes)

---

## Step 1 — Wire the amplifier to the Raspberry Pi

Connect the MAX98357 to the Pi's 40-pin GPIO header using the following table. Pin numbers refer to BCM GPIO numbering; physical header positions are shown for reference.

| MAX98357 pin | Raspberry Pi | Physical pin |
|---|---|---|
| Vin | 5V power | Pin 2 or 4 |
| GND | Ground | Pin 6, 9, 14, 20, 25, 30, 34, or 39 |
| DIN | GPIO 21 | Pin 40 |
| BCLK | GPIO 18 | Pin 12 |
| LRCLK | GPIO 19 | Pin 35 |
| SD | GPIO 22 | Pin 15 |

Leave **MCLK** unconnected — the MAX98357 does not require it.

> **SD pin:** connecting SD to GPIO 22 enables software-controlled startup sequencing that eliminates the amplifier's power-on transient (see [SD pin control](#sd-pin-gpio-control-startup-transient-elimination) below). If you prefer simpler wiring, connect SD directly to Vin instead — the amp will always be on, and a brief transient will occur when hello-operator starts.

> **Tip:** Use [pinout.xyz](https://pinout.xyz) to locate pins on your specific Pi revision.

---

## Step 2 — Wire the speaker

Connect your speaker to the two screw terminals on the MAX98357 board labelled **+** and **−**. Polarity matters for stereo setups but is not critical for mono use — if the sound seems phase-reversed, swap the wires.

The output is a bridge-tied load (BTL). Do **not** connect the output terminals to ground or to another amplifier input.

---

## Step 3 — Configure the Raspberry Pi

### 3a — Run the Adafruit installer script

Adafruit provides an installer script that applies all required config changes automatically:

```bash
sudo apt install -y python3-venv wget
python3 -m venv env --system-site-packages
source env/bin/activate
pip3 install adafruit-python-shell
wget https://github.com/adafruit/Raspberry-Pi-Installer-Scripts/raw/main/i2samp.py
sudo -E env PATH=$PATH python3 i2samp.py
```

When prompted, allow the script to reboot. After the reboot, run it again and answer **y** to the speaker test — you should hear audio from your speaker.

### 3b — Manual configuration (if you prefer not to use the installer)

The installer makes the following changes. Apply them manually if needed:

**`/boot/firmware/config.txt`** (use `/boot/config.txt` on older Raspberry Pi OS):

```
# Disable the built-in audio
dtparam=audio=off

# Enable the MAX98357 I2S amplifier
dtoverlay=max98357a
```

**`/etc/modprobe.d/raspi-blacklist.conf`** — comment out these lines if present:

```
#blacklist i2c-bcm2708
#blacklist snd-soc-pcm512x
#blacklist snd-soc-wm8804
```

**`/etc/modules`** — comment out this line if present:

```
#snd_bcm2835
```

**`/etc/asound.conf`** — create or replace with:

```
pcm.speakerbonnet {
    type hw
    card 0
}

pcm.dmixer {
    type dmix
    ipc_key 1024
    ipc_perm 0666
    slave {
        pcm "speakerbonnet"
        period_time 0
        period_size 1024
        buffer_size 8192
        rate 44100
        channels 2
    }
}

pcm.softvol {
    type softvol
    slave.pcm "dmixer"
    control.name "PCM"
    control.card 0
}

pcm.!default {
    type plug
    slave.pcm "softvol"
}
```

Reboot after making these changes.

---

## Step 4 — Test audio output

After rebooting, verify the amplifier is working:

```bash
# Check that the sound card is detected
aplay -l

# Play a test tone (Ctrl+C to stop)
speaker-test -c2 --test=wav -w /usr/share/sounds/alsa/Front_Center.wav
```

Adjust volume with `alsamixer` — set the PCM level to around **50%** as a starting point to avoid distortion.

---

## Gain adjustment (optional)

The default gain is **9dB** (GAIN pin unconnected). To change it, wire the GAIN pin as follows:

| GAIN pin connection | Gain |
|---|---|
| 100kΩ resistor to GND | 15dB |
| Direct to GND | 12dB |
| Unconnected (default) | 9dB |
| Direct to Vin | 6dB |
| 100kΩ resistor to Vin | 3dB |

Power-cycle the board after changing the gain wiring.

---

## SD pin GPIO control (startup transient elimination)

<<<<<<< Updated upstream
<<<<<<< Updated upstream
The breakout board's SD pin has a 1MΩ pull-up to Vin, which selects **stereo average** output `(L+R)/2` by default — appropriate for mono use with a stereo audio source.
=======
The MAX98357A's SD pin controls both the amp's enabled/shutdown state and its channel selection. When SD is driven LOW (< 0.16 V) the amp is in shutdown; when HIGH (> 1.4 V, e.g. 3.3 V from a Pi GPIO) the amp is active on the left channel — which is what aplay sends for mono output.
>>>>>>> Stashed changes
=======
The MAX98357A's SD pin controls both the amp's enabled/shutdown state and its channel selection. When SD is driven LOW (< 0.16 V) the amp is in shutdown; when HIGH (> 1.4 V, e.g. 3.3 V from a Pi GPIO) the amp is active on the left channel — which is what aplay sends for mono output.
>>>>>>> Stashed changes

### Why there is a startup transient

When aplay launches, the I2S clock starts and the amp's internal charge pump powers up. This power-up sequence produces a brief audible pop regardless of the PCM data being fed in — it is a hardware event, not a software one.

### Eliminating it with GPIO control

hello-operator can sequence the startup to prevent the transient:

1. **SD LOW** — amp held in shutdown before aplay starts.
2. **aplay starts** — I2S clock begins; silence flows through the pipe.
3. **Settle delay (100 ms)** — silence reaches the I2S hardware.
4. **SD HIGH** — amp powers up into a stable, silent I2S stream → no transient.

To enable this:

1. Wire MAX98357A **SD** to **GPIO 22** (physical pin 15) instead of Vin.
2. Set `AMP_SD_PIN=22` in `/etc/hello-operator/config.env`.

hello-operator handles the rest automatically at startup.

### SD pin voltage reference

| SD pin voltage | State |
|---|---|
| < 0.16 V | Shutdown |
| 0.16 V – 0.77 V | Stereo average (L+R)/2 |
| 0.77 V – 1.4 V | Right channel only |
| > 1.4 V | Left channel only (3.3 V Pi GPIO output) |

hello-operator uses mono output (`aplay -c 1`), so left-channel-only mode is correct.
<<<<<<< Updated upstream

The SD pin is also used for instant audio cutoff — see Step 5 below.

---

## Step 5 — Wire instant audio cutoff via hook switch (recommended)

Without this step, audio may continue briefly after the handset is replaced during live TTS synthesis (artist names, browse lists, connecting announcements). The hardware fix cuts the amplifier at the analog level — instantly and unconditionally — regardless of software state.

**How it works:** Pulling the SD pin below 0.16V shuts the amplifier down immediately. hello-operator drives a GPIO pin LOW when the handset is on the cradle and releases it to high impedance when the handset is lifted. The existing 1MΩ pull-up on the breakout board maintains stereo average mode during normal operation.

### Additional parts needed

- One 100Ω resistor (current-limiting protection for the GPIO pin)
- One additional jumper wire

### Wiring

| MAX98357 pin | Connection |
|---|---|
| SD | GPIO 22 (BCM) via 100Ω series resistor — Physical pin 15 |

Connect the 100Ω resistor in series between physical pin 15 on the Pi's GPIO header and the SD pin on the MAX98357 breakout board.

> **Do not drive GPIO 22 HIGH.** Driving 3.3V onto the SD pin would override the 1MΩ pull-up and force left-channel-only output. The pin is toggled between `OUTPUT LOW` (amp off) and high impedance / `INPUT` (amp on, pull-up controls mode). hello-operator handles this automatically.

### Behaviour without this step

For pre-rendered TTS (most menu prompts) the difference is negligible — one polling cycle (~5 ms). For live synthesis the gap can be up to ~1–2 seconds depending on how long piper takes to finish.
=======
>>>>>>> Stashed changes

---

## Troubleshooting

**No sound after reboot**
Run `aplay -l` and confirm a sound card appears. If not, check that `dtoverlay=max98357a` is in `config.txt` and that `dtparam=audio=on` is absent or commented out.

**Distorted or clipping audio**
Lower the PCM level in `alsamixer`. At 5V the amp delivers up to 3.2W into 4Ω — more than enough to clip a small speaker.

**`aplay -l` shows no cards**
The I2S overlay did not load. Double-check `config.txt`, then run `dmesg | grep -i max98357` to see if the driver reported an error.

**hello-operator produces no audio**
Confirm `ALSA_DEVICE=plughw:MAX98357A` is set in `/etc/hello-operator/config.env`. If `AMP_SD_PIN` is set, verify the SD wire is connected to the correct GPIO pin and that the pin number in config.env matches.

**Startup transient (pop when hello-operator starts)**
Wire SD to a GPIO pin and set `AMP_SD_PIN` in config.env — see [SD pin GPIO control](#sd-pin-gpio-control-startup-transient-elimination) above.
