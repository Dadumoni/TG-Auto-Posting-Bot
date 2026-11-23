# Telegram Auto-Posting Bot

A modular Telegram auto-posting bot built with Python, Telethon, MongoDB, and aiohttp. Features sequential message broadcasting, flood-wait handling, automated keep-alive health checks, and out-of-the-box Koyeb cloud deployment.

---

## Features

- **Modular Architecture:** Clean separation of concerns across config, database, handlers, services, and utils.
- **Telethon Dual-Client:** Telegram Bot for interaction and admin controls; Userbot for posting directly to targeted channels/groups.
- **Smart Group Resolution:** Accepts public links (`t.me/group`), private invite/message links (`t.me/c/...`), usernames, or peer IDs.
- **FloodWait & Rate Protection:** Uses sequential queue locking (`asyncio.Lock()`) and configurable delays between posts.
- **Koyeb & Cloud Ready:** Built-in lightweight HTTP server exposing `/health` and `/` on port `8080`, with an automated self-ping keep-alive loop.
- **Automated Scheduler:** Hourly auto-posting loop with countdown checks.

---

## Koyeb Deployment Guide

### Step 1: Push to GitHub
Ensure this repository is pushed to your GitHub account (as a private repository).

### Step 2: Create a New Service on Koyeb
1. Sign in to your [Koyeb Dashboard](https://app.koyeb.com/).
2. Click **Create App** or **Create Service**.
3. Select **GitHub** as the deployment source and select your `TG-Auto-Posting-Bot` repository.
4. Builder:
   - **Dockerfile** (Recommended): Koyeb will automatically use the included `Dockerfile`.
   - **Buildpack**: Alternatively, select Buildpack (it uses `Procfile` and `requirements.txt`).

### Step 3: Configure Port & Health Check
- **Port:** Set to `8080` (Protocol: `HTTP`).
- **Health Check Path:** Set HTTP path to `/health` (or `/`).

### Step 4: Add Environment Variables
Add the following Environment Variables in the Koyeb service settings:

| Variable | Description | Example |
| :--- | :--- | :--- |
| `API_ID` | Telegram API ID from my.telegram.org | `12345678` |
| `API_HASH` | Telegram API Hash from my.telegram.org | `0123456789abcdef0123456789abcdef` |
| `BOT_TOKEN` | Bot token from @BotFather | `123456789:ABCdefGHI...` |
| `SESSION_STRING` | Telethon Userbot session string | `1B23...your_session...` |
| `MONGO_URI` | MongoDB connection URI | `mongodb+srv://...` |
| `ADMIN_ID` | Telegram User ID of the admin | `123456789` |
| `PORT` | Web server port | `8080` |
| `APP_URL` | Public Koyeb app URL for self-ping keepalive | `https://your-app-name.koyeb.app` |

### Step 5: Deploy
Click **Deploy**. Koyeb will build the container, start the bot, verify the `/health` endpoint, and keep it running 24/7.

---

## Local Development

1. **Clone & Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Start the Bot:**
   ```bash
   python main.py
   ```

---

## Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | View bot overview, group counts, and help menu |
| `/debug <target>` | Check if the Userbot account has access to the target group |
| `/set_message <text>` | Set or update the promotional post message |
| `/get_message` | View the currently saved promotional post message |
| `/add_group <target>` | Add a group and immediately send an initial post |
| `/remove_group <id>` | Remove a single group from scheduler and database |
| `/remove_all` | Remove all groups from the database |
| `/all_groups` | List all saved groups with countdown to next post |
