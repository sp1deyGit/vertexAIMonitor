import difflib
import json
import os
import smtplib
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

# ENVIRONMENT TARGET — set via ENV_TARGET secret ("dev" or "prod")
ENV_TARGET = os.environ.get("ENV_TARGET", "dev")

IST = timezone(timedelta(hours=5, minutes=30))

ENV_CONFIG = {
    "dev": {
        "LOGIN_URL":     "https://api.dev.eka.io/support/auth/token",
        "REFRESH_URL":   "https://api.dev.eka.io/support/auth/token/refresh",
        "GET_ALL_URL":   "https://api.dev.eka.io/support/vertexAi/getAllConfigs",
        "GET_ONE_URL":   "https://api.dev.eka.io/support/vertexAi/getConfig",
        "USERNAME":      os.environ.get("DEV_USERNAME", ""),
        "PASSWORD":      os.environ.get("DEV_PASSWORD", ""),
        "SNAPSHOT_FILE": "snapshot_dev.json",
        "LOG_FILE":      "change_log_dev.json",
    },
    "prod": {
        "LOGIN_URL":     "https://heimdall.eka.io/support/auth/token",
        "REFRESH_URL":   "https://heimdall.eka.io/support/auth/token/refresh",
        "GET_ALL_URL":   "https://heimdall.eka.io/support/vertexAi/getAllConfigs",
        "GET_ONE_URL":   "https://heimdall.eka.io/support/vertexAi/getConfig",
        "USERNAME":      os.environ.get("PROD_USERNAME", ""),
        "PASSWORD":      os.environ.get("PROD_PASSWORD", ""),
        "SNAPSHOT_FILE": "snapshot_prod.json",
        "LOG_FILE":      "change_log_prod.json",
    },
}

if ENV_TARGET not in ENV_CONFIG:
    print(f"[FATAL] Unknown ENV_TARGET: '{ENV_TARGET}' — must be 'dev' or 'prod'")
    sys.exit(1)

cfg           = ENV_CONFIG[ENV_TARGET]
LOGIN_URL     = cfg["LOGIN_URL"]
REFRESH_URL   = cfg["REFRESH_URL"]
GET_ALL_URL   = cfg["GET_ALL_URL"]
GET_ONE_URL   = cfg["GET_ONE_URL"]
USERNAME      = cfg["USERNAME"]
PASSWORD      = cfg["PASSWORD"]
SNAPSHOT_FILE = cfg["SNAPSHOT_FILE"]
LOG_FILE      = cfg["LOG_FILE"]

POLL_INTERVAL = 10
RUN_DURATION  = 120

# ENV — shared
SMTP_USER   = os.environ.get("GMAIL_USER", "")
SMTP_PASS   = os.environ.get("GMAIL_APP_PASS", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")

LONG_TEXT_FIELDS = {"systemInstruction", "userInstruction"}


# TIMEZONE
def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


# AUTH STATE
class AuthSession:
    """Holds access + refresh token, handles expiry-aware re-auth."""

    def __init__(self):
        self.access_token:  Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at:    int = 0
        self.user_name:     str = ""

    def is_expired(self, buffer_ms: int = 60_000) -> bool:
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
    if not USERNAME or not PASSWORD:
        print(f"[ERROR] {ENV_TARGET.upper()}_USERNAME / {ENV_TARGET.upper()}_PASSWORD not set in GitHub secrets")
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
    if _session.access_token and not _session.is_expired():
        return _session.access_token
    print("[AUTH] Token expired or missing — refreshing…")
    return refresh_token()


# FETCH CONFIGS
def fetch_config_by_id(config_id: str) -> Optional[dict]:
    token = get_valid_token()
    if not token:
        return None
    try:
        resp = requests.get(
            f"{GET_ONE_URL}/{config_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"[ERROR] getConfig/{config_id} failed: {e}")
        return None


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

        result = {}
        failed = []

        for c in configs:
            cid  = str(c["id"])
            full = fetch_config_by_id(cid)
            if full:
                result[cid] = full
                print(f"[FETCH] Config #{cid} ({full.get('type', '?')}) fetched")
            else:
                failed.append(cid)
                print(f"[FETCH] Config #{cid} — detail fetch failed")

        if failed:
            print(f"[WARN] {len(failed)} config(s) failed to fetch: {failed} — aborting poll, no diff will run")
            return None

        return result

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
FLAT_TOP  = ["version", "type", "locationId", "projectId", "apiEndPoint",
             "model", "systemInstruction", "userInstruction"]
GC_FIELDS = ["temperature", "maxOutputTokens", "topP", "seed"]


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
    results = []
    all_ids = set(old_snap) | set(new_snap)

    for cid in all_ids:
        old_cfg = old_snap.get(cid)
        new_cfg = new_snap.get(cid)

        if old_cfg is None:
            results.append({
                "configId": cid,
                "version":  new_cfg.get("version", "?"),
                "type":     new_cfg.get("type", "?"),
                "event":    "ADDED",
                "changes":  [{"field": k, "old": "(new)", "new": v}
                             for k, v in flatten(new_cfg).items()],
            })
        elif new_cfg is None:
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


# FORMAT
def format_instruction_text(raw: str) -> str:
    """Use Groq (free) to reformat raw instruction text into clean readable format."""
    if len(raw) < 100 or raw == "(not set)":
        return raw

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("[FORMAT] GROQ_API_KEY not set — skipping formatting")
        return raw

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":      "llama-3.1-8b-instant",
                "max_tokens": 2048,
                "messages": [
                    {
                        "role":    "system",
                        "content": "You are a text formatter. Reformat the given raw text into clean, readable format with proper line breaks, bullet points where appropriate, and clear section headers if present. Return only the reformatted text, no commentary."
                    },
                    {
                        "role":    "user",
                        "content": f"Reformat this instruction text:\n\n{raw}"
                    }
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[FORMAT] Groq formatting failed ({e}) — using raw text")
        return raw


# EMAIL
def inline_diff(old: str, new: str, field: str = "") -> tuple:
    """Returns (old_html, new_html) with only changed characters highlighted inline."""
    if field in LONG_TEXT_FIELDS:
        old = format_instruction_text(old)
        new = format_instruction_text(new)

    matcher  = difflib.SequenceMatcher(None, old, new)
    old_html = ""
    new_html = ""

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = old[i1:i2].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        new_chunk = new[j1:j2].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if op == "equal":
            old_html += old_chunk
            new_html += new_chunk
        elif op == "replace":
            old_html += f'<mark style="background:#ffb3b3;color:#900;border-radius:2px;padding:0 1px;">{old_chunk}</mark>'
            new_html += f'<mark style="background:#b3ffb3;color:#060;border-radius:2px;padding:0 1px;">{new_chunk}</mark>'
        elif op == "delete":
            old_html += f'<mark style="background:#ffb3b3;color:#900;border-radius:2px;padding:0 1px;">{old_chunk}</mark>'
        elif op == "insert":
            new_html += f'<mark style="background:#b3ffb3;color:#060;border-radius:2px;padding:0 1px;">{new_chunk}</mark>'

    return old_html, new_html


def build_email_body(changed_configs: list, ts: str) -> tuple:
    env_label = "PRODUCTION 🔴" if ENV_TARGET == "prod" else "DEV 🟡"
    subject   = f"[VertexWatch][{ENV_TARGET.upper()}] {len(changed_configs)} config(s) changed — {ts}"

    html = f"""
    <html><body style="font-family:monospace;font-size:13px;background:#f4f4f4;padding:20px;margin:0;">
    <div style="max-width:960px;margin:auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.12);">

      <!-- HEADER -->
      <div style="background:#1a1a2e;color:#fff;padding:20px 30px;">
        <h2 style="margin:0;font-size:18px;letter-spacing:0.5px;">&#128269; VertexWatch — Config Change Alert</h2>
        <p style="margin:6px 0 0;color:#aaa;font-size:12px;">
          Environment: <strong style="color:#fff;">{env_label}</strong>
          &nbsp;|&nbsp; {ts}
          &nbsp;|&nbsp; {len(changed_configs)} config(s) changed
          &nbsp;|&nbsp; <a href="{GET_ALL_URL}" style="color:#7eb8f7;text-decoration:none;">API Endpoint</a>
        </p>
      </div>
    """

    event_colors = {
        "MODIFIED": ("#fff3cd", "#856404", "~"),
        "ADDED":    ("#d4edda", "#155724", "+"),
        "REMOVED":  ("#f8d7da", "#721c24", "-"),
    }

    for item in changed_configs:
        event        = item.get("event", "MODIFIED")
        bg, fg, icon = event_colors.get(event, ("#fff", "#000", "?"))

        html += f"""
      <div style="margin:24px 30px 0;">
        <div style="background:{bg};color:{fg};padding:10px 16px;border-radius:6px 6px 0 0;font-weight:bold;font-size:13px;">
          [{icon}] Config #{item['configId']} &nbsp;|&nbsp; {item['type']} &nbsp;|&nbsp; {item['version']} &nbsp;|&nbsp; {event}
        </div>
        <table style="width:100%;border-collapse:collapse;border:1px solid #ddd;border-top:none;table-layout:fixed;">
          <colgroup>
            <col style="width:18%;">
            <col style="width:41%;">
            <col style="width:41%;">
          </colgroup>
          <thead>
            <tr style="background:#f0f0f0;">
              <th style="padding:8px 12px;text-align:left;border:1px solid #ddd;font-size:12px;">Field</th>
              <th style="padding:8px 12px;text-align:left;border:1px solid #ddd;font-size:12px;background:#fff5f5;">&#8592; Before</th>
              <th style="padding:8px 12px;text-align:left;border:1px solid #ddd;font-size:12px;background:#f5fff5;">After &#8594;</th>
            </tr>
          </thead>
          <tbody>
        """

        if item["changes"]:
            for c in item["changes"]:
                field    = c["field"].replace("generationConfig.", "gc.")
                old_val  = str(c["old"])
                new_val  = str(c["new"])
                old_html, new_html = inline_diff(old_val, new_val, field=c["field"])

                html += f"""
            <tr>
              <td style="padding:8px 12px;border:1px solid #ddd;font-weight:bold;vertical-align:top;font-size:12px;word-break:break-word;">{field}</td>
              <td style="padding:8px 12px;border:1px solid #ddd;background:#fff8f8;white-space:pre-wrap;word-break:break-word;vertical-align:top;font-size:12px;line-height:1.6;">{old_html}</td>
              <td style="padding:8px 12px;border:1px solid #ddd;background:#f8fff8;white-space:pre-wrap;word-break:break-word;vertical-align:top;font-size:12px;line-height:1.6;">{new_html}</td>
            </tr>
                """
        else:
            html += """
            <tr>
              <td colspan="3" style="padding:8px 12px;border:1px solid #ddd;color:#888;font-size:12px;">No field-level changes recorded.</td>
            </tr>
            """

        html += """
          </tbody>
        </table>
      </div>
        """

    html += f"""
      <div style="margin:30px;padding-top:16px;border-top:1px solid #eee;color:#aaa;font-size:11px;">
        Sent by <strong>VertexWatch</strong> — GitHub Actions Monitor &nbsp;|&nbsp;
        <a href="https://github.com/${{GITHUB_REPOSITORY}}/actions" style="color:#7eb8f7;text-decoration:none;">View Run &#8599;</a>
      </div>
    </div>
    </body></html>
    """

    return subject, html


def send_email(subject: str, html_body: str) -> bool:
    if not all([SMTP_USER, SMTP_PASS, ALERT_EMAIL]):
        print("[EMAIL] Gmail credentials not configured — skipping alert")
        return False

    recipients = [e.strip() for e in ALERT_EMAIL.split(",") if e.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

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
    print(f"[START] VertexWatch [{ENV_TARGET.upper()}] — {now_ist()}")
    print(f"[START] Polling every {POLL_INTERVAL}s for {RUN_DURATION}s")
    print(f"[START] Endpoint: {GET_ALL_URL}")

    if not login():
        print(f"[FATAL] Cannot authenticate — check {ENV_TARGET.upper()}_USERNAME / {ENV_TARGET.upper()}_PASSWORD secrets")
        sys.exit(1)

    snapshot     = load_snapshot()
    is_first_run = not snapshot

    if is_first_run:
        print("[SNAPSHOT] No existing snapshot — building baseline on first fetch")
    else:
        print(f"[SNAPSHOT] Loaded {len(snapshot)} configs from cache")

    start_time   = time.time()
    poll_count   = 0
    total_alerts = 0

    while (time.time() - start_time) < RUN_DURATION:
        poll_count += 1
        now = now_ist()
        print(f"\n[POLL #{poll_count}] {now}")

        current = fetch_configs()

        if current is None:
            print("[WARN] Could not fetch configs — skipping this poll")
            time.sleep(POLL_INTERVAL)
            continue

        print(f"[POLL] Fetched {len(current)} configs (full detail)")

        if is_first_run:
            save_snapshot(current)
            snapshot     = current
            is_first_run = False
            print("[SNAPSHOT] Baseline established — monitoring starts next poll")
        else:
            changed = find_changes(snapshot, current)

            if changed:
                ts = now_ist()
                print(f"[CHANGE] {len(changed)} config(s) changed!")
                for item in changed:
                    print(f"  → Config #{item['configId']} ({item['version']}) "
                          f"— {item['event']} — {len(item['changes'])} field(s)")
                    for c in item["changes"]:
                        print(f"    {c['field']}: {c['old']}  →  {c['new']}")

                subject, html_body = build_email_body(changed, ts)
                sent = send_email(subject, html_body)

                log_entries = [{
                    "ts":        ts,
                    "env":       ENV_TARGET,
                    "level":     "change",
                    "message":   f"{len(changed)} config(s) changed",
                    "configs":   changed,
                    "emailSent": sent,
                    "runId":     os.environ.get("GITHUB_RUN_ID", "local"),
                }]
                append_log(log_entries)

                snapshot = current
                save_snapshot(current)
                total_alerts += 1

            else:
                print("[POLL] No changes detected")

        elapsed   = time.time() - start_time
        remaining = RUN_DURATION - elapsed
        wait      = min(POLL_INTERVAL, remaining)
        if wait > 0:
            print(f"[POLL] Waiting {int(wait)}s… ({int(remaining)}s remaining in run)")
            time.sleep(wait)

    print(f"\n[DONE] Run complete — {poll_count} polls, {total_alerts} alert(s) sent")


if __name__ == "__main__":
    main()
