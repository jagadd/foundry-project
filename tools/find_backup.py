import os
import pyodbc
import json
from dotenv import load_dotenv

load_dotenv()

def find_latest_backup(database_name):
    """Find the most recent full backup for a database."""
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
        SELECT TOP 5
            bs.database_name,
            bs.backup_start_date,
            bs.backup_finish_date,
            CASE bs.type 
                WHEN 'D' THEN 'Full' 
                WHEN 'I' THEN 'Differential' 
                WHEN 'L' THEN 'Log' 
            END AS backup_type,
            bmf.physical_device_name,
            CAST(bs.backup_size / 1048576 AS BIGINT) AS backup_size_mb,
            CAST(bs.compressed_backup_size / 1048576 AS BIGINT) AS compressed_size_mb,
            bs.is_copy_only,
            bs.has_backup_checksums
        FROM msdb.dbo.backupset bs
        JOIN msdb.dbo.backupmediafamily bmf 
            ON bs.media_set_id = bmf.media_set_id
        WHERE bs.database_name = ?
            AND bs.type = 'D'
        ORDER BY bs.backup_finish_date DESC
    """, database_name)
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return json.dumps({
            "found": False,
            "message": f"No full backups found for '{database_name}'"
        }, indent=2)
    
    backups = []
    for row in rows:
        backups.append({
            "database": row[0],
            "start": str(row[1]),
            "finish": str(row[2]),
            "type": row[3],
            "path": row[4],
            "size_mb": row[5],
            "compressed_mb": row[6],
            "copy_only": bool(row[7]),
            "has_checksum": bool(row[8])
        })
    
    return json.dumps({
        "found": True,
        "total_backups": len(backups),
        "latest": backups[0],
        "all_recent": backups
    }, indent=2)

# Test it
if __name__ == "__main__":
    print("Finding backups for 'salesdb'...")
    print(find_latest_backup("salesdb"))
    
    print("\nFinding backups for 'fakedb' (should find nothing)...")
    print(find_latest_backup("fakedb"))
