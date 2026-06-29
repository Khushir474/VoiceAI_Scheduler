# DailyOps AI – Messaging Setup Guide

This guide walks through setting up messaging with **iMessage Bridge (primary) + Twilio (fallback)**.

## Quick Start

```bash
# 1. Install dependencies
pip install requests python-dotenv

# 2. Run the automated setup
python setup_messaging.py

# 3. Follow the prompts to configure iMessage and/or Twilio
```

The script will:
- ✅ Clone and install iMessage bridge (macOS only)
- ✅ Start the bridge on port 8001
- ✅ Test connectivity
- ✅ Prompt for Twilio credentials
- ✅ Update `.env` with working configuration
- ✅ Set up automatic fallback

---

## What the Script Does

### 1. iMessage Bridge (Primary - macOS only)

If running on macOS:
- Clones `imessage-rest` repository
- Installs Python dependencies
- Starts bridge on `http://localhost:8001`
- Tests that it's running
- Adds `IMESSAGE_BRIDGE_URL=http://localhost:8001` to `.env`

### 2. Twilio SMS (Fallback)

Prompts for credentials:
- `TWILIO_ACCOUNT_SID` – From https://www.twilio.com/
- `TWILIO_AUTH_TOKEN` – From https://www.twilio.com/
- `TWILIO_PHONE_NUMBER` – Purchased Twilio phone number
- `USER_PHONE_NUMBER` – Your phone number for receiving messages

Updates `.env`:
```bash
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
TWILIO_PHONE_NUMBER=+1234567890
USER_PHONE_NUMBER=+1234567890
```

---

## Messaging Flow

### When iMessage Bridge is Available

```
User sends message
    ↓
Try iMessage bridge (http://localhost:8001)
    ↓
✅ Success → Send via iMessage
    ↓
✅ Message delivered
```

### When iMessage Bridge Fails or Unavailable

```
User sends message
    ↓
Try iMessage bridge
    ↓
❌ Bridge down/error
    ↓
Log: "iMessage unavailable, falling back to Twilio"
    ↓
Send via Twilio SMS
    ↓
✅ Message delivered
```

### When Both Are Unavailable

```
User sends message
    ↓
Try iMessage bridge
    ↓
❌ Bridge down
    ↓
Try Twilio SMS
    ↓
❌ Twilio not configured
    ↓
❌ Send failed (logged to debug_logs)
```

---

## Running the Setup

### Step 1: Run the Setup Script

```bash
python setup_messaging.py
```

### Step 2: iMessage Bridge Setup (if on macOS)

The script will:
1. Clone `imessage-rest` to `imessage_bridge/` directory
2. Install Python dependencies
3. Start the bridge in the background
4. Test connectivity on `http://localhost:8001`

**Keep the Bridge Running:**

The bridge runs in the background, but to keep it persistent:

```bash
# Terminal 1: Start the bridge
cd imessage_bridge
python server.py

# Terminal 2: Run your backend
python -m app.main
```

Or use a process manager like `supervisor` or `systemd` for production.

### Step 3: Twilio Setup (Recommended)

The script will prompt you for Twilio credentials:

1. **Create Twilio Account:**
   - Go to https://www.twilio.com/
   - Sign up (free trial with $15 credit)
   - Verify your phone number

2. **Get Credentials:**
   - Account SID: From dashboard → Account → Settings
   - Auth Token: From dashboard → Account → Settings
   - Buy a phone number: From Twilio → Phone Numbers

3. **Enter Credentials:**
   ```
   Enter TWILIO_ACCOUNT_SID: ACxxxxx
   Enter TWILIO_AUTH_TOKEN: xxxxx
   Enter TWILIO_PHONE_NUMBER: +1234567890
   Enter USER_PHONE_NUMBER: +1234567890
   ```

---

## Verification

### Test iMessage Bridge

```bash
curl -X GET http://localhost:8001/
```

Should return a response (200 or 404 is fine).

### Test Message Sending

Once DailyOps is running:

```bash
curl -X POST http://localhost:8000/api/messages/send \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "test-run-123",
    "user_id": "user-123",
    "content": "Hello from DailyOps!"
  }'
```

The API will:
1. Try iMessage first
2. Fall back to Twilio if iMessage fails
3. Return status and which channel was used

---

## Troubleshooting

### "Address already in use" on port 8001

The bridge port is occupied. Kill the process:

```bash
lsof -ti:8001 | xargs kill -9
```

Then restart: `python imessage_bridge/server.py`

### "Cannot connect to iMessage bridge"

- Check if `python imessage_bridge/server.py` is running
- Check logs: `cat imessage_bridge.log`
- Ensure port 8001 is accessible

### "Twilio credentials invalid"

- Verify credentials at https://www.twilio.com/
- Check `.env` for typos
- Ensure account has credit (not on free trial without verification)

### Messages not being received

1. **Check debug logs:**
   ```sql
   SELECT * FROM debug_logs 
   WHERE event_type IN ('send_success', 'send_failed', 'imessage_failed')
   ORDER BY created_at DESC
   LIMIT 10;
   ```

2. **Verify phone numbers:**
   - `USER_PHONE_NUMBER` must be in E.164 format: `+1234567890`

3. **Test with curl:**
   ```bash
   # Test Twilio directly
   curl -X POST https://api.twilio.com/2010-04-01/Accounts/YOUR_SID/Messages.json \
     -u "YOUR_SID:YOUR_TOKEN" \
     -d "Body=Hello&From=+1234567890&To=+1234567890"
   ```

---

## Production Deployment

### Backend (Railway)

1. Set environment variables in Railway dashboard:
   - `IMESSAGE_BRIDGE_URL` (optional if using Twilio only)
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_PHONE_NUMBER`
   - `USER_PHONE_NUMBER`

2. If using iMessage bridge:
   - Run bridge on a separate Mac server
   - Set `IMESSAGE_BRIDGE_URL` to that server's URL

### Frontend (Vercel)

No changes needed. Frontend sends messages via backend API.

---

## Code Reference

### Message API Endpoint

```python
# POST /api/messages/send
{
  "run_id": "abc-123",
  "user_id": "user-456",
  "content": "Your daily summary..."
}

# Response
{
  "status": "sent",
  "channel": "imessage",  # or "twilio" or "none"
  "message_id": "msg-789"
}
```

### Automatic Fallback Flow

See `backend/app/api/messages.py`:
- `send_with_fallback()` – Orchestrates iMessage → Twilio
- Logs both attempts to `debug_logs` table
- Returns which channel was used

### Debug Logging

All messaging attempts are logged with:
- `agent_name`: "MessageRouter"
- `event_type`: "send_success", "send_failed", "imessage_failed", etc.
- `input_payload`: recipient, content length
- `output_payload`: status, message_id, channel used
- `error`: error message if failed

---

## Next Steps

1. Run the setup script: `python setup_messaging.py`
2. Keep iMessage bridge running (if using): `python imessage_bridge/server.py`
3. Start the backend: `python -m app.main`
4. Test sending a message via the API
5. Check `debug_logs` table for details

Happy messaging! 📱
