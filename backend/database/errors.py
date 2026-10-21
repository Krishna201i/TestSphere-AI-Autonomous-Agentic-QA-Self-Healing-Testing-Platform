"""
TestSphere-AI — Human-readable database connection errors.

Turns raw driver errors (psycopg / SQLAlchemy) into a short explanation of
the likely cause and fix.  Never includes the connection string or password.
"""

import re

_HINTS = [
    (re.compile(r"tenant/user .* not found|tenant or user not found", re.I),
     "Supabase rejected the database user. The project may be paused (free projects pause after inactivity — "
     "restore it in the Supabase dashboard), or DATABASE_URL has the wrong pooler host or project ref. "
     "Copy the Session pooler string from Supabase → Connect and set it as DATABASE_URL."),
    (re.compile(r"password authentication failed", re.I),
     "The database password in DATABASE_URL is wrong. Reset it in Supabase if needed, and URL-encode special "
     "characters (e.g. @ as %40)."),
    (re.compile(r"could not translate host name|name or service not known|nodename nor servname|getaddrinfo failed", re.I),
     "The database host in DATABASE_URL cannot be resolved. Check the hostname for typos."),
    (re.compile(r"timeout|timed out", re.I),
     "The database did not respond in time. Check the host/port and that the server allows connections."),
    (re.compile(r"connection refused", re.I),
     "The database refused the connection. Check the host and port in DATABASE_URL."),
    (re.compile(r"no such table|does not exist", re.I),
     "A database table is missing. Restart the backend so it can create its tables."),
]


def describe_db_error(exc: BaseException) -> str:
    text = str(getattr(exc, "orig", None) or exc)
    for pattern, hint in _HINTS:
        if pattern.search(text):
            return f"Database unavailable: {hint}"
    return "Database unavailable: the backend could not reach its database (check DATABASE_URL and the database server)."
