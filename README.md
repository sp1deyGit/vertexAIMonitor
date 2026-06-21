VertexWatch

Real-time monitoring for Vertex AI OCR pipeline configurations across dev, jkc-uat, jkc-prod, and prod environments.

Overview

VertexWatch monitors Vertex AI configurations every 5 minutes, detects changes, and sends email alerts with detailed change summaries.

Features


Multi-environment monitoring (dev, jkc-uat, jkc-prod, prod)
Change detection (additions, modifications, deletions)
Email notifications with HTML formatting
Field-level change tracking
Snapshot caching per environment
Change logs with timestamps
Retry logic with exponential backoff
Comprehensive error logging


File Structure

.github/workflows/
    └── main.yml              # GitHub Actions workflow
monitor.py                    # Monitoring script
requirements.txt              # Python dependencies
README.md                     # Documentation

Generated files (created at runtime):


snapshot_dev.json
snapshot_jkc_uat.json
snapshot_jkc_prod.json
snapshot_prod.json
change_log_dev.json
change_log_jkc_uat.json
change_log_jkc_prod.json
change_log_prod.json


Setup

Secrets Configuration

Configure these in Settings → Secrets and variables → Actions:


DEV_USERNAME - Dev environment username
DEV_PASSWORD - Dev environment password
JKC_USERNAME - JKC username (shared for UAT and Prod)
JKC_PASSWORD - JKC password (shared for UAT and Prod)
PROD_USERNAME - Production username
PROD_PASSWORD - Production password
GMAIL_USER - Gmail address for alerts
GMAIL_APP_PASS - Gmail App Password (16 characters)
ALERT_EMAIL - Recipient email(s) (comma-separated)


Gmail Setup


Go to Google Account → Security
Enable 2-Step Verification
Go to App passwords
Select Mail and Windows Computer
Copy the 16-character password
Add as GMAIL_APP_PASS secret


How It Works

The workflow runs every 5 minutes with these steps:


Authenticate to each environment
Fetch all configurations
Compare with previous snapshot
Detect changes
Send email alert if changes detected
Update snapshot and change log


Monitored Fields

Top-level fields:


version
type
locationId
projectId
apiEndPoint
model
systemInstruction
userInstruction


Generation config:


temperature
maxOutputTokens
topP
seed
thinkingConfig.thinkingBudget


Viewing Results

GitHub Actions Logs


Go to Actions tab
Click VertexWatch workflow
Click a run
Expand job to see detailed logs


Change Logs


Go to workflow run
Scroll to Artifacts section
Download change_log_{env}.json files


Email Alerts

Alerts include:


Environment label
Config ID, type, and version
Change event (MODIFIED, ADDED, REMOVED)
Before/after field values
HTML table format with highlighted changes


Configuration

POLL_INTERVAL = 10 seconds
RUN_DURATION = 120 seconds
Change log retention = 500 entries

Troubleshooting

409 Conflict Error


Concurrent login attempts or rate limiting
Workflow has concurrency control to prevent this
Monitor retries up to 3 times with exponential backoff


401 Unauthorized


Invalid credentials
Verify all username and password secrets
Check credentials are correct for each environment


Email Not Sending


Verify GMAIL_USER, GMAIL_APP_PASS, and ALERT_EMAIL secrets
Check 2-Step Verification is enabled on Gmail
Ensure Gmail App Password is used (not main password)


Timeout Errors


API servers not responding or slow network
Check network connectivity
Retries happen automatically


Error Logging

All API calls log detailed error information including:


HTTP status codes
API response bodies
Connection errors
Timeout errors
SMTP errors with codes


Check GitHub Actions logs for complete error details.

Security


Secrets stored in GitHub (not in code)
Credentials never logged
API tokens handled securely
Email uses Gmail App Password
Concurrency control prevents race conditions
