# DOPS-12: Vapi call delivery through iPhone sleep/DND modes

6 AM call may be blocked by iPhone Sleep Focus or DND. Configure Vapi call with max priority settings. Implement retry with backoff if call fails. Send SMS fallback after N failed attempts. Add call priority config and retry count to settings. Touches: adapters/voice/vapi.py, conversation_agent.py. Acceptance: Calls configured with highest urgency; retry logic implemented; SMS fallback triggered after failures; delivery status logged.
