# Fox Call Bot

Telegram bot + HTTP API backend for the Fox Call mobile app.

## How it works
1. User starts Telegram bot → presses **توليد توكن** → gets a token like `962731079:AAFA8gCnVKU334lCsZTLtVIMrkp3eAoOxhc`.
2. Inside the encoded part is the bot's **public URL**. The mobile app decodes it (using a shared secret) and uses it as its API server.
3. App sends `x-user-id` header on every request. Bot looks up balance from `data/bot_data.json`.
4. On `/api/call/start`, bot picks a working Telicall account from `data/telicall_accounts.json`, gets SIP credentials, deducts balance, returns SIP creds.
5. App connects via WebRTC + jssip → live two-way call.

## Required files
- `data/telicall_accounts.json` — array of `{email, token, device_id}` Telicall accounts.
- `data/bot_data.json` — auto-managed; users, balances, banned, settings.

## Env vars
- `BOT_TOKEN` — Telegram bot token.
- `PUBLIC_URL` — public HTTPS URL of this server (defaults to Replit dev domain).
- `PORT` — Flask port (default 5000).

## Admin commands
- `/addbalance USER_ID AMOUNT`
- `/setcost AMOUNT`
- `/stats`
