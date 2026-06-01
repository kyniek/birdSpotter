"""Infrastructure connectivity tests."""

from pathlib import Path

import sqlite3


def test_sqlite():
    """SQLite should connect successfully."""
    conn = sqlite3.connect(":memory:")
    conn.execute("SELECT 1")
    conn.close()
    print("SQLite works.")


def test_mail():
    """Test SMTP connectivity."""
    import smtplib
    import yaml

    # Credentials from pass.yaml
    pass_file = Path(__file__).parent / "pass.yaml"
    with open(pass_file) as f:
        creds = yaml.safe_load(f)

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587
    EMAIL = creds["imap"]["user"]
    PASSWORD = creds["smtp"]["password"]

    if not EMAIL or not PASSWORD:
        print("SMTP credentials not set, skipping.")
        return

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL, PASSWORD)
        print("SMTP connection successful.")
        server.quit()
    except Exception as e:
        print(f"SMTP connection failed: {e}")


if __name__ == "__main__":
    print("BirdSpotter Infrastructure Tests")
    test_sqlite()
    test_mail()
