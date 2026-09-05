import psycopg2

passwords = [
    "Admin20221013",
    "A993412ymj,,.",
    "mysecretpassword",
    "admin20221013",
    "admin2022",
    "postgres",
    "123456"
]

print("Testing PostgreSQL passwords on 192.168.124.18:45869...")

working_pass = None
for pw in passwords:
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user="postgres",
            password=pw,
            host="192.168.124.18",
            port=45869,
            connect_timeout=3
        )
        print(f"  --> MATCH FOUND! Working Password is: '{pw}'")
        working_pass = pw
        conn.close()
        break
    except Exception as e:
        print(f"  Failed for '{pw}': {e}")

if working_pass:
    print(f"\nSUCCESS! Valid DSN password identified: {working_pass}")
else:
    print("\nNo matching password found in candidate list.")
