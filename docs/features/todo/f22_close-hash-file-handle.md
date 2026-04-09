### F-22 · Close TTS cache hash file with a context manager

**Background**
`PiperTTS.prerender()` in `src/tts.py` reads a cached hash file without a context manager:

```python
# tts.py line 125
stored_hash = open(hash_path).read().strip()
```

The file handle is left open until the garbage collector runs. All other file I/O in the project uses `with` blocks. On a long-running process (or a system with a low file descriptor limit, such as the Raspberry Pi target) this can silently exhaust file descriptors if `prerender()` is called with many scripts.

**Changes required**

Replace the bare `open()` call with a `with` block:

```python
with open(hash_path, 'r') as f:
    stored_hash = f.read().strip()
```

No behaviour changes.

**Acceptance criteria**
- The hash file is read inside a `with` block.
- All existing TTS tests pass.
