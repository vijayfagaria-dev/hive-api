"""Data-access layer: ORM queries only, one module per aggregate.

Repositories take an AsyncSession and never commit — the session's owner (the
request via get_session, or a session_scope) controls the transaction. Reads
return ORM entities or explicit Row tuples; entity mutations (status changes,
contact edits) are done by services on loaded entities and flushed by the session.
"""

_I64_MIN, _I64_MAX = -(2**63), 2**63 - 1


def fits_i64(value) -> bool:
    """A forged/garbage id (string from a tampered session, or an out-of-range
    int) is a clean miss, not an OverflowError/TypeError when bound to SQLite."""
    return isinstance(value, int) and _I64_MIN <= value <= _I64_MAX
