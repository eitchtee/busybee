import time as _time

from googleapiclient.errors import HttpError
from datetime import datetime, timezone, timedelta

from db import (
    get_sync_token,
    set_sync_token,
    record_mapping,
    get_mapped_event,
    delete_mapping,
)
import logging

logger = logging.getLogger(__name__)


def get_event_datetime(event_date_info):
    if not event_date_info:
        return None
    if "dateTime" in event_date_info:
        return datetime.fromisoformat(event_date_info["dateTime"])
    if "date" in event_date_info:
        # All day event, start at midnight of that date in UTC
        dt = datetime.fromisoformat(event_date_info["date"])
        return dt.replace(tzinfo=timezone.utc)
    return None


def is_busy(event):
    if event.get("transparency") == "transparent":
        return False
    if event.get("status") == "cancelled":
        return False
    return True


# Throttle delay between API write calls to avoid rate limiting
API_THROTTLE_SECONDS = 0.3


def create_out_of_office_event(
    service, calendar_id, start_data, end_data, summary="Busy"
):
    event_body = {
        "summary": summary,
        "start": start_data,
        "end": end_data,
        "eventType": "outOfOffice",
        "outOfOfficeProperties": {"autoDeclineMode": "declineNone"},
        "extendedProperties": {"private": {"busybeeSync": "true"}},
    }
    try:
        _time.sleep(API_THROTTLE_SECONDS)
        created_event = (
            service.events().insert(calendarId=calendar_id, body=event_body).execute()
        )
        return created_event.get("id")
    except HttpError as e:
        logger.error(f"Error creating event in {calendar_id}: {e}")
        return None


def update_out_of_office_event(service, calendar_id, event_id, start_data, end_data):
    try:
        _time.sleep(API_THROTTLE_SECONDS)
        service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body={"start": start_data, "end": end_data},
        ).execute()
    except HttpError as e:
        logger.error(f"Error updating event {event_id} in {calendar_id}: {e}")


def delete_event_if_exists(service, calendar_id, event_id):
    try:
        _time.sleep(API_THROTTLE_SECONDS)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info(f"Deleted mapped event {event_id} from {calendar_id}")
    except HttpError as e:
        if e.resp.status in (410, 404):
            pass
        else:
            logger.error(f"Error deleting event {event_id} in {calendar_id}: {e}")


def is_within_work_hours(event, work_hour_start, work_hour_end):
    """Check if an event falls within the specified work hours.
    If work hours are not defined (None), all events pass.
    """
    if work_hour_start is None or work_hour_end is None:
        return True
    start_dt = get_event_datetime(event.get("start"))
    if not start_dt:
        return True  # Can't determine, let it through
    # Use local hour from the event's timezone
    event_hour = start_dt.hour
    return work_hour_start <= event_hour < work_hour_end


def get_self_response_status(event):
    """Get the current user's response status for an event.
    Returns one of: 'accepted', 'declined', 'tentative', 'needsAction', or None.
    """
    for attendee in event.get("attendees", []):
        if attendee.get("self"):
            return attendee.get("responseStatus")
    # No attendees or organizer-only event — treat as accepted
    return None


def process_events(
    events,
    source_account,
    targets,
    sync_days_in_advance,
    work_hour_start=None,
    work_hour_end=None,
    default_text="Busy",
    accepted_statuses=None,
):
    now = datetime.now(timezone.utc)
    max_sync_date = now + timedelta(days=sync_days_in_advance)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for event in events:
        event_id = event["id"]
        status = event.get("status")
        summary = event.get("summary", "(no title)")

        # Skip events that we created ourselves (tagged via extendedProperties)
        ext_props = event.get("extendedProperties", {}).get("private", {})
        if ext_props.get("busybeeSync") == "true":
            logger.debug(f"Skipping Busybee-created event {event_id}")
            continue

        # Only sync regular events (skip OOO, focusTime, workingLocation, etc.)
        event_type = event.get("eventType", "default")
        if status != "cancelled" and event_type != "default":
            logger.debug(
                f"Skipping non-default event type '{event_type}' for {event_id}"
            )
            continue

        # Skip all-day events
        if status != "cancelled" and event.get("start", {}).get("date"):
            logger.debug(f"Skipping all-day event '{summary}' ({event_id})")
            continue

        # Check RSVP status if accepted_statuses is configured
        if accepted_statuses is not None:
            response = get_self_response_status(event)
            if response is not None and response not in accepted_statuses:
                # RSVP doesn't match — remove any existing mappings
                for t in targets:
                    target_event_id = get_mapped_event(event_id, t["account"])
                    if target_event_id:
                        delete_event_if_exists(
                            t["service"], t["calendar_id"], target_event_id
                        )
                        delete_mapping(event_id, t["account"])
                        logger.info(
                            f"Removed mapping for '{summary}' ({event_id}) on {t['account']} (response: {response})"
                        )
                continue

        # Handle cancelled events - they have minimal fields
        if status == "cancelled":
            logger.info(
                f"Event {event_id} was cancelled, removing mapped events if any"
            )
            for t in targets:
                target_event_id = get_mapped_event(event_id, t["account"])
                if target_event_id:
                    delete_event_if_exists(
                        t["service"], t["calendar_id"], target_event_id
                    )
                    delete_mapping(event_id, t["account"])
                    logger.info(
                        f"Removed mapping {event_id} -> {target_event_id} on {t['account']}"
                    )
            continue

        # From here on we have a non-cancelled event
        start_dt = get_event_datetime(event.get("start"))
        end_dt = get_event_datetime(event.get("end"))

        # Check if out of bounds
        out_of_bounds = False
        if end_dt and end_dt < start_of_today:
            out_of_bounds = True
            logger.info(
                f"Event '{summary}' ({event_id}) is in the past (ends {end_dt}), skipping"
            )
        if start_dt and start_dt > max_sync_date:
            out_of_bounds = True
            logger.info(
                f"Event '{summary}' ({event_id}) is beyond {sync_days_in_advance} days (starts {start_dt}), skipping"
            )

        if not is_busy(event) or out_of_bounds:
            # Remove any previously mapped events
            for t in targets:
                target_event_id = get_mapped_event(event_id, t["account"])
                if target_event_id:
                    delete_event_if_exists(
                        t["service"], t["calendar_id"], target_event_id
                    )
                    delete_mapping(event_id, t["account"])
                    logger.info(
                        f"Removed mapping for '{summary}' ({event_id}) on {t['account']}"
                    )
            continue

        # Check work hour filter
        if not is_within_work_hours(event, work_hour_start, work_hour_end):
            # Event is outside work hours - remove any existing mappings
            for t in targets:
                target_event_id = get_mapped_event(event_id, t["account"])
                if target_event_id:
                    delete_event_if_exists(
                        t["service"], t["calendar_id"], target_event_id
                    )
                    delete_mapping(event_id, t["account"])
                    logger.info(
                        f"Removed mapping for '{summary}' ({event_id}) on {t['account']} (outside work hours)"
                    )
            continue

        # Event is busy and within bounds - create or update
        if "start" not in event or "end" not in event:
            logger.warning(f"Event '{summary}' ({event_id}) has no start/end, skipping")
            continue

        end_str = event["end"].get("dateTime", event["end"].get("date", ""))
        logger.info(
            f"Processing busy event '{summary}' ({event_id}): {event.get('start')} -> {event.get('end')}"
        )

        for t in targets:
            existing_target = get_mapped_event(event_id, t["account"])
            if not existing_target:
                new_event_id = create_out_of_office_event(
                    t["service"],
                    t["calendar_id"],
                    event["start"],
                    event["end"],
                    summary=default_text,
                )
                if new_event_id:
                    record_mapping(
                        event_id, source_account, new_event_id, t["account"], end_str
                    )
                    logger.info(
                        f"Created OOO event {event_id} -> {new_event_id} on {t['account']}"
                    )
            else:
                update_out_of_office_event(
                    t["service"],
                    t["calendar_id"],
                    existing_target,
                    event["start"],
                    event["end"],
                )
                record_mapping(
                    event_id, source_account, existing_target, t["account"], end_str
                )
                logger.info(
                    f"Updated OOO event {event_id} -> {existing_target} on {t['account']}"
                )


def sync_events(
    source_account,
    source_service,
    source_calendar_id,
    targets,
    sync_days_in_advance,
    work_hour_start=None,
    work_hour_end=None,
    default_text="Busy",
    accepted_statuses=None,
):
    sync_token = get_sync_token(source_account)

    try:
        if sync_token:
            logger.info(f"Using sync token for {source_account} (incremental sync)")
            events_result = (
                source_service.events()
                .list(
                    calendarId=source_calendar_id,
                    syncToken=sync_token,
                    showDeleted=True,
                )
                .execute()
            )
        else:
            now = datetime.now(timezone.utc).isoformat()
            max_time = (
                datetime.now(timezone.utc) + timedelta(days=sync_days_in_advance)
            ).isoformat()
            logger.info(
                f"No sync token for {source_account}, performing full sync from {now} to {max_time}"
            )
            events_result = (
                source_service.events()
                .list(
                    calendarId=source_calendar_id,
                    timeMin=now,
                    timeMax=max_time,
                    singleEvents=True,
                    showDeleted=True,
                )
                .execute()
            )
    except HttpError as e:
        if e.resp.status == 410:
            logger.warning(
                f"Sync token for {source_account} invalid (410 Gone). Performing full sync."
            )
            set_sync_token(source_account, None)
            now = datetime.now(timezone.utc).isoformat()
            max_time = (
                datetime.now(timezone.utc) + timedelta(days=sync_days_in_advance)
            ).isoformat()
            events_result = (
                source_service.events()
                .list(
                    calendarId=source_calendar_id,
                    timeMin=now,
                    timeMax=max_time,
                    singleEvents=True,
                    showDeleted=True,
                )
                .execute()
            )
        else:
            logger.error(f"Error fetching events for {source_account}: {e}")
            return

    while True:
        events = events_result.get("items", [])
        logger.info(f"Fetched {len(events)} events from {source_account}")
        process_events(
            events,
            source_account,
            targets,
            sync_days_in_advance,
            work_hour_start,
            work_hour_end,
            default_text,
            accepted_statuses,
        )

        page_token = events_result.get("nextPageToken")
        if not page_token:
            next_sync_token = events_result.get("nextSyncToken")
            if next_sync_token:
                set_sync_token(source_account, next_sync_token)
                logger.info(f"Stored new sync token for {source_account}")
            break

        try:
            events_result = (
                source_service.events()
                .list(
                    calendarId=source_calendar_id,
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as e:
            logger.error(f"Error fetching paginated events for {source_account}: {e}")
            break
