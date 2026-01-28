import psycopg2


def main() -> None:
    dsn = "postgresql://postgres:2026-d@localhost:5432/postgres"
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'attendance'::regclass
              AND contype = 'c'
            ORDER BY conname;
            """
        )
        rows = cur.fetchall()
        for name, definition in rows:
            print(f"{name}: {definition}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

