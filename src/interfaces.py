"""All ABCs, data types, and named tuples for hello-operator."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class MediaItem:
    media_key: str
    name: str
    media_type: str  # "playlist" | "artist" | "album" | "genre" | "radio"


@dataclass
class RadioStation:
    name: str            # Human-readable station name (e.g. "KEXP")
    frequency_hz: float  # Carrier frequency in Hz (e.g. 90_300_000.0)
    phone_number: str    # Pre-configured 7-digit direct-dial number


@dataclass
class PlaybackState:
    item: Optional[MediaItem]  # None if nothing is playing
    is_paused: bool  # True if playback is paused; always False when item is None


@dataclass
class ErrorEntry:
    source: str
    severity: str  # "warning" | "error"
    message: str
    count: int
    last_happened: str  # ISO8601 timestamp


class AudioInterface(ABC):
    """Abstracts all sound output."""

    @abstractmethod
    def play_tone(self, frequencies: list, duration_ms: int) -> None:
        """Generate and play a sine wave mix."""

    @abstractmethod
    def play_file(self, path: str) -> None:
        """Play a pre-rendered audio file."""

    @abstractmethod
    def play_dtmf(self, digit: int) -> None:
        """Play the standard DTMF tone for a digit (0–9)."""

    @abstractmethod
    def play_off_hook_tone(self) -> None:
        """Play off-hook warning tone continuously until stop()."""

    @abstractmethod
    def stop(self) -> None:
        """Stop any current playback immediately."""

    @abstractmethod
    def is_playing(self) -> bool:
        """True if audio is currently playing."""


class TTSInterface(ABC):
    """Abstracts text-to-speech."""

    @abstractmethod
    def speak(self, text: str) -> str:
        """Synthesize text; return path to audio file."""

    @abstractmethod
    def speak_and_play(self, text: str) -> None:
        """Synthesize and play immediately."""

    @abstractmethod
    def speak_digits(self, digits: str) -> None:
        """Speak each character as an individual digit word."""

    @abstractmethod
    def prerender(self, prompts: dict) -> None:
        """Pre-synthesize fixed strings to cached audio files."""


class MediaClientInterface(ABC):
    """Abstracts all media player API calls (Plex, MPD, etc.)."""

    @abstractmethod
    def get_playlists(self) -> list:
        """Return all playlists as MediaItem list."""

    @abstractmethod
    def get_artists(self) -> list:
        """Return all artists."""

    @abstractmethod
    def get_genres(self) -> list:
        """Return all genres."""

    @abstractmethod
    def get_albums_for_artist(self, artist_media_key: str) -> list:
        """Return albums for a given artist."""

    @abstractmethod
    def play(self, media_key: str) -> None:
        """Start playback of a media item."""

    @abstractmethod
    def shuffle_all(self) -> None:
        """Shuffle and play the entire library."""

    @abstractmethod
    def pause(self) -> None:
        """Pause current playback."""

    @abstractmethod
    def unpause(self) -> None:
        """Resume paused playback."""

    @abstractmethod
    def skip(self) -> None:
        """Skip to next track."""

    @abstractmethod
    def stop(self) -> None:
        """Stop playback entirely."""

    @abstractmethod
    def now_playing(self) -> PlaybackState:
        """Return current playback state."""

    @abstractmethod
    def get_queue_position(self) -> tuple:
        """Return (current_track, total_tracks)."""

    @abstractmethod
    def get_tracks_for_genre(self, genre_media_key: str) -> list:
        """Return list of track keys for a genre, given the genre's media_key."""

    @abstractmethod
    def play_tracks(self, track_keys: list, shuffle: bool = True) -> None:
        """Create a play queue from track keys and start playback."""


# Backward-compat alias — use MediaClientInterface in new code
PlexClientInterface = MediaClientInterface


class ErrorQueueInterface(ABC):
    """Abstracts the persistent error log."""

    @abstractmethod
    def log(self, source: str, severity: str, message: str) -> None:
        """Add or update an entry; deduplicated by (source, message)."""

    @abstractmethod
    def get_all(self) -> list:
        """Return all entries, newest first."""

    @abstractmethod
    def get_by_severity(self, severity: str) -> list:
        """Return entries filtered by 'warning' or 'error'."""


class RadioInterface(ABC):
    """Abstracts FM radio playback via RTL-SDR dongle."""

    @abstractmethod
    def play(self, frequency_hz: float) -> None:
        """Tune to the given frequency and begin streaming audio."""

    @abstractmethod
    def stop(self) -> None:
        """Stop radio playback."""

    @abstractmethod
    def is_playing(self) -> bool:
        """True if radio is currently streaming."""
