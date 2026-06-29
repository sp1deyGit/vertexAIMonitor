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
 
# ENVIRONMENT TARGET — set via ENV_TARGET secret ("dev", "jkc-uat", "jkc-prod" or "prod")
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
    "sandbox": {
        "LOGIN_URL":     "https://api-uat-sandbox.eka.io/support/auth/token",
        "REFRESH_URL":   "https://api-uat-sandbox.eka.io/support/auth/token/refresh",
        "GET_ALL_URL":   "https://api-uat-sandbox.eka.io/support/vertexAi/getAllConfigs",
        "GET_ONE_URL":   "https://api-uat-sandbox.eka.io/support/vertexAi/getConfig",
        "USERNAME":      os.environ.get("SANDBOX_USERNAME", ""),
        "PASSWORD":      os.environ.get("SANDBOX_PASSWORD", ""),
        "SNAPSHOT_FILE": "snapshot_sandbox.json",
        "LOG_FILE":      "change_log_sandbox.json",
    },
    "jkc-uat": {
        "LOGIN_URL":     "https://api-uat.jkyms.com/support/auth/token",
        "REFRESH_URL":   "https://api-uat.jkyms.com/support/auth/token/refresh",
        "GET_ALL_URL":   "https://api-uat.jkyms.com/support/vertexAi/getAllConfigs",
        "GET_ONE_URL":   "https://api-uat.jkyms.com/support/vertexAi/getConfig",
        "USERNAME":      os.environ.get("JKC_USERNAME", ""),
        "PASSWORD":      os.environ.get("JKC_UAT_PASSWORD", ""),
        "SNAPSHOT_FILE": "snapshot_jkc_uat.json",
        "LOG_FILE":      "change_log_jkc_uat.json",
    },
    "jkc-prod": {
        "LOGIN_URL":     "https://api.jkyms.com/support/auth/token",
        "REFRESH_URL":   "https://api.jkyms.com/support/auth/token/refresh",
        "GET_ALL_URL":   "https://api.jkyms.com/support/vertexAi/getAllConfigs",
        "GET_ONE_URL":   "https://api.jkyms.com/support/vertexAi/getConfig",
        "USERNAME":      os.environ.get("JKC_USERNAME", ""),
        "PASSWORD":      os.environ.get("JKC_PROD_PASSWORD", ""),
        "SNAPSHOT_FILE": "snapshot_jkc_prod.json",
        "LOG_FILE":      "change_log_jkc_prod.json",
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
    print(f"[FATAL] Unknown ENV_TARGET: '{ENV_TARGET}' — must be 'dev', 'jkc-uat', 'jkc-prod' or 'prod'")
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
RUN_DURATION  = 20  # Allow up to 2 polls (1 normal + 1 retry if failed)
 
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
 
 
# LOGIN (with retry for CI/CD environments)
def login(attempt: int = 1, max_attempts: int = 3) -> Optional[str]:
    if not USERNAME or not PASSWORD:
        print(f"[ERROR] JKC_USERNAME / JKC_PASSWORD not set in GitHub secrets")
        return None
 
    try:
        print(f"[AUTH] Login attempt {attempt}/{max_attempts}...")
        resp = requests.post(
            LOGIN_URL,
            json={"username": USERNAME, "password": PASSWORD},
            timeout=45,  # Increased from 15 to 45 seconds
            headers={"Content-Type": "application/json"}
        )
         
        # Log response status and headers
        print(f"[AUTH] Response status: {resp.status_code}")
         
        # Handle specific error codes
        if resp.status_code == 409:
            # Conflict — likely concurrent login or rate limit
            print(f"[ERROR] 409 Conflict detected")
            print(f"[ERROR] Response body: {resp.text[:500]}")
            if attempt < max_attempts:
                wait_time = 10 * attempt  # Exponential backoff: 10s, 20s, 30s
                print(f"[AUTH] Retrying in {wait_time}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait_time)
                return login(attempt + 1, max_attempts)
            else:
                print(f"[ERROR] 409 Conflict after {max_attempts} attempts — giving up")
                return None
         
        elif resp.status_code == 401:
            print(f"[ERROR] 401 Unauthorized — Invalid credentials")
            print(f"[ERROR] Response: {resp.text[:500]}")
            return None
         
        elif resp.status_code == 403:
            print(f"[ERROR] 403 Forbidden — Access denied")
            print(f"[ERROR] Response: {resp.text[:500]}")
            return None
         
        elif resp.status_code >= 400:
            print(f"[ERROR] HTTP {resp.status_code} error")
            print(f"[ERROR] Response: {resp.text[:500]}")
            return None
         
        resp.raise_for_status()
        body = resp.json()
        _session.from_response(body)
 
        if not _session.access_token:
            print(f"[ERROR] No access_token in login response: {body}")
            return None
 
        expires_readable = datetime.fromtimestamp(_session.expires_at / 1000).isoformat()
        print(f"[AUTH] Login OK — user: {_session.user_name}  |  expires: {expires_readable}")
        return _session.access_token
 
    except requests.exceptions.Timeout as e:
        print(f"[ERROR] Login timeout (45s) — {e}")  # Updated error message
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Connection error — {e}")
        return None
    except requests.RequestException as e:
        print(f"[ERROR] Login request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[ERROR] Status code: {e.response.status_code}")
            print(f"[ERROR] Response body: {e.response.text[:500]}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error during login: {e}")
        return None
 
 
def refresh_token() -> Optional[str]:
    if not _session.refresh_token:
        print("[AUTH] No refresh token — falling back to full login")
        return login()
 
    try:
        resp = requests.post(
            REFRESH_URL,
            json={"refresh_token": _session.refresh_token},
            timeout=30,  # Increased from 10 to 30 seconds
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
        print(f"[ERROR] No valid token available for getConfig/{config_id}")
        return None
    try:
        resp = requests.get(
            f"{GET_ONE_URL}/{config_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,  # Increased from 10 to 30 seconds
        )
         
        if resp.status_code >= 400:
            print(f"[ERROR] getConfig/{config_id} failed with HTTP {resp.status_code}")
            print(f"[ERROR] Response: {resp.text[:500]}")
            return None
         
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        print(f"[ERROR] getConfig/{config_id} timeout (30s)")  # Updated error message
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] getConfig/{config_id} connection error: {e}")
        return None
    except requests.RequestException as e:
        print(f"[ERROR] getConfig/{config_id} request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[ERROR] Status: {e.response.status_code} | Body: {e.response.text[:500]}")
        return None
    except Exception as e:
        print(f"[ERROR] getConfig/{config_id} unexpected error: {e}")
        return None
 
 
def fetch_configs() -> Optional[dict]:
    token = get_valid_token()
    if not token:
        print(f"[ERROR] No valid token available for getAllConfigs")
        return None
    try:
        resp = requests.get(
            GET_ALL_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,  # Increased from 10 to 30 seconds
        )
         
        if resp.status_code >= 400:
            print(f"[ERROR] getAllConfigs failed with HTTP {resp.status_code}")
            print(f"[ERROR] Response: {resp.text[:500]}")
            return None
         
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
 
    except requests.exceptions.Timeout:
        print(f"[ERROR] getAllConfigs timeout (30s)")  # Updated error message
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] getAllConfigs connection error: {e}")
        return None
    except requests.RequestException as e:
        print(f"[ERROR] getAllConfigs request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[ERROR] Status: {e.response.status_code} | Body: {e.response.text[:500]}")
        return None
    except Exception as e:
        print(f"[ERROR] getAllConfigs unexpected error: {e}")
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
        print("[FORMAT] Calling Groq API to format instruction text...")
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":      "llama-3.3-70b-versatile",  # Upgraded model for higher baseline TPM limits
                "max_tokens": 2048,
                "messages": [
                    {
                        "role":    "system",
                        "content": """You are a technical text formatter for OCR/extraction instructions.
 
Your task: Reformat raw instruction text into clean, scannable format.
 
RULES:
1. Preserve all technical constraints and rules from the original
2. Use bullet points (•) for lists of requirements
3. Use numbered lists (1. 2. 3.) for sequential steps or priority-ordered rules
4. Create clear section headers with "===HEADER===" format
5. Bold key terms using **term** markdown
6. Break long paragraphs into short, focused sentences
7. Extract and highlight critical constraints (e.g., "NEVER modify...", "MUST include...")
8. Maintain ALL regex patterns, field names, and technical details exactly as-is
9. Use whitespace effectively — add blank lines between major sections
10. Do NOT add or invent requirements not in the original text
 
OUTPUT should be clean, maintainable, and dashboard-ready."""
                    },
                    {
                        "role":    "user",
                        "content": f"Reformat this instruction text:\n\n{raw}"
                    }
                ],
            },
            timeout=30,
        )
         
        if resp.status_code >= 400:
            print(f"[ERROR] Groq format API failed with HTTP {resp.status_code}")
            print(f"[ERROR] Response: {resp.text[:500]}")
            return raw
         
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        print("[FORMAT] Groq formatting succeeded")
        return result
    except requests.exceptions.Timeout:
        print(f"[ERROR] Groq format API timeout (30s)")
        return raw
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Groq format API connection error: {e}")
        return raw
    except requests.RequestException as e:
        print(f"[ERROR] Groq format API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[ERROR] Status: {e.response.status_code} | Body: {e.response.text[:500]}")
        return raw
    except Exception as e:
        print(f"[ERROR] Groq format API unexpected error: {e}")
        return raw
 
 
# EMAIL AI UTILITIES
def generate_functional_summary(old_text: str, new_text: str) -> str:
    """Uses Groq to generate a concise summary of how a prompt change transforms operational behavior."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return "GROQ_API_KEY environment secret is missing. Cannot evaluate prompt modifications."

    # Perform line-level comparison locally to optimize token payloads
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    unified_diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
    delta_lines = "\n".join([line for line in unified_diff if line.startswith('+') or line.startswith('-')])

    if not delta_lines.strip():
        return "No explicit configuration or structural rule modifications detected in this instruction field update."

    try:
        print("[SUMMARY] Dispatching isolated prompt delta to Groq for change analysis...")
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":      "llama-3.3-70b-versatile",
                "max_tokens": 300,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert prompt engineer and code intelligence analyzer. You will receive a unified text diff outlining updates to an OCR extraction system instruction prompt. Provide a highly direct, concise 2-to-3 sentence explanation summarizing what behavioral changes, technical rules, or execution restrictions this modification forces onto the processing engine."
                    },
                    {
                        "role": "user",
                        "content": f"Analyze the following changes made to the system instructions and explain its real-world functional impact:\n\n{delta_lines}"
                    }
                ]
            },
            timeout=30,
        )

        if resp.status_code >= 400:
            return "Unable to compile functional impact analysis due to an upstream API connectivity issue."
            
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ERROR] Failed to compile prompt functional overview: {e}")
        return "A processing error occurred while attempting to dynamically evaluate the prompt engineering changes."


def ai_diff(old: str, new: str) -> tuple:
    """Use Groq to semantically compare two texts by processing only changed blocks to save tokens."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("[DIFF] GROQ_API_KEY not set — falling back to character diff")
        return char_diff(old, new)
 
    # Split lines to track identical sections and isolate actual modifications
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    old_html_chunks = []
    new_html_chunks = []
 
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk_text = "".join(old_lines[i1:i2])
        new_chunk_text = "".join(new_lines[j1:j2])
 
        if op == "equal":
            # Pass unchanged segments directly through local Python processing (0 API tokens used)
            escaped_old = old_chunk_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            escaped_new = new_chunk_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            old_html_chunks.append(escaped_old)
            new_html_chunks.append(escaped_new)
        else:
            # Handle straightforward deletions or additions locally to preserve tokens
            if op == "delete" or not new_chunk_text.strip():
                escaped = old_chunk_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                old_html_chunks.append(f'<mark style="background:#ffb3b3;color:#900;border-radius:2px;padding:0 1px;">{escaped}</mark>')
                continue
            if op == "insert" or not old_chunk_text.strip():
                escaped = new_chunk_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                new_html_chunks.append(f'<mark style="background:#b3ffb3;color:#060;border-radius:2px;padding:0 1px;">{escaped}</mark>')
                continue
 
            # Check estimated token impact of complex modifications (approx. 4 characters per token)
            estimated_tokens = (len(old_chunk_text) + len(new_chunk_text)) // 4
            if estimated_tokens > 4500:
                print(f"[DIFF] Modification block too large ({estimated_tokens} est. tokens). Running local fallback char_diff for safety.")
                block_old_html, block_new_html = char_diff(old_chunk_text, new_chunk_text)
                old_html_chunks.append(block_old_html)
                new_html_chunks.append(block_new_html)
                continue
 
            try:
                print(f"[DIFF] Calling Groq API for semantic block diff ({estimated_tokens} est. tokens)...")
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":      "llama-3.3-70b-versatile",  # Upgraded model for higher TPM allocations
                        "max_tokens": 4096,
                        "temperature": 0.0,
                        "messages": [
                            {
                                "role": "system",
                                "content": """You are a precise semantic diff tool for technical text segments.
 
TASK: Compare the BEFORE and AFTER text segment, and return HTML with highlighted changes.
 
OUTPUT: Return ONLY a valid JSON object with exactly two keys:
  "before_html" — the BEFORE text segment with changes marked
  "after_html" — the AFTER text segment with changes marked
 
HIGHLIGHTING RULES:
- REMOVED/CHANGED in BEFORE: wrap in <mark style="background:#ffb3b3;color:#900;border-radius:2px;padding:0 1px;">text</mark>
- ADDED/CHANGED in AFTER: wrap in <mark style="background:#b3ffb3;color:#060;border-radius:2px;padding:0 1px;">text</mark>
- Highlight at SENTENCE or PHRASE level (not character-by-character)
- Preserve ALL line breaks and whitespace using proper HTML entities/formatting
- Return ONLY valid JSON — no markdown, no explanation, no fences"""
                            },
                            {
                                "role": "user",
                                "content": f"BEFORE:\n{old_chunk_text}\n\nAFTER:\n{new_chunk_text}"
                            }
                        ],
                    },
                    timeout=45,
                )
                 
                if resp.status_code >= 400:
                    print(f"[ERROR] Groq block diff failed with HTTP {resp.status_code}. Using fallback char_diff.")
                    block_old_html, block_new_html = char_diff(old_chunk_text, new_chunk_text)
                    old_html_chunks.append(block_old_html)
                    new_html_chunks.append(block_new_html)
                    continue
                 
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                
                # Sanitize random LLM markdown wrappers if present
                if content.startswith("```"):
                    content = content.strip("`").strip("json").strip()
                    
                parsed  = json.loads(content)
                old_html_chunks.append(parsed["before_html"])
                new_html_chunks.append(parsed["after_html"])
                print("[DIFF] Groq semantic block diff succeeded")
     
            except Exception as e:
                print(f"[ERROR] Semantic block diff exception: {e} — using fallback char_diff")
                block_old_html, block_new_html = char_diff(old_chunk_text, new_chunk_text)
                old_html_chunks.append(block_old_html)
                new_html_chunks.append(block_new_html)
 
    return "".join(old_html_chunks), "".join(new_html_chunks)
 
 
def char_diff(old: str, new: str) -> tuple:
    """Fallback character-level diff using difflib."""
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
 
 
def inline_diff(old: str, new: str, field: str = "") -> tuple:
    """Use AI diff for long text fields, char diff for everything else."""
    if field in LONG_TEXT_FIELDS and len(old) + len(new) > 200:
        return ai_diff(old, new)
    return char_diff(old, new)
 
 
def build_email_body(changed_configs: list, ts: str) -> tuple:
    env_label_map = {
        "dev": "DEV 🟡",
        "sandbox": "SANDBOX ⚪",
        "jkc-uat": "JKC-UAT 🔵",
        "jkc-prod": "JKC-PROD 🟠",
        "prod": "PRODUCTION 🔴",
    }
    env_label = env_label_map.get(ENV_TARGET, ENV_TARGET.upper())
    subject   = f"OCR CONFIG CHANGE[{ENV_TARGET.upper()}] {len(changed_configs)} Version(s) changed"
 
    html = f"""
    <html><body style="font-family:monospace;font-size:13px;background:#f4f4f4;padding:20px;margin:0;">
    <div style="max-width:960px;margin:auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.12);">
 
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
 
        # Evaluate rules and build AI summary analysis if systemInstruction field shifted
        summary_html = ""
        for c in item["changes"]:
            if c["field"] == "systemInstruction":
                summary_text = generate_functional_summary(str(c["old"]), str(c["new"]))
                summary_html = f"""
                <div style="background: #f0f7ff; color: #1e3a8a; border: 1px solid #bfdbfe; border-left: 4px solid #3b82f6; padding: 14px 18px; margin-bottom: 16px; border-radius: 4px; font-size: 12px; line-height: 1.6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                  <strong style="font-size: 13px; color: #1e40af; display: block; margin-bottom: 4px;">🤖 Operational Change Summary (AI Evaluation)</strong>
                  <span style="color: #374151;">{summary_text}</span>
                </div>
                """
                break
 
        html += f"""
      <div style="margin:24px 30px 0;">
        <div style="background:{bg};color:{fg};padding:10px 16px;border-radius:6px 6px 0 0;font-weight:bold;font-size:13px;">
          [{icon}] Config #{item['configId']} &nbsp;|&nbsp; {item['type']} &nbsp;|&nbsp; {item['version']} &nbsp;|&nbsp; {event}
        </div>
        <div style="background:#fff; padding:18px; border:1px solid #ddd; border-top:none;">
          {summary_html}
          <table style="width:100%;border-collapse:collapse;border:1px solid #ddd;table-layout:fixed;">
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
    </div>
    """
 
    html += """
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
        print(f"[EMAIL] Connecting to smtp.gmail.com:465...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:  # Increased from 10 to 30 seconds
            print(f"[EMAIL] Connected. Attempting login...")
            server.login(SMTP_USER, SMTP_PASS)
            print(f"[EMAIL] Login successful. Sending email...")
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"[EMAIL] Alert sent → {', '.join(recipients)}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"[ERROR] SMTP Authentication failed")
        print(f"[ERROR] Code: {e.smtp_code}")
        print(f"[ERROR] Message: {e.smtp_error}")
        print(f"[ERROR] Fix: Check GMAIL_USER and GMAIL_APP_PASS secrets")
        return False
    except smtplib.SMTPServerDisconnected as e:
        print(f"[ERROR] SMTP server disconnected: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"[ERROR] SMTP error: {e}")
        print(f"[ERROR] Code: {getattr(e, 'smtp_code', 'N/A')}")
        return False
    except TimeoutError:
        print(f"[ERROR] Email timeout (30s) — SMTP server not responding")  # Updated error message
        return False
    except ConnectionError as e:
        print(f"[ERROR] Email connection error: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Email send failed: {e}")
        print(f"[ERROR] Type: {type(e).__name__}")
        return False
 
 
# MAIN POLL LOOP
def main():
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    run_context = f"GitHub Actions (run #{run_id})" if run_id != "local" else "local"
     
    print(f"[START] VertexWatch [{ENV_TARGET.upper()}] — {now_ist()}")
    print(f"[START] Context: {run_context}")
    print(f"[START] Endpoint: {GET_ALL_URL}")
 
    if not login():
        print(f"[FATAL] Cannot authenticate — check JKC_USERNAME / JKC_PASSWORD secrets")
        print(f"[FATAL] For 409 Conflict errors, verify:")
        print(f"        1. Workflow has concurrency control enabled")
        print(f"        2. Credentials are correct for '{ENV_TARGET}' environment")
        print(f"        3. No other workflow run is currently executing")
        sys.exit(1)
 
    snapshot     = load_snapshot()
    is_first_run = not snapshot
 
    if is_first_run:
        print("[SNAPSHOT] No existing snapshot — building baseline on first fetch")
    else:
        print(f"[SNAPSHOT] Loaded {len(snapshot)} configs from cache")
 
    # Poll once, retry once on failure
    for attempt in range(1, 3):
        poll_count = attempt
        now = now_ist()
        print(f"\n[POLL #{poll_count}] {now}")
 
        current = fetch_configs()
 
        if current is None:
            if attempt < 2:
                print("[WARN] Fetch failed — retrying...")
                time.sleep(5)  # Wait 5 seconds before retry
                return
            else:
                print("[ERROR] Fetch failed after retry — aborting")
                sys.exit(1)
 
        print(f"[POLL] Fetched {len(current)} configs (full detail)")
 
        if is_first_run:
            save_snapshot(current)
            snapshot     = current
            is_first_run = False
            print("[SNAPSHOT] Baseline established — no changes to report")
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
                    "runId":     run_id,
                }]
                append_log(log_entries)
 
                if sent:
                    # Only update snapshot if email was successfully sent
                    snapshot = current
                    save_snapshot(current)
                else:
                    print("[WARN] Email failed — snapshot NOT updated")
 
            else:
                print("[POLL] No changes detected")
 
        # Exit after successful poll
        print(f"\n[DONE] Run complete — poll successful")
        break
 
 
if __name__ == "__main__":
    main()
