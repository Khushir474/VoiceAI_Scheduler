"""Voice adapters."""

from app.adapters.voice.base import VoiceAdapter
from app.adapters.voice.vapi import VapiAdapter

__all__ = ["VoiceAdapter", "VapiAdapter"]
