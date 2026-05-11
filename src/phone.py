import threading
import time
import logging

from gpiozero import Button, DigitalInputDevice
from src.audio import SounddeviceAudio
from src.tts import PiperTTS
from src.menu import Menu
from src.dialer import Dialer

log = logging.getLogger(__name__)

class Phone:
    
    def __init__(
        self,
        hook: DigitalInputDevice,
        pulse: Button,
        rotary: DigitalInputDevice,
        tts: PiperTTS,
        audio: SounddeviceAudio,
        menu: Menu
    ) -> None:
        self._handset_lifted = False
        self._hook = hook
        self._stop_event = threading.Event()
        self._audio = audio
        self._menu = menu
        self._dialer = Dialer(self._menu.on_digit, pulse, rotary)

        
    def start(self) -> None:
        t = threading.Thread(target=self._start_hook_watcher, daemon=True, name="hook-watcher")
        t.start()

    def stop(self) -> None:
        self._on_handset_replaced()
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_hook_watcher(self) -> None:
        """Spin a daemon thread that listens to the hook pin at ~1 ms intervals.
        Drives the amp and creates/closes Session the instant the pin changes
        state, bypassing the polling loop's debounce delay.
        """
        log.info("hook-watcher thread starting")
        self._hook.when_activated = self._on_handset_lifted
        self._hook.when_deactivated = self._on_handset_replaced
        while not self._stop_event.is_set():
            try:
                log.info("hook-watcher waiting for hook lift")
                self._hook.wait_for_active()
                log.info("hook-watcher waiting for hook replace")
                self._hook.wait_for_inactive()
            except Exception:
                log.exception("hook-watcher error")
        log.info("hook-watcher thread exiting")

    def _start_phone_session(self) -> None:
        log.info("phone session starting")
        while self._handset_lifted:
            try:
                now = time.monotonic()
                self._menu.tick(now=now)
            except Exception:
                log.exception("phone session error")
            time.sleep(0.005)
        log.info("phone session stopped")
    
    def _on_handset_lifted(self) -> None:
        if not self._handset_lifted:
            self._handset_lifted = True
            log.info("handset lifted - starting session")
            self._audio.amp_on()
            self._dialer.start()
            self._menu.on_handset_lifted()
            threading.Thread(
                target=self._start_phone_session, daemon=True, name="phone-session"
            ).start()
                
    def _on_handset_replaced(self) -> None:
        if self._handset_lifted:
            self._handset_lifted = False
            log.info("handset on cradle - ending session")
            self._audio.amp_off()
            self._dialer.stop()
            self._menu.on_handset_on_cradle()
