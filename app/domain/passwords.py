"""Password policy — pure, so the API and its tests share one definition.

Follows NIST SP 800-63B rather than composition rules: a minimum length, a hard
upper bound (bcrypt only reads the first 72 bytes and bcrypt>=5 rejects longer
input outright), and a block-list of passwords that fall to the first guesses of
any attack. The web client mirrors these rules for its live strength meter.
"""

from __future__ import annotations

from typing import Optional

MAX_BYTES = 72

# The most common leaked passwords (plus the obvious house-specific ones). Kept short
# on purpose: the length floor already rules out most of the usual top-100 lists.
COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password12", "password123", "passw0rd", "p@ssw0rd",
        "12345678", "123456789", "1234567890", "0123456789", "87654321", "11111111",
        "00000000", "12341234", "11223344", "123123123", "qwertyui", "qwerty123",
        "qwertyuiop", "1q2w3e4r", "1qaz2wsx", "zaq12wsx", "asdfghjk", "asdfasdf",
        "abcd1234", "abcdefgh", "iloveyou", "sunshine", "princess", "football",
        "baseball", "welcome1", "welcome123", "letmein1", "trustno1", "superman",
        "starwars", "whatever", "computer", "internet", "michael1", "jennifer",
        "dragon12", "monkey12", "shadow12", "master12", "admin123", "administrator",
        "changeme", "default1", "secret12", "secret123", "test1234", "testtest",
        "india123", "india@123", "bharat123", "mumbai123", "delhi123",
        "hive1234", "hivehive", "flatmate", "roommate",
    }
)


def problems(password: str, *, username: Optional[str] = None, min_length: int = 8) -> list[str]:
    """Every rule the password breaks, as user-facing sentences (empty = acceptable)."""
    issues: list[str] = []
    if len(password) < min_length:
        issues.append(f"Password must be at least {min_length} characters.")
    if len(password.encode("utf-8")) > MAX_BYTES:
        issues.append(f"Password must be at most {MAX_BYTES} bytes.")
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        issues.append("That password is too common — pick something less guessable.")
    elif password and len(set(password)) == 1:
        issues.append("Password can't be a single repeated character.")
    if username and len(username) >= 3 and username.strip().lower() in lowered:
        issues.append("Password can't contain your username.")
    return issues
