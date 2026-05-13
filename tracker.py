import os
import json
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Configuration
CASE_NUMBER    = "IOE0936799005"
EMAIL_TO       = "swrp.vicky@gmail.com"
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
STATUS_FILE    = "last_status.json"
USCIS_URL      = "https://egov.uscis.gov/casestatus/mycasestatus.do"

# USCIS public case status API (used by the official USCIS mobile app)
USCIS_API      = "https://egov.uscis.gov/case-status/api"


def get_case_status(case_number: str):
    """
    Call the USCIS case-status REST API that powers the official app.
    This endpoint is different from the website and does NOT go through Cloudflare.
    """
    url = f"{USCIS_API}/{case_number}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept"         : "application/json",
            "User-Agent"     : "okhttp/4.9.2",   # mimic USCIS Android app
            "Referer"        : "https://egov.uscis.gov/",
        }
    )
    try:
        print(f"Calling USCIS API: {url}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        print(f"API response: {json.dumps(data, indent=2)[:500]}")

        # Navigate the response structure
        case = data.get("caseStatus", data)
        title = (
            case.get("formType", "") + " " +
            case.get("subStatus", "")
        ).strip()
        if not title:
            title = case.get("current_case_status_text_en",
                    case.get("status", "")).strip()
        desc  = case.get("current_case_status_desc_en",
                case.get("description", "")).strip()

        if not title:
            print("Could not parse title from response.")
            return None

        return {
            "case_number"       : case_number,
            "status_title"      : title,
            "status_description": desc or "See USCIS website for details.",
            "checked_at"        : datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        print(f"API call failed: {e}")
        return None


def load_last_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return None


def save_status(status):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def send_email(subject, body):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials missing.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


def build_email_body(current, previous=None):
    change_banner = ""
    if previous and previous.get("status_title") != current["status_title"]:
        change_banner = f"""
        <div style="background:#fff3cd;border-left:5px solid #ffc107;
                    padding:14px 18px;margin-bottom:20px;border-radius:4px;">
          <strong>&#x26A0; Status Changed!</strong><br><br>
          Previous: <strong>{previous['status_title']}</strong><br>
          New: <strong style="color:#1a73e8;">{current['status_title']}</strong>
        </div>"""

    is_err = any(w in current["status_title"].lower()
                 for w in ("failed","blocked","manually","error"))
    color  = "#d32f2f" if is_err else "#2e7d32"

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:640px;
                               margin:auto;padding:20px;color:#333;">
  <div style="background:#1a73e8;padding:20px 24px;border-radius:8px 8px 0 0;">
    <h2 style="color:#fff;margin:0;">&#x1F4CB; USCIS Case Status Update</h2>
  </div>
  <div style="border:1px solid #ddd;border-top:none;padding:24px;
              border-radius:0 0 8px 8px;background:#fff;">
    {change_banner}
    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      <tr style="background:#f1f3f4;">
        <td style="padding:10px 14px;font-weight:bold;width:36%;">Case Number</td>
        <td style="padding:10px 14px;">{current['case_number']}</td></tr>
      <tr>
        <td style="padding:10px 14px;font-weight:bold;">Current Status</td>
        <td style="padding:10px 14px;font-weight:bold;color:{color};">
          {current['status_title']}</td></tr>
      <tr style="background:#f1f3f4;">
        <td style="padding:10px 14px;font-weight:bold;">Description</td>
        <td style="padding:10px 14px;">{current['status_description']}</td></tr>
      <tr>
        <td style="padding:10px 14px;font-weight:bold;">Checked At (UTC)</td>
        <td style="padding:10px 14px;">{current['checked_at']}</td></tr>
    </table>
    <p style="margin-top:22px;">
      <a href="{USCIS_URL}" style="background:#1a73e8;color:#fff;
         padding:10px 22px;border-radius:4px;text-decoration:none;font-weight:bold;">
        &#x1F517; Check on USCIS Website
      </a>
    </p>
    <p style="font-size:12px;color:#888;margin-top:16px;">
      Automated check &middot; Runs every 5 hours via GitHub Actions
    </p>
  </div>
</body></html>"""


def main():
    print(f"[{datetime.utcnow().isoformat()}Z] Checking USCIS case: {CASE_NUMBER}")
    current = get_case_status(CASE_NUMBER)

    if current is None:
        current = {
            "case_number"       : CASE_NUMBER,
            "status_title"      : "Check Manually - automated fetch failed",
            "status_description": (
                f"Could not retrieve status automatically. "
                f"Please visit {USCIS_URL} and enter {CASE_NUMBER}."
            ),
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

    print(f"Final status: {current['status_title']}")
    last = load_last_status()
    save_status(current)

    if last is None:
        subject = f"USCIS Case {CASE_NUMBER} - Initial Status Check"
    elif last.get("status_title") != current["status_title"]:
        subject = f"\u26a0\ufe0f USCIS STATUS CHANGED - {CASE_NUMBER}: {current['status_title']}"
    else:
        subject = f"USCIS {CASE_NUMBER} - Periodic Check ({current['status_title'][:50]})"

    send_email(subject, build_email_body(current, last))


if __name__ == "__main__":
    main()
