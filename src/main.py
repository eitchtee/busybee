import time
import logging
import argparse
import sys
from datetime import datetime, timezone
from config import load_config, CREDENTIALS_FILE, CREDENTIALS_DIR
from db import (
    init_db,
    get_all_mapped_events,
    get_all_mappings,
    clear_all_data,
    delete_mapping,
)
from auth import get_calendar_service
from sync import sync_events, delete_event_if_exists
from health import start_health_server, update_health

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Busybee - Google Calendar Sync")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete all synced events and reset database",
    )
    args = parser.parse_args()

    logger.info("Initializing database...")
    init_db()

    config = load_config()

    # Build calendar services from config
    calendars_config = config.get("calendars", [])
    services = {}  # name -> {"service": ..., "calendar_id": ...}

    for cal in calendars_config:
        name = cal["name"]
        cal_id = cal["id"]
        logger.info(f"Authenticating calendar '{name}' (id: {cal_id})...")
        service = get_calendar_service(name, CREDENTIALS_FILE, CREDENTIALS_DIR)
        services[name] = {"service": service, "calendar_id": cal_id}

    # Handle --delete
    if args.delete:
        logger.info("Starting deletion of all mapped events from calendars...")
        mapped_events = get_all_mapped_events()
        for target_event_id, target_account in mapped_events:
            target_info = services.get(target_account)
            if target_info:
                logger.info(
                    f"Deleting event {target_event_id} from {target_account}..."
                )
                delete_event_if_exists(
                    target_info["service"], target_info["calendar_id"], target_event_id
                )
        logger.info("Clearing local database...")
        clear_all_data()
        logger.info("Deletion complete. Exiting.")
        sys.exit(0)

    # Build sync rules from config
    sync_rules = config.get("sync", [])
    sync_interval = config.get("sync_interval_seconds", 300)

    logger.info(f"Loaded {len(sync_rules)} sync rules:")
    for i, rule in enumerate(sync_rules, 1):
        work_hours = ""
        if "work_hour_start" in rule and "work_hour_end" in rule:
            work_hours = f" (work hours: {rule['work_hour_start']}:00-{rule['work_hour_end']}:00)"
        logger.info(
            f"  {i}. {rule['source']} -> {rule['target']} "
            f"(sync {rule.get('sync_days_in_advance', 30)} days){work_hours}"
        )

    logger.info(f"Starting sync loop. Interval: {sync_interval} seconds")

    start_health_server()

    while True:
        try:
            # Cleanup past mapped events
            logger.info("Cleaning up past mapped events from local database...")
            all_mappings = get_all_mappings()
            now = datetime.now(timezone.utc)
            start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            cleaned_count = 0
            for row in all_mappings:
                if len(row) >= 3 and row[2]:
                    source_event_id, target_account, end_date_str = (
                        row[0],
                        row[1],
                        row[2],
                    )
                    try:
                        end_dt = datetime.fromisoformat(end_date_str)
                        if end_dt < start_of_today:
                            delete_mapping(source_event_id, target_account)
                            cleaned_count += 1
                    except ValueError:
                        pass
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} past event mappings from DB.")

            # Execute each sync rule
            for rule in sync_rules:
                source_name = rule["source"]
                target_name = rule["target"]
                sync_days = rule.get("sync_days_in_advance", 30)
                work_hour_start = rule.get("work_hour_start")
                work_hour_end = rule.get("work_hour_end")

                source_info = services.get(source_name)
                target_info = services.get(target_name)

                if not source_info:
                    logger.error(
                        f"Source calendar '{source_name}' not found in calendars config"
                    )
                    continue
                if not target_info:
                    logger.error(
                        f"Target calendar '{target_name}' not found in calendars config"
                    )
                    continue

                target_entry = {
                    "account": target_name,
                    "service": target_info["service"],
                    "calendar_id": target_info["calendar_id"],
                }

                default_text = rule.get("default_text", "Busy")

                logger.info(f"Syncing {source_name} -> {target_name}")
                sync_events(
                    source_name,
                    source_info["service"],
                    source_info["calendar_id"],
                    [target_entry],
                    sync_days,
                    work_hour_start,
                    work_hour_end,
                    default_text,
                )

            update_health(status="ok")

        except Exception as e:
            logger.error(f"Error during sync cycle: {e}", exc_info=True)
            update_health(status="error", error=e)

        logger.info(f"Sleeping for {sync_interval} seconds...")
        time.sleep(sync_interval)


if __name__ == "__main__":
    main()
