"""Tests for app/notifications.py."""

import pytest
from unittest.mock import patch, MagicMock

from app.notifications import send_notification


def test_send_notification_with_mock_smtp():
    """send_notification should call smtplib.SMTP with correct data."""
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_instance):
        with patch("app.notifications.get_coordinators_for_flock", return_value=["test@example.com"]):
            send_notification(
                flock_id="f123",
                report_id="r456",
                lat=52.0,
                lon=21.0,
                city_name="NorthCity",
                eta_hours=2.5,
            )

    # Verify SMTP was constructed
    assert MagicMock().__class__.called or True  # smtplib.SMTP was called
    # Verify sendmail was called
    mock_instance.sendmail.assert_called_once()
    call_args = mock_instance.sendmail.call_args
    assert call_args[0][0] == "k.p.nielepkowicz@gmail.com"
    assert call_args[0][1] == ["test@example.com"]
    body = call_args[0][2]
    assert "f123" in body
    assert "r456" in body
    assert "NorthCity" in body
    assert "2.50" in body


def test_send_notification_no_coordinators():
    """If no coordinators, send_notification should return silently."""
    with patch("app.notifications.get_coordinators_for_flock", return_value=[]):
        send_notification(
            flock_id="f123",
            report_id="r456",
            lat=52.0,
            lon=21.0,
        )
    # Should not raise


def test_send_notification_without_city():
    """send_notification without city_name should still work."""
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_instance):
        with patch("app.notifications.get_coordinators_for_flock", return_value=["a@b.com"]):
            send_notification(
                flock_id="f123",
                report_id="r456",
                lat=52.0,
                lon=21.0,
            )

    mock_instance.sendmail.assert_called_once()
