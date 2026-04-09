### F-18 · GPIO cleanup on exit

**Background**
`build_gpio_handler()` calls `GPIO.setmode()` and `GPIO.setup()` but the `finally` block in `run()` never calls `GPIO.cleanup()`. This leaves pull-up resistors active and triggers `RuntimeWarning: No channels have been set up yet` on the next startup.

**Changes required**

Add `GPIO.cleanup()` to the `finally` block in `run()`, after `audio.stop()`. Guard it so it only runs if the GPIO module was successfully imported (i.e., if `build_gpio_handler()` did not raise).

**Acceptance criteria**
- Clean shutdown (`KeyboardInterrupt`) calls `GPIO.cleanup()`.
- Subsequent startup does not emit GPIO RuntimeWarnings.