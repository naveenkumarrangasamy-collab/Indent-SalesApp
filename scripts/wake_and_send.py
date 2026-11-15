"""Open the live app with ?hourly=run so it sends this hour's indent e-mail.

Run by GitHub Actions every hour 8 AM-2 PM IST. Needs no secrets: the app uses
its own Streamlit secrets. Wakes the app if Streamlit Cloud put it to sleep.

    python scripts/wake_and_send.py [app_url]
"""
import sys
import time

from playwright.sync_api import sync_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else "https://indent-salesapp.streamlit.app").rstrip("/")
MARK = "HOURLY-RESULT:"
WAKE = "get this app back up"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{URL}/?hourly=run", wait_until="domcontentloaded", timeout=120_000)
        end = time.time() + 300
        woke = False
        while time.time() < end:
            for frame in page.frames:
                try:
                    text = frame.inner_text("body", timeout=2_000)
                except Exception:  # noqa: BLE001 - frame still loading
                    continue
                if MARK in text:
                    line = next(ln for ln in text.splitlines() if MARK in ln)
                    print(line)
                    browser.close()
                    return 1 if ("failed" in line or " error " in f" {line} ") else 0
                if not woke and WAKE in text.lower():
                    frame.get_by_role("button").filter(has_text="back up").first.click()
                    print("App was asleep: waking it up")
                    woke = True
            time.sleep(5)
        print("No answer from the app within 5 minutes")
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
