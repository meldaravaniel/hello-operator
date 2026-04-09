# Piper TTS Setup

[Piper](https://github.com/rhasspy/piper) is a fast, local neural text-to-speech engine. hello-operator uses it to synthesise all voice prompts.

---

## What you need

- The `piper` binary for your platform
- A voice model (`.onnx` file + its `.onnx.json` config sidecar)
- A writable TTS cache directory

The default paths expected by `src/constants.py` are:

| Item | Default path |
|---|---|
| Binary | `/usr/local/bin/piper` |
| Model | `/usr/local/share/piper/en_US-lessac-medium.onnx` |
| Cache dir | `/var/cache/hello-operator/tts` |

If you install to different locations, update the corresponding constants in `src/constants.py`.

---

## Step 1 — Download the Piper binary

Go to the [Piper releases page](https://github.com/rhasspy/piper/releases) and download the archive for your platform:

| Platform | Filename |
|---|---|
| Linux x86-64 (dev machine) | `piper_linux_x86_64.tar.gz` |
| Linux ARM64 (Raspberry Pi 4) | `piper_linux_aarch64.tar.gz` |
| macOS Apple Silicon | `piper_macos_aarch64.tar.gz` |
| macOS Intel | `piper_macos_x86_64.tar.gz` |

Extract and install the binary:

```bash
# Example for Linux x86-64 — adjust filename for your platform
tar -xzf piper_linux_x86_64.tar.gz
sudo cp piper/piper /usr/local/bin/piper
sudo chmod +x /usr/local/bin/piper
```

The archive also contains shared libraries. If the binary fails to run because of missing `.so` files, copy the entire `piper/` folder somewhere permanent and symlink the binary:

```bash
sudo cp -r piper/ /usr/local/lib/piper/
sudo ln -s /usr/local/lib/piper/piper /usr/local/bin/piper
```

Verify the installation:

```bash
piper --version
```

---

## Step 2 — Download the voice model

hello-operator uses `en_US-lessac-medium` by default. You need **two files** — the model and its config sidecar — and they must be in the same directory.

Create the model directory:

```bash
sudo mkdir -p /usr/local/share/piper
```

Download both files from the [Piper voices repository on Hugging Face](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium):

```bash
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
sudo curl -L "$BASE/en_US-lessac-medium.onnx"      -o /usr/local/share/piper/en_US-lessac-medium.onnx
sudo curl -L "$BASE/en_US-lessac-medium.onnx.json" -o /usr/local/share/piper/en_US-lessac-medium.onnx.json
```

> **Other voices:** Browse the [full voice list](https://huggingface.co/rhasspy/piper-voices/tree/main) to pick a different voice. Update `PIPER_MODEL` in `src/constants.py` to point to the new `.onnx` file — the `.json` sidecar must be in the same directory.

---

## Step 3 — Create the TTS cache directory

hello-operator pre-renders all fixed voice prompts at startup and caches them here. The process must be able to write to this directory.

```bash
sudo mkdir -p /var/cache/hello-operator/tts
sudo chown $USER /var/cache/hello-operator/tts
```

---

## Step 4 — Smoke test

Verify the full pipeline works before running hello-operator:

```bash
echo "Hello, operator." | piper \
  --model /usr/local/share/piper/en_US-lessac-medium.onnx \
  --output_file /tmp/test.wav \
  && aplay /tmp/test.wav
```

You should hear "Hello, operator." spoken aloud. On macOS, replace `aplay` with `afplay`.

If `aplay` is not installed on Linux:

```bash
sudo apt install alsa-utils
```

---

## Troubleshooting

**`piper: command not found`**
The binary is not on your `PATH`. Confirm it is at `/usr/local/bin/piper` or update `PIPER_BINARY` in `src/constants.py` to the full path.

**`error: failed to load model`**
Piper cannot find the `.onnx.json` sidecar. Confirm both the `.onnx` and `.onnx.json` files are in the same directory.

**`Segmentation fault` or missing shared libraries on Linux**
Copy the full extracted `piper/` directory (which includes bundled `.so` files) to a permanent location and symlink the binary — see the note in Step 1.

**No audio from `aplay`**
Check your system audio device:
```bash
aplay -l          # list available devices
aplay -D hw:0,0 /tmp/test.wav   # try a specific device
```

**Output file is empty or not a valid WAV**
hello-operator always uses `--output_file`, never `--output-raw`. If you are testing manually, make sure you include `--output_file <path>` and do not redirect stdout.
