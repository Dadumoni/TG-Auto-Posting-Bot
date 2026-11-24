# Telegram Auto-Posting Bot

A modular Telegram auto-posting bot built with Python, Telethon, MongoDB, and aiohttp. Features sequential message broadcasting, human-like randomized posting intervals, group slowmode/cooldown detection, interactive inline button link policy selection, automated keep-alive health checks, and out-of-the-box Koyeb cloud deployment.

---

## Features

- **Modular Architecture:** Clean separation of concerns across config, database, handlers, services, and utils.
- **Human-Like Randomized Interval:** Replaces rigid fixed intervals with a configurable randomized range (`POST_INTERVAL_MIN` to `POST_INTERVAL_MAX`), evading automated spam patterns.
- **Automatic Cooldown & Slowmode Detection:** Detects native Telegram slowmode limits when adding groups, saves them in MongoDB, and automatically reschedules posts to respect cooldowns.
- **Immediate Initial Post:** Dispatches an immediate post as soon as a new group is registered.
- **Interactive Link Policy Selection:** Prompts the admin with inline buttons (`t.me only` vs `Domain / External`) upon group registration to ensure appropriate templates are used.
- **Template Management:** Supports default, `t.me`-only, and external domain post templates.
- **Koyeb 10-Minute Auto-Ping:** Automatically pings the `/health` endpoint every 10 minutes (600s) to prevent free-tier container sleep.

---

## Koyeb Deployment Guide

### Step 1: Push to GitHub
Ensure this repository is pushed to your GitHub account as a private repository.

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
| `APP_URL` | Public Koyeb app URL (prevents free-tier sleep) | `https://your-app-name.koyeb.app` |
| `POST_INTERVAL_MIN` | Minimum random post interval in seconds | `3000` |
| `POST_INTERVAL_MAX` | Maximum random post interval in seconds | `4200` |
| `PING_INTERVAL_SECONDS` | Auto-ping interval in seconds (default 600) | `600` |

---

## Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | View bot overview, group counts, and help menu |
| `/debug <target>` | Check Userbot access and detect group slowmode cooldown |
| `/set_message <text>` | Set default promotional post message |
| `/set_tme_message <text>` | Set post message for groups supporting only t.me links |
| `/set_domain_message <text>` | Set post message for groups supporting domain/external links |
| `/get_message` | View all configured message templates |
| `/add_group <target>` | Add a group, detect cooldown, post immediately, and prompt for link type |
| `/remove_group <id>` | Remove a single group from scheduler and database |
| `/remove_all` | Remove all groups from the database |
| `/all_groups` | List all saved groups with link policy, cooldown, and countdowns |
