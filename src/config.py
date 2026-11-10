import json
import os

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CREDENTIALS_DIR = "credentials"
CREDENTIALS_FILE = os.path.join(
    CREDENTIALS_DIR,
    "client_secret.json",
)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        default_config = {
            "sync_interval_seconds": 300,
            "calendars": [
                {"name": "personal", "id": "primary"},
                {"name": "work", "id": "primary"},
            ],
            "sync": [
                {
                    "source": "personal",
                    "target": "work",
                    "sync_days_in_advance": 7,
                    "work_hour_start": 13,
                    "work_hour_end": 17,
                }
            ],
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=4)
        print(f"Created default {CONFIG_FILE}. Edit it in the web UI or by hand.")
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)
