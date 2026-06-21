# VertexWatch
*Real-time monitoring for Vertex AI OCR pipeline configurations.*

## Overview
**VertexWatch** monitors Vertex AI configurations across four environments: `dev`, `jkc-uat`, `jkc-prod`, and `prod`. The monitoring runs automatically every 5 minutes, detects configuration changes, and sends email alerts with detailed change summaries.

---

## Features

### Monitoring
* **Multi-environment tracking:** Monitors EKA API (`dev`), JK Systems UAT (`jkc-uat`), JK Systems Production (`jkc-prod`), and EKA Production (`prod`).
* **Change detection:** Captures additions, modifications, and deletions.
* **Field-level change tracking:** Pinpoints exactly what was altered.
* **Snapshot caching:** Maintains caches per environment for accurate diffing.

### Alerting
* **Email notifications:** Delivered via Gmail.
* **HTML formatted messages:** Easy-to-read tables with color highlighting.
* **Before/after comparisons:** Clear view of what changed.
* **Metadata included:** Timestamps and environment details attached to every alert.

### Reliability
* **Retry logic:** Includes exponential backoff for failed requests.
* **Comprehensive error logging:** Detailed tracking of HTTP, Auth, and SMTP errors.
* **Graceful error handling:** Prevents minor network blips from crashing the workflow.
* **Token refresh mechanism:** Ensures uninterrupted authentication.

---

## Setup

### Prerequisites
* Python 3.11+
* GitHub repository with Actions enabled
* Gmail account with 2-Step Verification enabled

### Environment Configuration & Secrets
Add the following key-value pairs to your repository under **Settings → Secrets and variables → Actions**:

| Secret Name | Target Environment | Description |
| :--- | :--- | :--- |
| `DEV_USERNAME` | `dev` | Dev environment username |
| `DEV_PASSWORD` | `dev` | Dev environment password |
| `JKC_USERNAME` | `jkc-uat`, `jkc-prod` | JKC username (UAT and Prod) |
| `JKC_PASSWORD` | `jkc-uat`, `jkc-prod` | JKC password (UAT and Prod) |
| `PROD_USERNAME` | `prod` | Production username |
| `PROD_PASSWORD` | `prod` | Production password |
| `GMAIL_USER` | *All (Shared)* | Gmail address for alerts |
| `GMAIL_APP_PASS` | *All (Shared)* | Gmail App Password (16 characters) |
| `ALERT_EMAIL` | *All (Shared)* | Recipient email(s), comma-separated |

### Gmail Setup
1. Go to your **Google Account → Security**.
2. Enable **2-Step Verification**.
3. Navigate to **App passwords**.
4. Select *Mail* and *Windows Computer* (or custom name).
5. Copy the generated 16-character password.
6. Add this to your GitHub Secrets as `GMAIL_APP_PASS`.

---

## Getting Started

### File Structure
```text
.github/workflows/
└── main.yml        # GitHub Actions workflow
monitor.py          # Monitoring script
requirements.txt    # Dependencies
README.md           # Documentation
