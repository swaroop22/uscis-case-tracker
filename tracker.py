import os
import json
import smtplib
import subprocess
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Configuration ---
CASE_NUMBER   = "IOE0936799005"
EMAIL_TO      = "swrp.vicky@gmail.com"
EMAIL_FROM    = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
STATUS_FILE   = "last_status.json"


def get_case_status_curl(case_number: str):
    """Use system curl to query the USCIS case status API."""
    url = "https://egov.uscis.gov/casestatus/mycasestatus.do"
    data = f"appReceiptNum={case_number}&caseStatusSearchBtn=CHECK+STATUS"
    cmd = [
        "curl", "-s", "-L",
        "-X", "POST",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-H", "Origin: https://egov.uscis.gov",
        "-H", "Referer: https://egov.uscis.gov/casestatus/landing.do",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H", "Cache-Control: no-cache",
        "-b", "cookiefile",
        "-c", "cookiefile",
        "--data", data,
        "--max-time", "30",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    html = result.stdout
    print(f"[DEBUG] curl exit code: {result.returncode}")
    print(f"[DEBUG] HTML length: {len(html)}")
    print(f"[DEBUG] First 500 chars: {html[:500]}")
    return html


def get_first_cookie(case_number: str):
    """Get a session cookie first from the landing page."""
    cmd = [
        "curl", "-s",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-c", "cookiefile",
        "--max-time", "20",
        "https://egov.uscis.gov/casestatus/landing.do"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print(f"[DEBUG] Landing page status: {result.returncode}, length: {len(result.stdout)}")


def parse_status_from_html(html: str):
    """Extract status title and description from USCIS HTML response."""
    if not html or len(html) < 100:
        return None, None

    # Check for Cloudflare block
    if "cloudflare" in html.lower() or "cf-ray" in html.lower() or "just a moment" in html.lower():
        print("[DEBUG] Cloudflare block detected")
        return "BLOCKED", "Cloudflare challenge page detected"

    # Try to extract status heading (h1 inside the result div)
    title_match = re.search(
        r'<div[^>]*class="[^"]*rows[^"]*"[^>]*>.*?<h1[^>]*>(.*?)</h1>',
        html, re.DOTALL
    )
    if not title_match:
        title_match = re.search(r'<h1[^>]*>([^<]{5,100})</h1>', html)

    desc_match = re.search(
        r'<div[^>]*class="[^"]*rows[^"]*"[^>]*>.*?<p>(.*?)</p>',
        html, re.DOTALL
    )
    if not desc_match:
        desc_match = re.search(r'<p[^>]*class="[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)

    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else None
    desc  = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()[:500] if desc_match else None

    print(f"[DEBUG] Parsed title: {title}")
    print(f"[DEBUG] Parsed desc: {desc}")
    return title, desc


def try_uscis_api(case_number: str):
    """Try the internal USCIS JSON API."""
    url = f"https://egov.uscis.gov/case-status/api/public/case-status/{case_number}"
    cmd = [
        "curl", "-s",
        "-H", "Accept: application/json, text/plain, */*",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", "Referer: https://egov.uscis.gov/casestatus/landing.do",
        "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H", "X-Requested-With: XMLHttpRequest",
        "--max-time", "20",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print(f"[DEBUG] API curl exit: {result.returncode}, body: {result.stdout[:300]}")
    if result.returncode != 0 or not result.stdout.strip():
        return None, None
    try:
        data = json.loads(result.stdout)
        # Expected: {"caseStatus": {"formType": ..., "currentCaseStatus": ..., "currentCaseStatusDescription": ...}}
        cs = data.get("caseStatus", data)
        title = cs.get("currentCaseStatus") or cs.get("receiptNumber") or str(cs)[:100]
        desc  = cs.get("currentCaseStatusDescription", "")[:500]
        return title, desc
    except Exception as e:
        print(f"[DEBUG] JSON parse error: {e}")
        return None, None


def load_last_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {}


def save_status(status: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f)


def send_email(subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print("[INFO] Email sent successfully.")


def main():
    print(f"[INFO] Starting USCIS tracker at {datetime.now().isoformat()}")
    print(f"[INFO] Case number: {CASE_NUMBER}")

    # Step 1: Try JSON API first
    title, desc = try_uscis_api(CASE_NUMBER)

    # Step 2: Fall back to HTML form POST with cookie session
    if not title:
        print("[INFO] JSON API failed, trying HTML form POST...")
        get_first_cookie(CASE_NUMBER)
        html = get_case_status_curl(CASE_NUMBER)
        title, desc = parse_status_from_html(html)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    if not title or title == "BLOCKED":
        subject = f"USCIS Tracker - Manual Check Needed ({now_str})"
        body = (
            f"Case Number: {CASE_NUMBER}\n"
            f"Check Time:  {now_str}\n\n"
            f"Automated fetch was blocked. Please check manually:\n"
            f"https://egov.uscis.gov/casestatus/landing.do\n\n"
            f"Debug info: title={title}, desc={desc}"
        )
        send_email(subject, body)
        print("[WARN] Sent fallback email.")
        return

    last = load_last_status()
    last_title = last.get("title", "")

    if title != last_title:
        subject = f"USCIS Status CHANGED: {title}"
        body = (
            f"Your USCIS case status has CHANGED!\n\n"
            f"Case Number: {CASE_NUMBER}\n"
            f"New Status:  {title}\n"
            f"Description: {desc}\n\n"
            f"Checked at:  {now_str}\n"
            f"Check online: https://egov.uscis.gov/casestatus/landing.do"
        )
        print(f"[INFO] Status CHANGED: {last_title!r} -> {title!r}")
    else:
        subject = f"USCIS Status Update: {title} ({now_str})"
        body = (
            f"Case Number: {CASE_NUMBER}\n"
            f"Current Status: {title}\n"
            f"Description: {desc}\n\n"
            f"Checked at: {now_str}\n"
            f"Check online: https://egov.uscis.gov/casestatus/landing.do"
        )
        print(f"[INFO] Status unchanged: {title!r}")

    send_email(subject, body)
    save_status({"title": title, "desc": desc, "checked_at": now_str})
    print("[INFO] Done.")


if __name__ == "__main__":
    main()
