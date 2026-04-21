import threading
import time
import logging

from src.session import Session
from gpiozero import Button
from src.audio import SounddeviceAudio
from src.tts import PiperTTS
from src.menu import Menu

log = logging.getLogger(__name__)

class Phone:
    
    def __init__(
        self,
        hook: Button,
        pulse: Button,
        tts: PiperTTS,
        audio: SounddeviceAudio,
        menu: Menu
    ) -> None:
        self._handset_lifted = False
        self._session = None
        self._hook = hook
        self._pulse = pulse
        self._stop_event = threading.Event()
        self._audio = audio
        self._menu = menu

        
    def start(self) -> None:
        t = threading.Thread(target=self._start_hook_watcher, daemon=True, name="hook-watcher")
        t.start()
        
    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_hook_watcher(self) -> None:
        """Spin a daemon thread that listens to the hook pin at ~1 ms intervals.
        Drives the amp and creates/closes Session the instant the pin changes
        state, bypassing the polling loop's debounce delay.
        """
        log.info("hook-watcher: thread starting")
        while not self._stop_event.is_set():
            try:
                self._hook.when_pressed = self._on_handset_lifted              
                self._hook.when_released = self._on_handset_replaced
            except Exception:
                log.exception("hook-watcher: error")
            time.sleep(0.001)
        log.info("hook-watcher: thread exiting")
    
    def _on_handset_lifted(self) -> None:
        if not handset_lifted:
            self._handset_lifted = True
            log.info("hook: handset lifted - starting session")
            self._audio.amp_on()
            self._session = Session(menu=self._menu, pulse=self._pulse)
            self._session.start()

    def _on_handset_replaced(self) -> None:
        if self._handset_lifted:
            log.info("hook: handset on cradle - ending session")
            self._audio.amp_off()
            self._tts.abort()
            if self._session is not None:
                self._session.close()
                self._session = None  
