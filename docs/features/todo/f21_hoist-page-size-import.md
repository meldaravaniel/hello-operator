### F-21 · Hoist `ASSISTANT_MESSAGE_PAGE_SIZE` to module-level import

**Background**
`ASSISTANT_MESSAGE_PAGE_SIZE` is imported inside two methods in `src/menu.py` rather than at module scope:

```python
# menu.py line 924
def _read_assistant_page(self, now: float) -> None:
    from src.constants import ASSISTANT_MESSAGE_PAGE_SIZE  # ← inside method

# menu.py line 952
def _assistant_continue_or_navigate(self, digit: int, now: float) -> None:
    from src.constants import ASSISTANT_MESSAGE_PAGE_SIZE  # ← inside method
```

All other constants in `menu.py` are imported at module scope (lines 31–41). This inconsistency suggests the import was forgotten when the assistant pagination feature was added.

**Changes required**

Add `ASSISTANT_MESSAGE_PAGE_SIZE` to the existing `from src.constants import (...)` block at the top of `menu.py`, and remove the two local imports inside `_read_assistant_page` and `_assistant_continue_or_navigate`.

No behaviour changes.

**Acceptance criteria**
- `ASSISTANT_MESSAGE_PAGE_SIZE` appears in the module-level import block in `menu.py`.
- Neither method contains a local `from src.constants import` statement.
- All existing tests pass.
