import pyodbc

MI_SERVER = "2276259-azsqlmi-freetier.74acffc514f1.database.windows.net,1433"
MI_PWD = "994052@Aatukundi"

# Try both username formats
users = [
    "jaga_admin",                                # plain
    "jaga_admin@2276259-azsqlmi-freetier",       # with server suffix
]

for MI_USER in users:
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER=tcp:{MI_SERVER};"
        f"UID={MI_USER};"
        f"PWD={MI_PWD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    print(f"\nTrying user: {MI_USER}")
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        print(f"✅ Connected!\n   {version[:100]}...")
        cursor.execute("SELECT name FROM sys.databases ORDER BY name")
        dbs = [row[0] for row in cursor.fetchall()]
        print(f"   Databases: {', '.join(dbs)}")
        cursor.close()
        conn.close()
        break
    except Exception as e:
        print(f"❌ Failed: {e}")
