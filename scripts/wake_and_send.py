"""Open the live app with ?hourly=run so it sends the production e-mail.

Run by GitHub Actions: on the hourly schedule (backup) and, for exact times, when
cron-job.org starts the workflow a few minutes before the hour (7:54, 8:54 IST).
Needs no secrets: the app uses its own Streamlit secrets.

Steps: 1) open the app and wake it if Streamlit Cloud put it to sleep;
2) if it is just before an hour (minute >= 45 IST), wait until hh:00:00;
3) open ?hourly=run and print the app's answer. So the mail leaves at hh:00.

    python scripts/wake_and_send.py [app_url]
"""
import sys
import time
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else "https://indent-salesapp.streamlit.app").rstrip("/")
MARK = "HOURLY-RESULT:"
WAKE = "get this app back up"
IST = timezone(timedelta(hours=5, minutes=30))


def _texts(page):
    for frame in page.frames:
        try:
            yield frame, frame.inner_text("body", timeout=2_000)
        except Exception:  # noqa: BLE001 - frame still loading
            continue


def _wake(page) -> None:
    """Open the app and wait until it is up (click 'wake' if it sleeps)."""
    page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
    end, woke = time.time() + 240, False
    while time.time() < end:
        for frame, text in _texts(page):
            low = text.lower()
            if not woke and WAKE in low:
                frame.get_by_role("button").filter(has_text="back up").first.click()
                print("App was asleep: waking it up")
                woke = True
            elif "mt indent" in low or "sign in" in low:
                print("App is up")
                return
        time.sleep(3)
    print("App did not come up within 4 minutes; trying anyway")


def _wait_for_the_hour() -> None:
    now = datetime.now(IST)
    if now.minute >= 45:
        target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        secs = (target - now).total_seconds()
        print(f"Waiting {secs:.0f}s until {target:%H:%M} IST")
        time.sleep(secs)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _wake(page)
        _wait_for_the_hour()
        print(f"Sending at {datetime.now(IST):%H:%M:%S} IST")
        page.goto(f"{URL}/?hourly=run", wait_until="domcontentloaded", timeout=120_000)
        end, woke = time.time() + 300, False
        while time.time() < end:
            for frame, text in _texts(page):
                if MARK in text:
                    line = next(ln for ln in text.splitlines() if MARK in ln)
                    print(line)
                    browser.close()
                    return 1 if ("failed" in line or " error " in f" {line} ") else 0
                if not woke and WAKE in text.lower():
                    frame.get_by_role("button").filter(has_text="back up").first.click()
                    woke = True
            time.sleep(3)
        print("No answer from the app within 5 minutes")
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
