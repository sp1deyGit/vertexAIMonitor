# VertexWatch
Real-time monitoring for Vertex AI OCR pipeline configurations.

## Overview
VertexWatch monitors Vertex AI configurations across four environments: dev, jkc-uat, jkc-prod, and prod. The monitoring runs automatically every 5 minutes, detects configuration changes, and sends email alerts with detailed change summaries.

---

## Features

### Monitoring
* Multi-environment tracking: Monitors EKA API (dev), JK Systems UAT (jkc-uat), JK Systems Production (jkc-prod), and EKA Production (prod).
* Change detection: Captures additions, modifications, and deletions.
* Field-level change tracking: Pinpoints exactly what was altered.
* Snapshot caching: Maintains caches per environment for accurate diffing.

### Alerting
* Email notifications: Delivered via Gmail.
* HTML formatted messages: Easy-to-read tables with color highlighting.
* Before/after comparisons: Clear view of what changed.
* Metadata included: Timestamps and environment details attached to every alert.

### Reliability
* Retry logic: Includes exponential backoff for failed requests.
* Comprehensive error logging: Detailed tracking of HTTP, Auth, and SMTP errors.
* Graceful error handling: Prevents minor network blips from crashing the workflow.
* Token refresh mechanism: Ensures uninterrupted authentication.

---

## Setup

### Prerequisites
* Python 3.11+
* GitHub repository with Actions enabled
* Gmail account with 2-Step Verification enabled

### Environment Configuration & Secrets
Add the following key-value pairs to your repository under Settings -> Secrets and variables -> Actions:

* DEV_USERNAME: Dev environment username (dev)
* DEV_PASSWORD: Dev environment password (dev)
* JKC_USERNAME: JKC username (jkc-uat, jkc-prod)
* JKC_PASSWORD: JKC password (jkc-uat, jkc-prod)
* PROD_USERNAME: Production username (prod)
* PROD_PASSWORD: Production password (prod)
* GMAIL_USER: Gmail address for alerts (Shared)
* GMAIL_APP_PASS: Gmail App Password - 16 characters (Shared)
* ALERT_EMAIL: Recipient email(s), comma-separated (Shared)

### Gmail Setup
1. Go to your Google Account -> Security.
2. Enable 2-Step Verification.
3. Navigate to App passwords.
4. Select Mail and Windows Computer (or custom name).
5. Copy the generated 16-character password.
6. Add this to your GitHub Secrets as GMAIL_APP_PASS.

---

## Getting Started

### File Structure
.github/workflows/
└── main.yml        # GitHub Actions workflow
monitor.py          # Monitoring script
requirements.txt    # Dependencies
README.md           # Documentation

### Running the Workflow
The workflow is scheduled to run automatically every 5 minutes. To trigger it manually:
1. Go to the Actions tab in your repository.
2. Click the VertexWatch workflow on the left sidebar.
3. Click "Run workflow" on the right side.
4. Select your branch and confirm by clicking "Run workflow".

### Viewing Results
* GitHub Actions Logs: Navigate to the Actions tab -> click the specific run -> expand the job to view detailed logs.
* Change Logs: Go to the workflow run page, scroll down to the Artifacts section, and download the change_log_{environment}.json files.

---

## Configuration

### Settings & Thresholds
* Polling Interval (POLL_INTERVAL): 10 seconds (Interval between configuration checks)
* Run Duration (RUN_DURATION): 120 seconds (Total duration the script runs per action)
* Data Retention (Change Logs): 500 latest entries retained per environment
* Data Retention (Snapshot Cache): Per-environment, updated only on a successful alert

### Timeout Settings
* Login/Token: 15 seconds
* Config Fetch: 10 seconds
* Groq API: 30-60 seconds
* Email: 10 seconds

### Monitored Fields
The script tracks changes across the following configuration fields:
* Top-Level Configuration: version, type, locationId, projectId, apiEndPoint, model, systemInstruction, userInstruction
* Generation Config: temperature, maxOutputTokens, topP, seed, thinkingConfig.thinkingBudget

---

## Email Alerts
When a change is detected, alerts include:
* Environment name and label
* Configuration ID, type, and version
* Change event type (MODIFIED, ADDED, REMOVED)
* Field-by-field before/after values
* HTML table format with color highlighting
* Timestamp of detection

---

## Troubleshooting

### 409 Conflict Error
Cause: Concurrent login attempts or rate limiting.
Solution: The workflow uses concurrency control to prevent simultaneous logins. The monitor automatically retries up to 3 times using exponential backoff.
Log Example: [ERROR] 409 Conflict detected [AUTH] Retrying in 10s (attempt 1/3)

### 401 Unauthorized Error
Cause: Invalid credentials for the target environment.
Solution: Verify username and password secrets are set correctly and map to the correct environment.
Log Example: [ERROR] 401 Unauthorized — Invalid credentials

### Email Not Sending
Cause: Missing or incorrect Gmail configuration.
Solution: Verify GMAIL_USER, GMAIL_APP_PASS (must be the 16-character app password), and ALERT_EMAIL secrets are set. Ensure 2-Step Verification is active.
Log Example: [ERROR] SMTP Authentication failed, [ERROR] Code: 535

### Timeout Errors
Cause: Slow network or unresponsive API servers.
Solution: Check network connectivity and ensure target API servers are accessible. Retries will trigger automatically.
Log Example: [ERROR] getAllConfigs timeout (10s)

### Connection Errors
Cause: Network issues, firewall rules, or unreachable API endpoints.
Solution: Verify API URLs and check network/firewall configurations.
Log Example: [ERROR] Connection error: Connection refused

---

## Error Logging
All API calls log comprehensive error information. Check GitHub Actions logs for complete details:
* HTTP Errors: Logs rate limits (HTTP 429) and other server responses.
* Network Errors: Logs connection refusals and timeouts.
* Authentication Errors: Logs invalid credentials (401) and access denials (403).
* SMTP Errors: Logs authentication failures and unexpected disconnects.

---

## Security
* Secure Storage: Secrets are stored securely in GitHub Actions.
* Log Sanitization: Credentials are never printed or leaked in action logs.
* Token Handling: API tokens are handled securely in memory.
* Email Security: Uses App Passwords rather than your primary Google password.
* Concurrency Control: Prevents race conditions.
* Data Privacy: No sensitive pipeline data is exposed in change logs.
