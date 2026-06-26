"""Shared response mappers used by more than one resource."""

from __future__ import annotations


def overturn_out(stat: dict) -> dict:
    return {
        "name": stat["name"],
        "filed": stat["filed"],
        "upheld": stat["upheld"],
        "overturned": stat["overturned"],
        "overturnRate": stat["overturn_rate"],
    }
