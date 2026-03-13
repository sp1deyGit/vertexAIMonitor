# VertexWatch
> Monitors Vertex AI configs on `api.dev.eka.io` and emails you the moment anything changes.
> Zero manual steps after setup — just push and forget.

---

## How it works

```
GitHub Actions (every 5 min)
  └── monitor.py starts
        └── Logs in → gets fresh bearer token
        └── Polls getAllConfigs every 30s for 4.5 minutes
        └── Diffs against last known snapshot
        └── Change detected → sends email alert instantly
        └── Saves updated snapshot for next run
  └── Loops again in 5 min
```

Net result: changes are detected within **30 seconds** of being made on the dashboard.

---

## One-time Setup (5 minutes)

### 1. Create a GitHub repo
```bash
git init
git add .
git commit -m "init vertexwatch"
git remote add origin https://github.com/YOUR_USERNAME/vertexwatch.git
git push -u origin main
```

### 2. Add Secrets
Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

Add all 6 secrets:

| Secret Name | Value |
|---|---|
| `VERTEX_USERNAME` | Your dashboard login email |
| `VERTEX_PASSWORD` | Your dashboard password |
| `EMAILJS_SERVICE_ID` | From emailjs.com → Email Services |
| `EMAILJS_TEMPLATE_ID` | Template with `{{to_email}}` `{{subject}}` `{{message}}` |
| `EMAILJS_PUBLIC_KEY` | From EmailJS → Account → General |
| `ALERT_EMAIL` | Where to send change alerts |

### 3. Update the login endpoint
Once you share the login API details, update this line in `monitor.py`:
```python
LOGIN_URL = "https://api.dev.eka.io/___LOGIN_PATH___"
```

### 4. Push
```bash
git push
```

GitHub Actions will pick up the workflow automatically. First run establishes the baseline snapshot. Every run after that diffs and alerts.

---

## Email Alert Example

```
VERTEXWATCH — CONFIG CHANGE ALERT
══════════════════════════════════════════════════════

Endpoint  : https://api.dev.eka.io/support/vertexAi/getAllConfigs
Timestamp : 2026-03-13 14:32:10
Changes   : 1 config(s) modified

────────────────────────────────────────
  Config ID : 4
  Version   : v1
  Type      : INVOICE_LINE_ITEM
  Event     : MODIFIED

  Field                                       Before                After
  ──────────────────────────────────────────  ────────────────────  ────────────────────
  generationConfig.temperature                1.5                   1.0
  model                                       abc                   gemini-2.5-flash
  systemInstruction                           old text              new text

══════════════════════════════════════════════════════
Sent by VertexWatch — GitHub Actions Monitor
```

---

## Files

| File | Purpose |
|---|---|
| `monitor.py` | Main script — login, poll, diff, alert |
| `requirements.txt` | Python deps (just `requests`) |
| `snapshot.json` | Persisted between runs via Actions cache |
| `.github/workflows/monitor.yml` | GitHub Actions workflow |

---

## ⚠️ One pending step
The **login endpoint URL and payload shape** need to be confirmed from DevTools.
Update `LOGIN_URL` in `monitor.py` and the `json={...}` payload in the `login()` function once known.
