"""Email notifications for BirdTracker."""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .services import get_coordinators_for_flock
from .config import settings


def send_notification(
    flock_id: str,
    report_id: str,
    lat: float,
    lon: float,
    city_name: str | None = None,
    eta_hours: float | None = None,
) -> None:
    """Send email notification to all coordinators for *flock_id*.

    If no coordinators are found the function returns silently (no error).
    """
    coordinators = get_coordinators_for_flock(flock_id)
    if not coordinators:
        return

    subject = f"BirdTracker: New report for flock {flock_id[:8]}"

    body_lines = [
        f"Flock ID: {flock_id}",
        f"Report ID: {report_id}",
        f"Location: {lat:.4f}, {lon:.4f}",
    ]
    if city_name:
        body_lines.append(f"Predicted city: {city_name}")
    if eta_hours is not None:
        body_lines.append(f"ETA: {eta_hours:.2f} hours")

    body = "\n".join(body_lines)

    msg = MIMEMultipart()
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(coordinators)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, coordinators, msg.as_string())
    except Exception:
        # In production you'd log this; for now just swallow to keep
        # the API happy even if SMTP is misconfigured.
        pass
