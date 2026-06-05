import os
import pyodbc
import json
from dotenv import load_dotenv

load_dotenv()

def check_disk_space():
    """Check available disk space on target SQL Server VM."""
    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.environ['SQLVM_SERVER']};"
        f"DATABASE=master;"
        f"UID=sa;"
        f"PWD={os.environ['SQLVM_PASSWORD']};"
        f"TrustServerCertificate=yes;"
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT
            vs.volume_mount_point AS drive,
            CAST(vs.total_bytes/1048576 AS BIGINT) AS total_mb,
            CAST(vs.available_bytes/1048576 AS BIGINT) AS free_mb,
            CAST(vs.available_bytes * 100.0 / vs.total_bytes AS DECIMAL(5,2)) AS free_pct
        FROM sys.master_files mf
        CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) vs
    """)
    
    drives = []
    for row in cursor.fetchall():
        drives.append({
            "drive": row[0].strip(),
            "total_mb": row[1],
            "free_mb": row[2],
            "free_pct": float(row[3])
        })
    conn.close()
    return json.dumps({"drives": drives}, indent=2)

# Test it
if __name__ == "__main__":
    print("Checking disk space on SQL VM (10.10.0.5)...")
    result = check_disk_space()
    print(result)
