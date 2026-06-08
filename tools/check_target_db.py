
import os
import pyodbc
import json
from dotenv import load_dotenv

load_dotenv()


def check_target_database(target_db_name):
    #raise Exception("SIMULATED: SQL Server connection refused")
    """Check if database exists on target VM and count active connections."""
    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={os.environ['SQLVM_SERVER']};"
        f"DATABASE=master;"
        f"UID=sa;"
        f"PWD={os.environ['SQLVM_PASSWORD']};"
        f"TrustServerCertificate=yes;"
    )
    cursor = conn.cursor()

    # Check if DB exists (case-insensitive)
    cursor.execute("""
        SELECT
            name,
            state_desc,
            create_date,
            compatibility_level,
            recovery_model_desc
        FROM sys.databases
        WHERE name COLLATE SQL_Latin1_General_CP1_CI_AS =
              ? COLLATE SQL_Latin1_General_CP1_CI_AS
    """, target_db_name)

    db_row = cursor.fetchone()

    if not db_row:
        conn.close()
        return json.dumps({
            "exists": False,
            "active_connections": 0,
            "message": f"Database '{target_db_name}' does not exist on VM"
        }, indent=2)

    # Count active connections using the canonical DB name returned by SQL Server
    canonical_db_name = db_row[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM sys.dm_exec_sessions
        WHERE database_id = DB_ID(?)
    """, canonical_db_name)

    active = cursor.fetchone()[0]

    conn.close()
    return json.dumps({
        "exists": True,
        "name": db_row[0],
        "state": db_row[1],
        "created": str(db_row[2]),
        "compatibility_level": db_row[3],
        "recovery_model": db_row[4],
        "active_connections": active
    }, indent=2)


if __name__ == "__main__":
    print("Test 1: Check 'EnterpriseHR'...")
    print(check_target_database("EnterpriseHR"))

    print("\nTest 2: Check 'enterprisehr'...")
    print(check_target_database("enterprisehr"))

    print("\nTest 3: Check 'salesdb_dev_copy'...")
    print(check_target_database("salesdb_dev_copy"))
