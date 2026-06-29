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

#### Step 1: Create a Google Cloud Project
1. Go to https://console.cloud.google.com/
2. Click the project dropdown (top-left)
3. Click **"NEW PROJECT"**
4. Enter project name (e.g., "DailyOps AI")
5. Click **CREATE**
6. Wait for project to be created, then select it

#### Step 2: Enable Google Calendar API
1. In the top search bar, search for **"Google Calendar API"**
2. Click on it
3. Click **ENABLE**
4. Wait for it to activate

#### Step 3: Create OAuth 2.0 Credentials
1. Go to **APIs & Services** → **Credentials** (left sidebar)
2. Click **"+ CREATE CREDENTIALS"** → **OAuth client ID**
3. You may see "Configure OAuth consent screen first" — click that button
4. Choose **User Type: External**
5. Click **CREATE**
6. Fill in the form:
   - **App name**: DailyOps AI
   - **User support email**: your-email@gmail.com
   - **Developer contact**: your-email@gmail.com
7. Click **SAVE AND CONTINUE** (skip optional fields)
8. Back to Credentials page, click **"+ CREATE CREDENTIALS"** → **OAuth client ID** again
9. Choose **Application type: Desktop app**
10. Click **CREATE**
11. You'll see a popup with **Client ID** and **Client Secret** — copy these

```bash
GOOGLE_CALENDAR_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CALENDAR_CLIENT_SECRET=yyy
```

#### Step 4: Get Refresh Token (OAuth Flow)
Run this Python script to get the refresh token:

```python
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import json

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Replace with your Client ID and Secret
flow = InstalledAppFlow.from_client_secrets_file(
    'client_secret.json',  # Download this from GCloud console
    SCOPES
)

creds = flow.run_local_server(port=0)

# Print refresh token
print("Refresh Token:", creds.refresh_token)
```

Or use the official CLI:
```bash
# Install gcloud CLI from https://cloud.google.com/sdk/docs/install
gcloud auth application-default login
```

Then add to `.env`:
```bash
GOOGLE_CALENDAR_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CALENDAR_CLIENT_SECRET=yyy
GOOGLE_CALENDAR_REFRESH_TOKEN=zzz
```

### 2. Apple iCal (CalDAV)

#### Option A: iCloud (Recommended for Mac)

**Step 1: Generate App-Specific Password**
1. Go to https://appleid.apple.com/account/manage
2. Sign in with your Apple ID
3. Click **"Security"** (left sidebar)
4. Scroll down to **"App-specific passwords"**
5. Click **"Generate password"**
6. Select **"Calendar"** (or "Other App")
7. A password appears like: `xxxx-xxxx-xxxx-xxxx`
8. Copy this password

**Step 2: Add to .env**
```bash
APPLE_ICAL_CALDAV_URL=https://caldav.icloud.com
APPLE_ICAL_USERNAME=your-apple-id@icloud.com
APPLE_ICAL_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

**Step 3: Test (Optional)**
```bash
curl -u "your-apple-id@icloud.com:xxxx-xxxx-xxxx-xxxx" \
  "https://caldav.icloud.com/.well-known/caldav/" \
  -H "Depth: 0"
```

If it works, you'll see an XML response.

**Note:** iCloud CalDAV requires 2FA enabled on your Apple ID.

---

#### Option B: Nextcloud (For Self-Hosted Calendar)

If you run your own Nextcloud server:
```bash
APPLE_ICAL_CALDAV_URL=https://nextcloud.example.com
APPLE_ICAL_USERNAME=user@example.com
APPLE_ICAL_PASSWORD=password
```

---

#### Option C: Google Calendar (Easiest)

If you prefer, you can use Google Calendar via CalDAV instead:
```bash
APPLE_ICAL_CALDAV_URL=https://caldav.google.com/caldav/v2/your-email@gmail.com/calendar/primary
APPLE_ICAL_USERNAME=your-email@gmail.com
APPLE_ICAL_PASSWORD=your-app-specific-password
```

Get the Google app-specific password from: https://myaccount.google.com/apppasswords

---

**Recommendation:** Start with **iCloud** (Option A) if you use Apple devices. It's simplest and integrates with Mac Calendar.

### 3. Weather API (Choose One)

#### Option A: OpenWeather (Recommended)

**Step 1: Create Account**
1. Go to https://openweathermap.org/api
2. Click **"Sign Up"**
3. Fill in email, password, company name
4. Click **Create Account**
5. Check your email and verify

**Step 2: Get API Key**
1. Log in to https://openweathermap.org/api
2. Go to **"API Keys"** tab (top menu)
3. Your default API key is already generated
4. Copy the key under "API key" column

**Step 3: Add to .env**
```bash
WEATHER_API_KEY=xxx
WEATHER_PROVIDER=openweather
```

**Step 4: Test (Optional)**
```bash
curl "https://api.openweathermap.org/data/2.5/weather?lat=37.7749&lon=-122.4194&appid=YOUR_API_KEY&units=metric"
```

You should see JSON with temperature, humidity, weather description.

---

#### Option B: WeatherAPI.com

**Step 1: Create Account**
1. Go to https://www.weatherapi.com/
2. Click **"Sign Up Free"**
3. Fill in email and password
4. Click **Create Account**

**Step 2: Get API Key**
1. Log in to dashboard
2. Your API key is shown on the dashboard
3. Copy it

**Step 3: Add to .env**
```bash
WEATHER_API_KEY=xxx
WEATHER_PROVIDER=weatherapi
```

**Step 4: Test (Optional)**
```bash
curl "https://api.weatherapi.com/v1/current.json?key=YOUR_API_KEY&q=San+Francisco&aqi=no"
```

---

**Comparison:**
| Feature | OpenWeather | WeatherAPI |
|---------|------------|-----------|
| Free Tier | Yes (1000/day) | Yes (1M/month) |
| Forecast | Yes | Yes |
| Historical | Premium only | Yes (free) |
| Alerts | Premium only | Yes (free) |
| Best for | Production | Development |

**Recommendation:** Use **OpenWeather** for the MVP (simpler). Switch to WeatherAPI later if you need historical data.

### 4. Google Maps API

#### Step 1: Enable Distance Matrix API
1. In your Google Cloud project (https://console.cloud.google.com/)
2. Search for **"Distance Matrix API"** in the top search bar
3. Click on it
4. Click **ENABLE**

#### Step 2: Create API Key
1. Go to **APIs & Services** → **Credentials** (left sidebar)
2. Click **"+ CREATE CREDENTIALS"** → **API Key**
3. A popup appears with your API Key — copy it
4. (Optional) Restrict the key to only Distance Matrix API:
   - Click on the key you just created
   - Under "API restrictions", select **"Distance Matrix API"**
   - Click **SAVE**

```bash
GOOGLE_MAPS_API_KEY=xxx
```

#### Testing
```bash
curl "https://maps.googleapis.com/maps/api/distancematrix/json?origins=San+Francisco&destinations=Los+Angeles&key=YOUR_API_KEY"
```

You should get back distance and duration data.

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

### 7. iMessage Bridge (Optional - Mac Only)

iMessage Bridge allows DailyOps to send summaries via iMessage instead of SMS. It requires a local HTTP server running on your Mac.

#### Option A: Use open-source Bridge (Recommended)

**Step 1: Install Bridge**

There are several open-source iMessage bridges available:
- **[imessage-rest](https://github.com/ReagentX/imessage-rest)** (Python, easiest)
- **[EasyIMessage](https://github.com/Balackburn/EasyIMessage)** (Node.js)
- **[MacForge iMessage](https://macforge.io/)** (GUI app)

**Using imessage-rest (Python):**

```bash
# 1. Clone the repository
git clone https://github.com/ReagentX/imessage-rest.git
cd imessage-rest

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the bridge
python server.py
```

The bridge starts on `http://localhost:8001` (or configure the port)

**Step 2: Add to .env**
```bash
IMESSAGE_BRIDGE_URL=http://localhost:8001
```

**Step 3: Test**
```bash
curl -X POST http://localhost:8001/send \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello from DailyOps!",
    "recipient": "+1234567890"
  }'
```

---

#### Option B: Fallback to Twilio (Recommended for Production)

If iMessage bridge is unavailable, DailyOps automatically falls back to **Twilio SMS**.

**Setup Twilio:**
1. Go to https://www.twilio.com/
2. Sign up (free trial includes $15 credit)
3. Verify your phone number
4. Get your credentials:
   - Account SID
   - Auth Token
   - Buy a phone number

Add to `.env`:
```bash
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
TWILIO_PHONE_NUMBER=+1234567890
USER_PHONE_NUMBER=+1234567890
IMESSAGE_BRIDGE_URL=http://localhost:8001  # Leave as fallback
```

**Fallback Logic:**
- If iMessage bridge is running → Use iMessage
- If iMessage bridge is down → Automatically use Twilio SMS

---

**Recommendation:** For MVP, use **Twilio** (simpler, no local server needed). Add iMessage bridge later if you want native integration.

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
