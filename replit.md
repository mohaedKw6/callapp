# Fox Call (callapp)

## Overview
Telegram bot + Expo React Native mobile client for SIP-TLS voice calling.
Bot issues encrypted tokens via `/token`, app uses them to fetch SIP
credentials and place real calls through a native Linphone module.

## Architecture
- **bot/** — Python (Flask + pyTelegramBotAPI). Entry: `bot/bot.py` →
  loads `callv2.py` (5500+ lines, do NOT modify) → `foxapp_api.py`
  exposes Flask API on `$PORT`.
- **fox-call/** — Expo SDK 54 React Native app, new architecture enabled.
  - `App.tsx` — root, screen routing
  - `screens/` — TokenScreen, DialerScreen, CallScreen
  - `services/api.ts` — bot HTTP client
  - `services/callManager.ts` — bridges Linphone events to UI state
  - `services/foxToken.ts` — pure-JS Token v2 decoder (DO NOT MODIFY,
    must stay in lockstep with `bot/foxapp_api.py`)
  - `modules/linphone-call/` — custom Expo Native Module wrapping
    `org.linphone:linphone-sdk-android:5.3.86` for real TLS-SIP audio
- **Procfile / railway.json / nixpacks.toml** — Railway deploy config

## Token v2 Format
`<userId>:<base64url(xor(payload, K_user))>` where
`payload = userId|serverUrl|nonce|hmac16` and
`K_user = SHA256("FOXCALL_2026_SHARED_SECRET_v1:" + userId)`.

## Deployment
- **Bot** → Railway (Python 3.11, nixpacks). Set `BOT_TOKEN`, `PUBLIC_URL`,
  `SESSION_SECRET`. Health check: `/api/health`.
- **App** → EAS Build (`preview` profile = APK). Requires native build,
  Expo Go will NOT work because of Linphone module.

## Environment / Secrets
- `BOT_TOKEN` (required) — Telegram bot token
- `PUBLIC_URL` — URL the app uses to reach the bot API
- `SESSION_SECRET` — Flask session signing
- `GITHUB_TOKEN`, `EXPO_TOKEN` — for CI / EAS

## Key Design Decisions
- TLS-SIP cannot be handled in pure JS (no raw socket TLS). Native
  Linphone module is the only realistic path for real audio.
- Bot side untouched: `callv2.py` is battle-tested and complex; we only
  added a thin Flask layer (`foxapp_api.py`).
- App entirely rewritten v2 with @expo/vector-icons, expo-linear-gradient,
  react-native-safe-area-context, expo-haptics for a modern UX.

## Workflow
- Workflow `Fox Bot` runs `python bot/bot.py` for local testing.
- Mobile app cannot be tested in Replit preview — must use EAS build.

## User Preferences
- Communication: Arabic, plain language, no jargon.
- Honest about limitations (e.g. native module needs real device test).
