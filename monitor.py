import json
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

import requests

# CONSTANTS
LOGIN_URL      = "https://api.dev.eka.io/support/auth/token"
REFRESH_URL    = "https://api.dev.eka.io/support/auth/token/refresh"
GET_ALL_URL    = "https://api.dev.eka.io/support/vertexAi/getAllConfigs"
SNAPSHOT_FILE  = "snapshot.json"
LOG_FILE       = "change_log.json"

POLL_INTERVAL  = 10
RUN_DURATION   = 120

# ENV
USERNAME    = os.environ.get("SUPER_USERNAME", "")
PASSWORD    = os.environ.get("SUPER_PASSWORD", "")
SMTP_USER   = os.environ.get("GMAIL_USER", "")      # your Gmail address
SMTP_PASS   = os.environ.get("GMAIL_APP_PASS", "")  # 16-char app password
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")


# AUTH STATE
class AuthSession:
    """Holds access + refresh token, handles expiry-aware re-auth."""

    def __init__(self):
        self.access_token:  Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at:    int = 0          # epoch ms from API response
        self.user_name:     str = ""

    def is_expired(self, buffer_ms: int = 60_000) -> bool:
        """True if token expires within the next `buffer_ms` milliseconds."""
        now_ms = int(time.time() * 1000)
        return now_ms >= (self.expires_at - buffer_ms)

    def from_response(self, body: dict):
        self.access_token  = body.get("access_token", "")
        self.refresh_token = body.get("refresh_token", "")
        self.expires_at    = body.get("expires_at", 0)
        self.user_name     = body.get("name", "")

_session = AuthSession()


# LOGIN
def login() -> Optional[str]:
    """
    POST {username, password} → get access_token + refresh_token + expires_at.
    Response shape: {name, access_token, refresh_token, token_type, expires_at}
    """
    if not USERNAME or not PASSWORD:
        print("[ERROR] SUPER_USERNAME / SUPER_PASSWORD not set in GitHub secrets")
        return None

    try:
        resp = requests.post(
            LOGIN_URL,
            json={"username": USERNAME, "password": PASSWORD},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()

        _session.from_response(body)

        if not _session.access_token:
            print(f"[ERROR] No access_token in login response: {body}")
            return None

        expires_readable = datetime.fromtimestamp(_session.expires_at / 1000).isoformat()
        print(f"[AUTH] Login OK — user: {_session.user_name}  |  expires: {expires_readable}")
        return _session.access_token

    except requests.RequestException as e:
        print(f"[ERROR] Login failed: {e}")
        return None


def refresh_token() -> Optional[str]:
    """
    Use the refresh_token to get a new access_token without re-entering credentials.
    Falls back to full login if refresh fails.
    """
    if not _session.refresh_token:
        print("[AUTH] No refresh token — falling back to full login")
        return login()

    try:
        resp = requests.post(
            REFRESH_URL,
            json={"refresh_token": _session.refresh_token},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        _session.from_response(body)

        if not _session.access_token:
            print("[AUTH] Refresh returned no token — falling back to full login")
            return login()

        print(f"[AUTH] Token refreshed — new expiry: "
              f"{datetime.fromtimestamp(_session.expires_at / 1000).isoformat()}")
        return _session.access_token

    except requests.RequestException as e:
        print(f"[AUTH] Token refresh failed ({e}) — falling back to full login")
        return login()


def get_valid_token() -> Optional[str]:
    """Return a valid (non-expired) token, refreshing proactively if needed."""
    if _session.access_token and not _session.is_expired():
        return _session.access_token
    print("[AUTH] Token expired or missing — refreshing…")
    return refresh_token()


# FETCH CONFIGS
def fetch_configs() -> Optional[dict]:
    token = get_valid_token()
    if not token:
        return None
    try:
        resp = requests.get(
            GET_ALL_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        configs = body.get("data", [])
        return {str(c["id"]): c for c in configs}
    except requests.RequestException as e:
        print(f"[ERROR] getAllConfigs failed: {e}")
        return None


# SNAPSHOT
def load_snapshot() -> dict:
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_snapshot(data: dict):
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[SNAPSHOT] Saved {len(data)} configs")


# DIFF ENGINE
FLAT_TOP   = ["version", "type", "locationId", "projectId", "apiEndPoint",
              "model", "systemInstruction", "userInstruction"]
GC_FIELDS  = ["temperature", "maxOutputTokens", "topP", "seed"]


def flatten(cfg: dict) -> dict:
    flat = {}
    for f in FLAT_TOP:
        if f in cfg:
            flat[f] = cfg[f]
    gc = cfg.get("generationConfig", {})
    for f in GC_FIELDS:
        if f in gc:
            flat[f"generationConfig.{f}"] = gc[f]
    tb = gc.get("thinkingConfig", {}).get("thinkingBudget")
    if tb is not None:
        flat["generationConfig.thinkingConfig.thinkingBudget"] = tb
    return flat


def diff(old: dict, new: dict) -> list:
    keys = set(old) | set(new)
    return [
        {"field": k, "old": old.get(k, "(not set)"), "new": new.get(k, "(not set)")}
        for k in sorted(keys)
        if str(old.get(k, "(not set)")) != str(new.get(k, "(not set)"))
    ]


def find_changes(old_snap: dict, new_snap: dict) -> list:
    """
    Compare two full snapshots.
    Returns list of {configId, version, type, changes:[{field,old,new}]}
    """
    results = []
    all_ids = set(old_snap) | set(new_snap)

    for cid in all_ids:
        old_cfg = old_snap.get(cid)
        new_cfg = new_snap.get(cid)

        if old_cfg is None:
            # New config added
            results.append({
                "configId": cid,
                "version":  new_cfg.get("version", "?"),
                "type":     new_cfg.get("type", "?"),
                "event":    "ADDED",
                "changes":  [{"field": k, "old": "(new)", "new": v}
                             for k, v in flatten(new_cfg).items()],
            })
        elif new_cfg is None:
            # Config removed
            results.append({
                "configId": cid,
                "version":  old_cfg.get("version", "?"),
                "type":     old_cfg.get("type", "?"),
                "event":    "REMOVED",
                "changes":  [],
            })
        else:
            changes = diff(flatten(old_cfg), flatten(new_cfg))
            if changes:
                results.append({
                    "configId": cid,
                    "version":  new_cfg.get("version", "?"),
                    "type":     new_cfg.get("type", "?"),
                    "event":    "MODIFIED",
                    "changes":  changes,
                })

    return results


# CHANGE LOG
def append_log(entries: list):
    existing = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                existing = json.load(f)
        except Exception:
            pass
    combined = entries + existing
    with open(LOG_FILE, "w") as f:
        json.dump(combined[:500], f, indent=2, default=str)


# EMAIL
def build_email_body(changed_configs: list, ts: str) -> tuple:
    subject = (
        f"[VertexWatch] {len(changed_configs)} config(s) changed"
        f" — {ts}"
    )

    body  = f"VERTEXWATCH — CONFIG CHANGE ALERT\n{'━' * 54}\n\n"
    body += f"Endpoint  : {GET_ALL_URL}\n"
    body += f"Timestamp : {ts}\n"
    body += f"Changes   : {len(changed_configs)} config(s) modified\n\n"

    for item in changed_configs:
        event = item.get("event", "MODIFIED")
        body += f"{'─' * 40}\n"
        body += f"  Config ID : {item['configId']}\n"
        body += f"  Version   : {item['version']}\n"
        body += f"  Type      : {item['type']}\n"
        body += f"  Event     : {event}\n"

        if item["changes"]:
            body += f"\n  {'Field':<42}  {'Before':<20}  After\n"
            body += f"  {'─'*42}  {'─'*20}  {'─'*20}\n"
            for c in item["changes"]:
                field = c["field"].replace("generationConfig.", "")
                body += f"  {field:<42}  {str(c['old']):<20}  {c['new']}\n"
        body += "\n"

    body += f"{'━' * 54}\n"
    body += "Sent by VertexWatch — GitHub Actions Monitor\n"
    body += f"Run: https://github.com/${{GITHUB_REPOSITORY}}/actions"

    return subject, body


def send_email(subject: str, body: str) -> bool:
    if not all([SMTP_USER, SMTP_PASS, ALERT_EMAIL]):
        print("[EMAIL] Gmail credentials not configured — skipping alert")
        return False

    recipients = [e.strip() for e in ALERT_EMAIL.split(",") if e.strip()]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = ", ".join(recipients)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"[EMAIL] Alert sent → {', '.join(recipients)}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[EMAIL] Authentication failed — check GMAIL_USER and GMAIL_APP_PASS")
        return False
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")
        return False

# MAIN POLL LOOP
def main():
    print(f"[START] VertexWatch — {datetime.now().isoformat()}")
    print(f"[START] Polling every {POLL_INTERVAL}s for {RUN_DURATION}s")

    # Initial login to populate session
    if not login():
        print("[FATAL] Cannot authenticate — check SUPER_USERNAME / SUPER_PASSWORD secrets")
        sys.exit(1)

    # Load persisted snapshot (restored from Actions cache)
    snapshot = load_snapshot()
    is_first_run = not snapshot

    if is_first_run:
        print("[SNAPSHOT] No existing snapshot — building baseline on first fetch")
    else:
        print(f"[SNAPSHOT] Loaded {len(snapshot)} configs from cache")

    start_time = time.time()
    poll_count = 0
    total_alerts = 0

    while (time.time() - start_time) < RUN_DURATION:
        poll_count += 1
        now = datetime.now().isoformat(timespec="seconds")
        print(f"\n[POLL #{poll_count}] {now}")

        # Fetch latest configs (get_valid_token handles refresh automatically)
        current = fetch_configs()

        if current is None:
            print("[WARN] Could not fetch configs — skipping this poll")
            time.sleep(POLL_INTERVAL)
            continue

        print(f"[POLL] Fetched {len(current)} configs")

        if is_first_run:
            # First run — just save baseline, don't alert
            save_snapshot(current)
            snapshot = current
            is_first_run = False
            print("[SNAPSHOT] Baseline established — monitoring starts next poll")
        else:
            # Diff against snapshot
            changed = find_changes(snapshot, current)

            if changed:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[CHANGE] {len(changed)} config(s) changed!")
                for item in changed:
                    print(f"  → Config #{item['configId']} ({item['version']}) "
                          f"— {item['event']} — {len(item['changes'])} field(s)")
                    for c in item["changes"]:
                        print(f"    {c['field']}: {c['old']}  →  {c['new']}")

                # Send email
                subject, body = build_email_body(changed, ts)
                sent = send_email(subject, body)

                # Log the event
                log_entries = [{
                    "ts":        ts,
                    "level":     "change",
                    "message":   f"{len(changed)} config(s) changed",
                    "configs":   changed,
                    "emailSent": sent,
                    "runId":     os.environ.get("GITHUB_RUN_ID", "local"),
                }]
                append_log(log_entries)

                # Update snapshot to current state
                snapshot = current
                save_snapshot(current)
                total_alerts += 1

            else:
                print("[POLL] No changes detected")

        # Wait before next poll
        elapsed = time.time() - start_time
        remaining = RUN_DURATION - elapsed
        wait = min(POLL_INTERVAL, remaining)
        if wait > 0:
            print(f"[POLL] Waiting {int(wait)}s… ({int(remaining)}s remaining in run)")
            time.sleep(wait)

    print(f"\n[DONE] Run complete — {poll_count} polls, {total_alerts} alert(s) sent")


if __name__ == "__main__":
    main()
