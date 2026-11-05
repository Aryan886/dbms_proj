import psycopg

# Source timestamps are naive Asia/Kolkata wall-clock strings. With the session
# time zone set to Asia/Kolkata, Postgres interprets them correctly when cast
# to timestamptz, and date_trunc/::date work on IST calendar days.
SESSION_TZ = "Asia/Kolkata"


def connect(dsn: str, **kwargs) -> psycopg.Connection:
    conn = psycopg.connect(dsn, **kwargs)
    conn.execute(f"SET TIME ZONE '{SESSION_TZ}'")
    conn.commit()
    return conn
