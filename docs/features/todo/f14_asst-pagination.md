### F-14 · Assistant pagination says "next" after the first page

**Background**
`_read_assistant_page()` always says *"I'll read you the first X"* regardless of which page is being read. On pages 2 and beyond this is incorrect.

**Changes required**

Track whether this is the first read of the current message list. One approach: check `self._assistant_page_offset == 0` before the read to determine which word to use.

```python
ordinal = "first" if self._assistant_page_offset == 0 else "next"
self._tts.speak_and_play(
    f"All right, here we go. I have {total} message{'s' if total != 1 else ''} for you. "
    f"I'll read you the {ordinal} {min(page_size, len(page))}."
)
```

**Acceptance criteria**
- First page of messages: announcement says "first X".
- Second and subsequent pages: announcement says "next X".

**Testable outcome**
- Input: set up 6 error messages (2 pages of 3); enter reading mode; read page 1; then dial `1` to continue.
- Expected: first `speak_and_play` call contains "first 3"; second contains "next 3".