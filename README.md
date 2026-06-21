VertexWatch

Real-time monitoring for Vertex AI OCR pipeline configurations.


Overview

VertexWatch monitors Vertex AI configurations across four environments:


dev (EKA API)
jkc-uat (JK Systems UAT)
jkc-prod (JK Systems Production)
prod (EKA Production)


The monitoring runs every 5 minutes, detects configuration changes, and sends email alerts with detailed change summaries.


Features

Monitoring


Multi-environment tracking (dev, jkc-uat, jkc-prod, prod)
Change detection (additions, modifications, deletions)
Field-level change tracking
Snapshot caching per environment


Alerting


Email notifications via Gmail
HTML formatted messages
Before/after comparison tables
Timestamp and metadata included


Reliability


Retry logic with exponential backoff
Comprehensive error logging
Graceful error handling
Token refresh mechanism



Setup

Prerequisites


Python 3.11+
GitHub repository with Actions enabled
Gmail account with 2-Step Verification


Secrets Configuration

Add these to GitHub Settings → Secrets and variables → Actions:

DEV_USERNAME        # Dev environment username
DEV_PASSWORD        # Dev environment password
JKC_USERNAME        # JKC username (UAT and Prod)
JKC_PASSWORD        # JKC password (UAT and Prod)
PROD_USERNAME       # Production username
PROD_PASSWORD       # Production password
GMAIL_USER          # Gmail address for alerts
GMAIL_APP_PASS      # Gmail App Password (16 characters)
ALERT_EMAIL         # Recipient email(s), comma-separated

Gmail Setup


Go to Google Account → Security
Enable 2-Step Verification
Navigate to App passwords
Select Mail and Windows Computer
Copy the 16-character password
Add as GMAIL_APP_PASS secret



Getting Started

File Structure

.github/workflows/
    └── main.yml                  # GitHub Actions workflow
monitor.py                        # Monitoring script
requirements.txt                  # Dependencies
README.md                         # Documentation

Running the Workflow

The workflow runs automatically every 5 minutes. To run manually:


Go to Actions tab
Click VertexWatch workflow
Click "Run workflow"
Select branch and click "Run workflow"


Viewing Results

GitHub Actions Logs:


Go to Actions tab
Click VertexWatch workflow
Click the run you want to check
Expand job to view detailed logs


Change Logs:


Go to the workflow run page
Scroll to Artifacts section
Download change_log_{environment}.json files



Configuration

Polling Settings:

POLL_INTERVAL = 10 seconds (interval between checks)
RUN_DURATION = 120 seconds (total run duration)

Data Retention:

Change log retention: 500 latest entries per environment
Snapshot caching: Per-environment, updated on successful alert

Timeout Settings:

Login/Token: 15 seconds
Config Fetch: 10 seconds
Groq API: 30-60 seconds
Email: 10 seconds


Monitored Fields

Top-Level Configuration


version
type
locationId
projectId
apiEndPoint
model
systemInstruction
userInstruction


Generation Config


temperature
maxOutputTokens
topP
seed
thinkingConfig.thinkingBudget



Email Alerts

Alert messages include:


Environment name and label
Configuration ID, type, and version
Change event type (MODIFIED, ADDED, REMOVED)
Field-by-field before/after values
HTML table format with color highlighting
Timestamp of detection



Troubleshooting

409 Conflict Error

Cause: Concurrent login attempts or rate limiting

Solution:


Workflow has concurrency control to prevent simultaneous logins
Monitor automatically retries up to 3 times
Uses exponential backoff between retries


[ERROR] 409 Conflict detected
[AUTH] Retrying in 10s (attempt 1/3)

401 Unauthorized Error

Cause: Invalid credentials for the environment

Solution:


Verify username and password secrets are set
Check credentials are correct for each environment
Ensure secrets match the target environment


[ERROR] 401 Unauthorized — Invalid credentials

Email Not Sending

Cause: Missing or incorrect Gmail configuration

Solution:


Verify GMAIL_USER secret is set
Verify GMAIL_APP_PASS is the 16-character app password
Verify ALERT_EMAIL recipient is set
Ensure 2-Step Verification is enabled on Gmail account


[ERROR] SMTP Authentication failed
[ERROR] Code: 535

Timeout Errors

Cause: Slow network or unresponsive API servers

Solution:


Check network connectivity
Verify target API servers are accessible
Retries happen automatically


[ERROR] getAllConfigs timeout (10s)

Connection Errors

Cause: Network issues or API endpoint not reachable

Solution:


Verify network connectivity
Check firewall rules
Verify API endpoint URLs are correct


[ERROR] Connection error: Connection refused


Error Logging

All API calls log comprehensive error information:

HTTP Errors:

[ERROR] HTTP 429 error
[ERROR] Response: {"error": "rate_limited"}

Network Errors:

[ERROR] Connection error: Connection refused
[ERROR] Timeout (10s): API server not responding

Authentication Errors:

[ERROR] 401 Unauthorized — Invalid credentials
[ERROR] 403 Forbidden — Access denied

SMTP Errors:

[ERROR] SMTP Authentication failed
[ERROR] Server disconnected unexpectedly

Check GitHub Actions logs for complete error details.


Security


Secrets are stored securely in GitHub
Credentials are never printed in logs
API tokens are handled securely
Gmail authentication uses App Password (not main password)
Concurrency control prevents race conditions
No sensitive data in change logs



Environment Configuration

dev - Uses DEV_USERNAME and DEV_PASSWORD

jkc-uat - Uses JKC_USERNAME and JKC_PASSWORD

jkc-prod - Uses JKC_USERNAME and JKC_PASSWORD

prod - Uses PROD_USERNAME and PROD_PASSWORD

Email configuration is shared across all environments:

GMAIL_USER, GMAIL_APP_PASS, ALERT_EMAIL
