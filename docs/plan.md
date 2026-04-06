# hello-operator Implementation Plan

## Implementation Workflow

Work strictly in module order. Each module is fully testable with mocks before
the next begins — never skip ahead. Use one Claude Code session per module
(except `menu`, which warrants splitting by subsection).

### Session Development Process

**Test-first within every session:**
1. Write all tests for the module from TEST_SPEC.md
2. Run them — confirm they all fail
3. Implement until all tests pass
4. Check for anything the spec implies but the tests don't cover

---

## CLAUDE.md Additions (do these before starting implementation)

Add the following to CLAUDE.md before the first coding session:

```markdown
## Commands

# Run all unit tests
python -m pytest

# Run a single test
python -m pytest tests/test_menu.py::test_idle_menu_announces_options

# Run integration tests (requires live Plex server)
python -m pytest -m integration

# Run all tests except integration
python -m pytest -m "not integration"

# Run the application
python main.py

## Project Structure

src/
  interfaces.py       # All ABCs, MediaItem, PlaybackState, ErrorEntry
  error_queue.py      # SqliteErrorQueue
  phone_book.py       # PhoneBook
  gpio_handler.py     # GPIOHandler
  audio.py            # SounddeviceAudio
  tts.py              # PiperTTS
  plex_client.py      # PlexClient
  plex_store.py       # PlexStore
  menu.py             # Menu state machine
  session.py          # Session lifecycle
  constants.py        # All configuration constants
  main.py             # Wires everything together

tests/
  conftest.py         # Shared pytest fixtures (all mocks)
  test_error_queue.py
  test_phone_book.py
  test_gpio_handler.py
  test_audio.py
  test_tts.py
  test_plex_client.py
  test_plex_store.py
  test_menu.py
  test_session.py

## Conventions

- All constants live in constants.py; no magic numbers elsewhere
- All TBD constants are defined with a placeholder value and a TODO comment
- Mocks are defined in tests/conftest.py as pytest fixtures
- Integration tests are marked with @pytest.mark.integration
```

---

## Task List

---

### Session 1: Interfaces + Data Types
**Start prompt:**
> "We're starting implementation of the hello-operator project. Please read
> DESIGN.md, IMPL.md, and CLAUDE.md to understand the architecture. Your task
> for this session is to create `src/interfaces.py` and `src/constants.py`.
> `interfaces.py` should contain all four ABCs (AudioInterface, TTSInterface,
> PlexClientInterface, ErrorQueueInterface) and the three data types (MediaItem,
> PlaybackState, ErrorEntry). `constants.py` should contain all constants from
> the Configuration Constants table in DESIGN.md, with TBD values set to
> reasonable placeholder values and a TODO comment. No logic — just definitions."

**Done when:** File structure is in place, all ABCs importable, no test failures.

**End note:** Commit. Confirm the file structure matches the layout in CLAUDE.md.

---

### Session 2: `error_queue`
**Start prompt:**
> "We're implementing `error_queue` for the hello-operator project. Please read
> DESIGN.md § ErrorQueueInterface, TEST_SPEC.md § 5, and IMPL.md § Database
> Schemas (error_queue schema). Write all tests in `tests/test_error_queue.py`
> first, then implement `src/error_queue.py` (SqliteErrorQueue + MockErrorQueue)
> until all tests pass."

**Done when:** All tests in TEST_SPEC.md § 5 pass.

---

### Session 3: `phone_book`
**Start prompt:**
> "We're implementing `phone_book` for the hello-operator project. Please read
> DESIGN.md § phone_book, TEST_SPEC.md § 4, and IMPL.md § Database Schemas
> (phone_book schema). Write all tests in `tests/test_phone_book.py` first, then
> implement `src/phone_book.py` until all tests pass."

**Done when:** All tests in TEST_SPEC.md § 4 pass.

---

### Session 4: `gpio_handler`
**Start prompt:**
> "We're implementing `gpio_handler` for the hello-operator project. Please read
> DESIGN.md § gpio_handler and TEST_SPEC.md § 1. The GPIO pin reader must be
> abstracted so tests can inject a mock — there should be no real RPi.GPIO
> dependency in unit tests. Write all tests in `tests/test_gpio_handler.py`
> first, then implement `src/gpio_handler.py` until all tests pass."

**Done when:** All tests in TEST_SPEC.md § 1 pass.

---

### Session 5: `audio`
**Start prompt:**
> "We're implementing `audio` for the hello-operator project. Please read
> DESIGN.md § AudioInterface and § audio, TEST_SPEC.md § 2, and IMPL.md §
> Audio Implementation. Write all tests in `tests/test_audio.py` first (using
> a mock sounddevice backend so no audio hardware is needed), then implement
> `src/audio.py` (SounddeviceAudio + MockAudio) until all tests pass."

**Done when:** All tests in TEST_SPEC.md § 2 pass.

---

### Session 6: `tts`
**Start prompt:**
> "We're implementing `tts` for the hello-operator project. Please read
> DESIGN.md § TTSInterface and § tts, TEST_SPEC.md § 3, and IMPL.md § TTS
> Implementation. Write all tests in `tests/test_tts.py` first (Piper binary
> should be mockable so tests don't require it installed), then implement
> `src/tts.py` (PiperTTS + MockTTS) until all tests pass. Pay particular
> attention to the persistent cache + hash-based change detection behaviour."

**Done when:** All tests in TEST_SPEC.md § 3 pass.

---

### Session 7: `plex_client`
**Start prompt:**
> "We're implementing `plex_client` for the hello-operator project. Please read
> DESIGN.md § PlexClientInterface and § plex_client, TEST_SPEC.md § 8, and
> IMPL.md § Plex Client Implementation. Write all tests in
> `tests/test_plex_client.py` first — unit tests use MockPlexClient, integration
> tests (marked @pytest.mark.integration, skipped by default) hit a live server.
> Implement `src/plex_client.py` (PlexClient + MockPlexClient) until all unit
> tests pass."

**Done when:** All unit tests in TEST_SPEC.md § 8 pass. Integration tests
written but skipped.

---

### Session 8: `plex_store`
**Start prompt:**
> "We're implementing `plex_store` for the hello-operator project. Please read
> DESIGN.md § plex_store, TEST_SPEC.md § 7, and IMPL.md § Database Schemas
> (plex_cache schema). Write all tests in `tests/test_plex_store.py` first using
> MockPlexClient, then implement `src/plex_store.py` until all tests pass."

**Done when:** All tests in TEST_SPEC.md § 7 pass.

---

### Session 9a: `menu` — Core states + reserved digits
**Start prompt:**
> "We're starting implementation of the `menu` state machine for hello-operator.
> This will take multiple sessions. Please read DESIGN.md § menu, the full UX
> flow section, and TEST_SPEC.md § 9. This session covers: the state enum,
> reserved digits + disambiguation (§ 9.1), idle state top-level menu (§ 9.2),
> and playing state top-level menu (§ 9.3). Write those tests first in
> `tests/test_menu.py`, then implement the relevant states in `src/menu.py`
> until they pass. Use MockAudio, MockTTS, MockPlexClient, MockPlexStore, and
> MockErrorQueue throughout."

**Done when:** TEST_SPEC.md § 9.1, 9.2, 9.3 tests pass.

---

### Session 9b: `menu` — T9 browsing + artist submenu
**Start prompt:**
> "Continuing `menu` implementation for hello-operator. Please read
> `src/menu.py` (existing code), DESIGN.md § menu + § Browsing + § Artist
> submenu, and TEST_SPEC.md § 9.4 and § 9.5. Add tests for T9 browsing and
> the artist submenu to `tests/test_menu.py`, then implement those states until
> all new tests pass without breaking existing ones."

**Done when:** TEST_SPEC.md § 9.4 and § 9.5 tests pass.

---

### Session 9c: `menu` — Direct dial + assistant + final selection
**Start prompt:**
> "Continuing `menu` implementation for hello-operator. Please read
> `src/menu.py` (existing code), DESIGN.md § Direct dial + § Diagnostic
> assistant + § Final selection, and TEST_SPEC.md § 9.6 and § 9.7. Add the
> remaining tests to `tests/test_menu.py` and implement those states until all
> tests pass."

**Done when:** All tests in TEST_SPEC.md § 9 pass.

---

### Session 10: `session`
**Start prompt:**
> "We're implementing `session` for the hello-operator project. Please read
> DESIGN.md § session, TEST_SPEC.md § 10, and the existing `src/menu.py` to
> understand what the session needs to drive. Write all tests in
> `tests/test_session.py` first, then implement `src/session.py` until all
> tests pass."

**Done when:** All tests in TEST_SPEC.md § 10 pass.

---

### Session 11: `main` + hardware smoke test
**Start prompt:**
> "We're implementing `main.py` for the hello-operator project. Please read
> DESIGN.md, IMPL.md § TTS Implementation (prerender call), and all existing
> `src/` files to understand what needs to be wired together. `main.py` should:
> instantiate all concrete implementations, call `tts.prerender()` with all
> pre-renderable scripts from SCRIPTS.md, wire everything into `session`, and
> start the event loop. No unit tests for main — this is validated by running
> on hardware."

**Done when:** `python main.py` runs on the Raspberry Pi without errors.
