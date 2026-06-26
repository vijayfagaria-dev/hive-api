"""Notification contracts."""

from __future__ import annotations


def notification_out(notification) -> dict:
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "fineId": notification.fine_id,
        "read": bool(notification.read),
        "ts": notification.ts,
    }
