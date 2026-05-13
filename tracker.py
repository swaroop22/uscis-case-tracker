import os
import json
import smtplib
import re
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import cloudscraper
from bs4 import BeautifulSoup

# ---------------- CONFIG ----------------

CASE_NUMBER = "IOE0936799005"

EMAIL_TO = "swrp.vicky@gmail.com"

EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

STATUS_FILE = "last_status.json"

BASE_URL = "https://egov.uscis.gov"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------- SESSION ----------------

scraper = cloudscraper.create_scraper(
    browser={
        "browser": "chrome",
        "platform": "darwin",
        "mobile": False
    }
)

scraper.headers.update(HEADERS)

# ---------------- HELPERS ----------------


def load_last_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_status(status):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def send_email(subject, body):
    msg = MIMEMultipart()

    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(
            EMAIL_FROM,
            EMAIL_TO,
            msg.as_string()
        )

    print("[INFO] Email sent")


# ---------------- USCIS FETCH ----------------


def get_case_status(case_number):
    """
    Fetch USCIS status page using Cloudflare-aware session.
    """

    landing_url = f"{BASE_URL}/casestatus/landing.do"

    print("[INFO] Opening landing page...")

    # establish session cookies
    scraper.get(landing_url, timeout=30)

    time.sleep(2)

    post_url = f"{BASE_URL}/casestatus/mycasestatus.do"

    payload = {
        "appReceiptNum": case_number,
        "caseStatusSearchBtn": "CHECK STATUS"
    }

    print("[INFO] Posting case request...")

    response = scraper.post(
        post_url,
        data=payload,
        timeout=45
    )

    html = response.text

    print(f"[DEBUG] HTTP: {response.status_code}")
    print(f"[DEBUG] HTML length: {len(html)}")

    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"

    lower_html = html.lower()

    blocked_keywords = [
        "cf-ray",
        "cloudflare",
        "attention required",
        "just a moment",
        "captcha"
    ]

    if any(x in lower_html for x in blocked_keywords):
        return "BLOCKED", "Cloudflare challenge detected"

    return parse_html(html)


def parse_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # USCIS result container
    rows = soup.find("div", class_="rows text-center")

    if not rows:
        rows = soup

    h1 = rows.find("h1")
    p = rows.find("p")

    title = h1.get_text(strip=True) if h1 else None
    desc = p.get_text(" ", strip=True) if p else None

    if desc:
        desc = desc[:1000]

    print(f"[DEBUG] TITLE: {title}")
    print(f"[DEBUG] DESC: {desc}")

    return title, desc


# ---------------- MAIN ----------------


def main():

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    print(f"[INFO] Checking {CASE_NUMBER}")

    try:
        title, desc = get_case_status(CASE_NUMBER)

    except Exception as e:
        title = None
        desc = str(e)

    if not title or title == "BLOCKED":

        subject = f"USCIS Manual Check Needed - {CASE_NUMBER}"

        body = (
            f"Case Number: {CASE_NUMBER}\n"
            f"Check Time: {now_str}\n\n"
            f"Automated fetch failed.\n\n"
            f"Reason:\n{desc}\n\n"
            f"Manual Check:\n"
            f"https://egov.uscis.gov/casestatus/landing.do\n"
        )

        send_email(subject, body)

        print("[WARN] Blocked or failed")
        return

    last = load_last_status()

    old_title = last.get("title")

    changed = old_title != title

    if changed:
        subject = f"USCIS STATUS CHANGED: {title}"
    else:
        subject = f"USCIS Status Update: {title}"

    body = (
        f"Case Number: {CASE_NUMBER}\n\n"
        f"Status: {title}\n\n"
        f"Description:\n{desc}\n\n"
        f"Checked At: {now_str}\n\n"
        f"USCIS:\n"
        f"https://egov.uscis.gov/casestatus/landing.do\n"
    )

    send_email(subject, body)

    save_status({
        "title": title,
        "desc": desc,
        "checked_at": now_str
    })

    print("[INFO] Done")


if __name__ == "__main__":
    main()
