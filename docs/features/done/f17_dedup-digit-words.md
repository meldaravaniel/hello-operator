### F-17 · Deduplicate `_DIGIT_WORDS`

**Background**
An identical `_DIGIT_WORDS = {'0': 'zero', '1': 'one', ...}` dict is defined in both `src/tts.py` and `src/menu.py`. If the mapping ever changes, both must be updated in sync.

**Changes required**

Move `_DIGIT_WORDS` to `src/constants.py` (public name: `DIGIT_WORDS`) and import it in both `tts.py` and `menu.py`. No behaviour changes.

**Acceptance criteria**
- `_DIGIT_WORDS` / `DIGIT_WORDS` appears in exactly one source file.
- All tests that exercise digit-word output continue to pass.