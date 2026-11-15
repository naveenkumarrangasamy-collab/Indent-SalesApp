"""Send the hourly indent e-mail (run by GitHub Actions every hour 8 AM-2 PM IST).

    python scripts/hourly_mail.py            # this hour's e-mails (skips outside 8-2 / if already sent)
    python scripts/hourly_mail.py --force    # send now regardless

Reads the same settings as the app from .streamlit/secrets.toml (the workflow
writes that file from the STREAMLIT_SECRETS repository secret).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core import hourly  # noqa: E402


def main() -> int:
    results = hourly.run(force="--force" in sys.argv)
    for r in results:
        print(f"{r['status']:8} {r['to']:40} {r.get('detail', '')}")
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
