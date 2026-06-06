import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

print("SQL Server 2025 VM (10.10.0.5)...")
conn = pyodbc.connect(
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={os.environ['SQLVM_SERVER']};"
    f"DATABASE=master;"
    f"UID=sa;"
    f"PWD=994052@Jaga;"
    f"TrustServerCertificate=yes;"
)
cursor = conn.cursor()

cursor.execute("SELECT @@VERSION")
print(f"✅ {cursor.fetchone()[0][:80]}...")

cursor.execute("SELECT name FROM sys.databases ORDER BY name")
print(f"   Databases: {', '.join([r[0] for r in cursor.fetchall()])}")

conn.close()
print("\n✅ SQL VM connectivity confirmed")
