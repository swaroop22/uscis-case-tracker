# USCIS Case Status Tracker

Automated tracker for USCIS case **** — checks status every 5 hours and sends email notifications to **swrp.vicky@gmail.com**.

## Features
- Scrapes USCIS case status from the official website
- Sends HTML email notifications on every check
- Highlights when status **changes**
- Saves last known status to detect changes
- Runs automatically via GitHub Actions every 5 hours
- Supports manual trigger via GitHub Actions UI

## Setup Instructions

### 1. Add Gmail App Password
The tracker uses Gmail SMTP to send emails. You need a **Gmail App Password** (not your regular password).

1. Go to your Google Account → Security → 2-Step Verification → App passwords
2. Create a new app password for "Mail"
3. Copy the 16-character password

### 2. Add GitHub Secrets
Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Value |
|---|---|
| `EMAIL_FROM` | Your Gmail address (e.g., `yourname@gmail.com`) |
| `EMAIL_PASSWORD` | Your Gmail App Password (16-char) |

### 3. Enable GitHub Actions
Go to the **Actions** tab and enable workflows if prompted.

### 4. Run Manually (Optional)
Go to **Actions → USCIS Case Status Tracker → Run workflow** to trigger an immediate check.

## How It Works

```
GitHub Actions (every 5 hours)
        ↓
tracker.py runs
        ↓
Fetch status from egov.uscis.gov
        ↓
Compare with last_status.json
        ↓
Send email to swrp.vicky@gmail.com
        ↓
Save updated status to last_status.json
```

## Files

| File | Description |
|---|---|
| `tracker.py` | Main Python script |
| `requirements.txt` | Python dependencies |
| `.github/workflows/tracker.yml` | GitHub Actions workflow |
| `last_status.json` | Auto-generated: stores last status |

## Email Notifications
- **First run**: Sends current status
- **Status changed**: Highlights old vs new status
- **No change**: Sends periodic check-in email every 5 hours

## Case Information
- **Case Number**: IOE0936799005
- **Notification Email**: swrp.vicky@gmail.com
- **Check Frequency**: Every 5 hours (cron: `0 */5 * * *`)
