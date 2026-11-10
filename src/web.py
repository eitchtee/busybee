import json
import os
import pickle
import re
import threading
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import Flow

from auth import SCOPES, token_path, get_calendar_service
from config import CONFIG_FILE, CREDENTIALS_DIR, CREDENTIALS_FILE, load_config

# Google redirects back over plain http://localhost, and may grant extra scopes
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

reload = threading.Event()  # set when config or tokens change; the sync loop restarts
_flows = {}  # oauth state -> (calendar name, Flow)
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # names become token file names
PAGE = os.path.join(os.path.dirname(__file__), "web.html")


def validate(cfg):
    """Return a list of problems with a config dict (empty if valid)."""
    if not isinstance(cfg, dict):
        return ["Config must be an object"]
    errors = []
    interval = cfg.get("sync_interval_seconds", 300)
    if not isinstance(interval, int) or interval < 10:
        errors.append("sync_interval_seconds must be an integer >= 10")

    names = []
    for i, cal in enumerate(cfg.get("calendars") or []):
        name = cal.get("name") if isinstance(cal, dict) else None
        if not isinstance(name, str) or not NAME_RE.match(name):
            errors.append(f"Calendar {i + 1}: name must use only letters, digits, _ or -")
        elif name in names:
            errors.append(f"Calendar name '{name}' is used twice")
        if not isinstance(cal, dict) or not isinstance(cal.get("id"), str) or not cal["id"]:
            errors.append(f"Calendar {i + 1}: id is required")
        names.append(name)

    def int_in(v, lo, hi):
        return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi

    for i, rule in enumerate(cfg.get("sync") or []):
        p = f"Sync rule {i + 1}"
        if not isinstance(rule, dict):
            errors.append(f"{p}: must be an object")
            continue
        for key in ("source", "target"):
            if rule.get(key) not in names:
                errors.append(f"{p}: {key} must be one of the calendars")
        if rule.get("source") == rule.get("target"):
            errors.append(f"{p}: source and target must differ")
        if "sync_days_in_advance" in rule and not int_in(rule["sync_days_in_advance"], 1, 365):
            errors.append(f"{p}: sync_days_in_advance must be 1-365")
        for key in ("work_hour_start", "work_hour_end"):
            if key in rule and not int_in(rule[key], 0, 24):
                errors.append(f"{p}: {key} must be 0-24")
        if ("work_hour_start" in rule) != ("work_hour_end" in rule):
            errors.append(f"{p}: set both work hours or neither")
        elif "work_hour_start" in rule and rule["work_hour_start"] >= rule["work_hour_end"]:
            errors.append(f"{p}: work_hour_start must be before work_hour_end")
        if "workdays" in rule and not (
            isinstance(rule["workdays"], list) and all(int_in(d, 0, 6) for d in rule["workdays"])
        ):
            errors.append(f"{p}: workdays must be a list of 0-6")
        for key in ("accepted_statuses", "pause_on"):
            if key in rule and not (
                isinstance(rule[key], list) and all(isinstance(s, str) for s in rule[key])
            ):
                errors.append(f"{p}: {key} must be a list of strings")
        if "default_text" in rule and not isinstance(rule["default_text"], str):
            errors.append(f"{p}: default_text must be text")
    return errors


def _send(h, code, body, ctype="application/json"):
    if not isinstance(body, bytes):
        body = (json.dumps(body) if ctype == "application/json" else body).encode()
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def _redirect(h, url):
    h.send_response(302)
    h.send_header("Location", url)
    h.end_headers()


def _calendar_names():
    return [c.get("name") for c in load_config().get("calendars", [])]


def _finish_auth(url):
    """Exchange the code in Google's redirect URL for a token and save it."""
    state = parse_qs(urlparse(url).query).get("state", [None])[0]
    if state not in _flows:
        raise ValueError("Unknown or expired sign-in attempt; start again")
    name, flow = _flows.pop(state)
    flow.fetch_token(authorization_response=url)
    with open(token_path(name, CREDENTIALS_DIR), "wb") as f:
        pickle.dump(flow.credentials, f)
    reload.set()
    return name


def handle(h, method):
    url = urlparse(h.path)
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    route = (method, url.path)
    try:
        if route == ("GET", "/"):
            with open(PAGE, "rb") as f:
                return _send(h, 200, f.read(), "text/html; charset=utf-8")

        if route == ("GET", "/api/config"):
            cfg = load_config()
            return _send(h, 200, {
                "config": cfg,
                "authed": {
                    c["name"]: os.path.exists(token_path(c["name"], CREDENTIALS_DIR))
                    for c in cfg.get("calendars", []) if NAME_RE.match(str(c.get("name")))
                },
                "client_secret": os.path.exists(CREDENTIALS_FILE),
            })

        if method == "POST":
            # JSON content type forces a CORS preflight, so other sites can't post here
            if h.headers.get("Content-Type") != "application/json":
                return _send(h, 415, {"error": "Content-Type must be application/json"})
            body = json.loads(h.rfile.read(min(int(h.headers.get("Content-Length", 0)), 1_000_000)))

        if route == ("POST", "/api/config"):
            errors = validate(body)
            if errors:
                return _send(h, 400, {"errors": errors})
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(body, f, indent=4)
            os.replace(tmp, CONFIG_FILE)
            reload.set()
            return _send(h, 200, {"ok": True})

        if route == ("GET", "/api/calendars"):
            if q.get("name") not in _calendar_names():
                return _send(h, 404, {"error": "Unknown calendar"})
            service = get_calendar_service(q["name"], CREDENTIALS_FILE, CREDENTIALS_DIR, interactive=False)
            items = service.calendarList().list(maxResults=250).execute().get("items", [])
            return _send(h, 200, [
                {"id": c["id"], "summary": c.get("summary", c["id"]), "primary": c.get("primary", False)}
                for c in items
            ])

        if route == ("GET", "/auth/start"):
            if q.get("name") not in _calendar_names():
                return _send(h, 404, "Unknown calendar; save it in the config first", "text/plain")
            if not os.path.exists(CREDENTIALS_FILE):
                return _send(h, 400, f"Missing {CREDENTIALS_FILE}", "text/plain")
            # Desktop OAuth clients only accept loopback redirects, so always use localhost
            port = h.headers.get("Host", "").rpartition(":")[2] or "80"
            flow = Flow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES, redirect_uri=f"http://localhost:{port}/auth/callback"
            )
            auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
            _flows[state] = (q["name"], flow)
            return _redirect(h, auth_url)

        if route == ("GET", "/auth/callback"):
            _finish_auth("http://localhost" + h.path)
            return _redirect(h, "/")

        if route == ("POST", "/auth/finish"):
            return _send(h, 200, {"name": _finish_auth(body.get("url", ""))})

        return _send(h, 404, {"error": "Not found"})
    except Exception as e:
        return _send(h, 400, {"error": str(e)})
