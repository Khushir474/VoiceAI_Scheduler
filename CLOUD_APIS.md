# Cloud APIs – No Local Paths

DailyOps AI is **100% cloud-based**. No local file access, no AppleScript, no local paths.

## Architecture

Every integration uses cloud APIs:

### Calendar

**Google Calendar** → Google Calendar API
- Fetch events via REST API
- OAuth setup required

**Apple iCal** → CalDAV (cloud-based)
- Connect via iCloud CalDAV: `caldav.icloud.com`
- Or any CalDAV-compatible server (Nextcloud, OwnCloud, etc.)
- No local `/Library/Calendars` access

### Weather

**OpenWeather API** (cloud)
- REST API call: `https://api.openweathermap.org/data/2.5/weather`
- Latitude/longitude input
- Real-time weather data

### Commute

**Google Maps Distance Matrix API** (cloud)
- REST API call: `https://maps.googleapis.com/maps/api/distancematrix/json`
- Origin & destination addresses
- Returns duration, distance, traffic condition

### Messaging

**iMessage** → Twilio fallback (cloud)
- Primary: Local Mac bridge (HTTP to `localhost:8001`)
- Fallback: Twilio SMS API for reliability

**SMS** → Twilio API (cloud)
- REST API: `https://api.twilio.com`
- Reliable cloud alternative

### Voice

**Vapi** (cloud)
- REST API for outbound calls
- Webhooks for call state & transcript
- ElevenLabs voice provider

---

## Setup

### 1. Google Calendar API

```bash
# Create service account or OAuth2 credentials
# https://console.cloud.google.com/

GOOGLE_CALENDAR_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CALENDAR_CLIENT_SECRET=xxx
GOOGLE_CALENDAR_REFRESH_TOKEN=xxx  # After OAuth flow
```

### 2. Apple iCal (CalDAV)

**Option A: iCloud**
```bash
APPLE_ICAL_CALDAV_URL=https://caldav.icloud.com
APPLE_ICAL_USERNAME=your-apple-id@icloud.com
APPLE_ICAL_PASSWORD=xxxx-xxxx-xxxx-xxxx  # App-specific password
```

**To generate Apple app-specific password:**
1. Go to https://appleid.apple.com/account/manage
2. Sign in
3. Click "Security"
4. Scroll to "App-specific passwords"
5. Generate new password for "Calendar"

**Option B: Nextcloud**
```bash
APPLE_ICAL_CALDAV_URL=https://nextcloud.example.com
APPLE_ICAL_USERNAME=user@example.com
APPLE_ICAL_PASSWORD=password
```

### 3. OpenWeather API

```bash
# Sign up at https://openweathermap.org/api
WEATHER_API_KEY=xxx
WEATHER_PROVIDER=openweather
```

### 4. Google Maps API

```bash
# Enable Distance Matrix API in Google Cloud Console
# https://console.cloud.google.com/

GOOGLE_MAPS_API_KEY=xxx
```

### 5. Vapi (Voice)

```bash
# Sign up at https://vapi.ai/
VAPI_API_KEY=xxx
VAPI_ASSISTANT_ID=xxx
```

### 6. Twilio (SMS Fallback)

```bash
# Sign up at https://www.twilio.com/
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
TWILIO_PHONE_NUMBER=+1234567890
USER_PHONE_NUMBER=+1234567890
```

### 7. iMessage Bridge (Optional)

```bash
# Local HTTP bridge for iMessage (Mac-only)
IMESSAGE_BRIDGE_URL=http://localhost:8001

# If not available, falls back to Twilio SMS
```

---

## No Local Files Allowed

✅ Cloud APIs only:
- Google Calendar REST API
- CalDAV protocol (standard)
- OpenWeather REST API
- Google Maps REST API
- Vapi REST API
- Twilio REST API

❌ No local access:
- ~~AppleScript~~
- ~~local `/Library/Calendars` path~~
- ~~local file reading~~
- ~~subprocess calls~~

---

## Benefits

1. **Scalable**: Works on any cloud infrastructure (Railway, AWS, GCP, etc.)
2. **Secure**: No credentials stored locally, API keys in env only
3. **Portable**: Same code runs on macOS, Linux, Windows, Docker, serverless
4. **Testable**: Easy to mock cloud APIs in tests
5. **Observable**: All API calls logged to Supabase for debugging

---

## Adapter Implementations

### CalendarAdapter
- `GoogleCalendarAdapter` → REST API calls
- `AppleICalAdapter` → CalDAV protocol (RFC 4791)

### WeatherAdapter
- `WeatherAdapter.openweather()` → OpenWeather REST API

### MapsAdapter
- `MapsAdapter.google_maps()` → Google Maps Distance Matrix API

### VoiceAdapter
- `VapiAdapter` → Vapi REST API + webhooks

### MessageAdapter
- `IMessageBridgeAdapter` → Local HTTP bridge (fallback to Twilio)
- `TwilioSMSAdapter` → Twilio REST API

---

## Testing

All adapters are mock-friendly:

```python
# Mock weather adapter for tests
mock_weather = WeatherData(
    temperature_high=72,
    temperature_low=62,
    condition="sunny",
)

# No cloud calls, no credentials needed
assert mock_weather.condition == "sunny"
```

---

## Migration Path

If running locally (dev machine):
1. Set env vars for cloud APIs
2. Adapters automatically use cloud APIs
3. No code changes needed

If deploying to cloud (Railway, Vercel, AWS):
1. Set same env vars in platform dashboard
2. All cloud APIs work out-of-the-box
3. iMessage bridge → use Twilio fallback (SMS)

---

## Troubleshooting

**CalDAV not connecting?**
- Verify credentials at https://caldav.icloud.com/
- Check app-specific password is generated correctly

**Weather API returning errors?**
- Verify API key is valid
- Check latitude/longitude are correct

**Google Maps returning no results?**
- Verify addresses are valid format
- Check API is enabled in Google Cloud Console

**Vapi call not initiating?**
- Verify VAPI_API_KEY and VAPI_ASSISTANT_ID
- Check webhook URL is publicly accessible

All API errors are logged to `debug_logs` table with full payload for debugging.
