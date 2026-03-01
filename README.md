# 🐝 Busybee

A Python application that syncs Google Calendar events across multiple accounts. It automatically creates **Out of Office** events on target calendars to block busy timeslots, keeping all your calendars in sync.

## How it works

1. Busybee connects to your Google Calendar accounts via OAuth 2.0
2. For each sync rule you define, it watches the **source** calendar for busy events
3. When it finds one, it creates an **Out of Office** event on the **target** calendar
4. It runs in a loop, checking for changes every `sync_interval_seconds`
5. If a source event is cancelled or updated, the synced event is updated/removed accordingly

### Key features

- **Dynamic configuration** — define any number of calendars and sync rules
- **Work hour filtering** — only sync events that fall within specified hours
- **Incremental sync** — uses Google's `syncToken` for efficient polling
- **Duplicate prevention** — tags created events with `extendedProperties` and tracks mappings in a local SQLite database
- **Auto-cleanup** — removes stale database entries for past events

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A Google Cloud project with the Calendar API enabled and OAuth 2.0 credentials

### 1. Install dependencies

```bash
uv sync
```

### 2. Add your Google OAuth credentials

Place your OAuth client secret JSON file in the `credentials/` folder. The default expected filename is `client_secret.json`.

### 3. Configure

Copy the example config to `data/config.json`:

```bash
cp data/config.json.example data/config.json
```

Edit `data/config.json` with your calendar IDs and sync rules:

```json
{
    "sync_interval_seconds": 300,
    "calendars": [
        {"name": "personal", "id": "your-personal-calendar-id@gmail.com"},
        {"name": "work", "id": "your-work-calendar-id@gmail.com"}
    ],
    "sync": [
        {
            "source": "personal",
            "target": "work",
            "sync_days_in_advance": 7,
            "work_hour_start": 9,
            "work_hour_end": 18,
            "default_text": "Busy"
        }
    ]
}
```

#### Config reference

| Field | Description | Default |
|---|---|---|
| `sync_interval_seconds` | Seconds between sync cycles | `300` |
| `calendars[].name` | Unique name for the calendar (used for auth tokens) | — |
| `calendars[].id` | Google Calendar ID (`primary` for the default calendar) | — |
| `sync[].source` | Source calendar name | — |
| `sync[].target` | Target calendar name | — |
| `sync_days_in_advance` | Only sync events within this many days | `30` |
| `work_hour_start` | Only sync events starting at or after this hour (24h) | *(none — all hours)* |
| `work_hour_end` | Only sync events starting before this hour (24h) | *(none — all hours)* |
| `default_text` | Title for the created Out of Office event | `"Busy"` |

### 4. Authenticate

Run the app once locally to authenticate each calendar via browser:

```bash
uv run src/main.py
```

A browser window will open for each calendar account. After logging in, tokens are saved as pickle files in `credentials/`.

### 5. Run

```bash
uv run src/main.py
```

#### Flags

| Flag | Description |
|---|---|
| `--delete` | Delete all synced events from target calendars and reset the local database |

## Docker

> **Note:** You must authenticate locally first (step 4 above) before running in Docker, since OAuth requires a browser.

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f busybee
```

The `credentials/` and `data/` directories are mounted as volumes, so auth tokens and state persist across container restarts.

### Health check

Busybee exposes a health endpoint at `http://localhost:8080/health` that returns:

- **200** — sync loop is running normally
- **503** — app is still starting up
- **500** — last sync cycle failed (includes error details)

```bash
curl http://localhost:8080/health
```

```json
{"last_sync": "2026-02-28T19:30:00+00:00", "status": "ok", "error": null}
```

Docker uses this endpoint automatically via the `HEALTHCHECK` directive in the Dockerfile.

## Project structure

```
├── credentials/          # OAuth client secret + auth tokens (.pickle)
├── data/                 # config.json + sync_state.db (runtime data)
│   └── config.json.example   # Example configuration file
├── src/
│   ├── auth.py           # Google OAuth authentication
│   ├── config.py         # Configuration loading
│   ├── db.py             # SQLite state management
│   ├── health.py         # HTTP health check server
│   ├── main.py           # Entry point and sync loop
│   └── sync.py           # Core sync logic and API calls
├── Dockerfile
├── docker-compose.yml
```

