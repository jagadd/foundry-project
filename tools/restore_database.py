"""
restore_database.py -- Restore a database on SQL Server 2025 VM from Azure Blob URL
Author: jagadeesan.vg@cognizant.com - 2276259

Uses RESTORE FROM URL with SAS credential.
Backup files are pushed from Azure SQL MI to Blob Storage.
"""
import pyodbc
import re
import json
import os
from dotenv import load_dotenv

load_dotenv()


def _get_connection():
    server = os.getenv("SQLVM_SERVER", "10.10.0.5")
    user = os.getenv("SQLVM_USER", "sa")
    pwd = os.getenv("SQLVM_PASSWORD")
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};UID={user};PWD={pwd};"
        f"TrustServerCertificate=yes;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, autocommit=True)


def _ensure_credential():
    """Create SAS credential on target SQL Server for RESTORE FROM URL."""
    blob_url = os.getenv("AZURE_BLOB_URL")
    sas_token = os.getenv("AZURE_SAS_TOKEN", "").lstrip("?")

    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        IF NOT EXISTS (
            SELECT 1 FROM sys.symmetric_keys
            WHERE name = '##MS_DatabaseMasterKey##'
        )
        BEGIN
            CREATE MASTER KEY ENCRYPTION BY PASSWORD = 'DbOps@Agent#2026!';
        END
    """)

    cursor.execute(f"""
        IF EXISTS (SELECT 1 FROM sys.credentials WHERE name = '{blob_url}')
            DROP CREDENTIAL [{blob_url}];
    """)

    cursor.execute(f"""
        CREATE CREDENTIAL [{blob_url}]
        WITH IDENTITY = 'SHARED ACCESS SIGNATURE',
        SECRET = '{sas_token}';
    """)

    cursor.close()
    conn.close()
    return True


def _list_blob_backups(db_name):
    """List .bak files in blob container matching db_name."""
    from azure.storage.blob import ContainerClient

    blob_url = os.getenv("AZURE_BLOB_URL")
    sas_token = os.getenv("AZURE_SAS_TOKEN", "").lstrip("?")
    container_url = f"{blob_url}?{sas_token}"
    client = ContainerClient.from_container_url(container_url)

    # Strip common target suffixes to get the base source DB name
    # e.g. "salesdb_Restored" -> "salesdb", "EnterpriseHR_Dev" -> "enterprisehr"
    base = re.sub(r'(_restored|_dev|_copy|_test)$', '', db_name.lower())

    backups = []
    for blob in client.list_blobs():
        name_lower = blob.name.lower()
        if name_lower.endswith(".bak") and base in name_lower:
            backups.append({
                "name": blob.name,
                "size_mb": round(blob.size / (1024 * 1024), 2),
                "last_modified": blob.last_modified.isoformat(),
            })

    backups.sort(key=lambda x: x["last_modified"], reverse=True)
    return backups


def restore_database(db_name, backup_path=None):
    """
    Restore a database from Azure Blob URL on the target SQL Server.

    Args:
        db_name:     Target database name for the restored DB.
        backup_path: Blob file name (e.g. salesdb_MI_Export_20260605_1649.bak).
                     If None, auto-discovers the latest .bak for db_name.

    Returns:
        Dict with status and details.
    """
    blob_url = os.getenv("AZURE_BLOB_URL")
    data_path = os.getenv(
        "SQL_DATA_PATH",
        r"D:\Program Files\Microsoft SQL Server\MSSQL17.MSSQLSERVER\MSSQL\DATA",
    )

    result = {"database": db_name}

    # Step 1: Find backup if not specified
    if not backup_path:
        try:
            backups = _list_blob_backups(db_name)
            if not backups:
                result["status"] = "FAILED"
                result["error"] = f"No .bak files found in blob for '{db_name}'"
                return result
            backup_path = backups[0]["name"]
            result["auto_selected_backup"] = backup_path
            result["backup_size_mb"] = backups[0]["size_mb"]
        except Exception as e:
            result["status"] = "FAILED"
            result["error"] = f"Failed to list blob backups: {str(e)}"
            return result

    backup_full_url = f"{blob_url}/{backup_path}"
    result["backup_url"] = backup_full_url

    try:
        # Step 2: Ensure SAS credential
        _ensure_credential()
        result["credential"] = "OK"

        conn = _get_connection()
        cursor = conn.cursor()

        # Step 3: Read logical file names
        cursor.execute(f"RESTORE FILELISTONLY FROM URL = '{backup_full_url}'")
        files = []
        for row in cursor.fetchall():
            files.append({
                "logical": row[0],
                "physical": row[1],
                "type": row[2],
            })

        if not files:
            result["status"] = "FAILED"
            result["error"] = "FILELISTONLY returned no files"
            cursor.close()
            conn.close()
            return result

        result["logical_files"] = files

        # Step 4: Build MOVE clauses
        move_clauses = []
        for f in files:
            logical = f["logical"]
            ftype = f["type"]
            if ftype == "D":
                dest = f"{data_path}\\{db_name}.mdf"
            elif ftype == "L":
                dest = f"{data_path}\\{db_name}_log.ldf"
            elif ftype == "S":
                dest = f"{data_path}\\{db_name}_XTP"
            else:
                dest = f"{data_path}\\{db_name}_{logical}"
            move_clauses.append(f"MOVE N'{logical}' TO N'{dest}'")

        # Step 5: Drop existing DB if present
        cursor.execute(f"""
            IF DB_ID('{db_name}') IS NOT NULL
            BEGIN
                ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
                DROP DATABASE [{db_name}];
            END
        """)

        # Step 6: Execute restore
        restore_sql = (
            f"RESTORE DATABASE [{db_name}] FROM URL = '{backup_full_url}' "
            f"WITH {', '.join(move_clauses)}, RECOVERY, REPLACE, STATS = 10"
        )
        result["restore_sql_preview"] = restore_sql[:300]

        cursor.execute(restore_sql)
        while cursor.nextset():
            pass

        # Step 7: Verify
        cursor.execute(
            f"SELECT state_desc FROM sys.databases WHERE name = '{db_name}'"
        )
        row = cursor.fetchone()
        result["db_state"] = row[0] if row else "UNKNOWN"
        result["status"] = "SUCCESS" if row and row[0] == "ONLINE" else "FAILED"

        cursor.close()
        conn.close()

    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)

    return result


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "salesdb_Restored"
    bak = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(restore_database(db, bak), indent=2))
