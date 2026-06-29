"""Messaging router: selects the active adapter based on preferred_messaging_channel."""

from app.adapters.messaging.base import MessageAdapter
from app.adapters.messaging.imessage_bridge import IMessageBridgeAdapter
from app.adapters.messaging.twilio_sms import TwilioSMSAdapter
from app.services.logger import DebugLogger
from app.config import Settings


def build_messaging_adapter(settings: Settings, debug_logger: DebugLogger) -> MessageAdapter:
    """Return the appropriate MessageAdapter based on settings.preferred_messaging_channel.

    Falls back to Twilio if the channel is 'twilio' or any unrecognised value.
    """
    channel = (settings.preferred_messaging_channel or "imessage").lower().strip()

    if channel == "imessage":
        return IMessageBridgeAdapter(
            debug_logger=debug_logger,
            bridge_url=settings.imessage_bridge_url,
        )

    return TwilioSMSAdapter(
        debug_logger=debug_logger,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_phone_number,
    )
