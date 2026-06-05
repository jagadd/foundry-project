import os
import pyodbc
import json
from dotenv import load_dotenv

load_dotenv()

def check_target_database(target_db_name):
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
    
    # Check if DB exists
    cursor.execute("""
        SELECT name, state_desc, create_date, 
               compatibility_level, recovery_model_desc
        FROM sys.databases WHERE name = ?
    """, target_db_name)
    
    db_row = cursor.fetchone()
    
    if not db_row:
        conn.close()
        return json.dumps({
            "exists": False,
            "active_connections": 0,
            "message": f"Database '{target_db_name}' does not exist on VM"
        }, indent=2)
    
    # Count active connections
    cursor.execute("""
        SELECT COUNT(*) FROM sys.dm_exec_sessions 
        WHERE database_id = DB_ID(?)
    """, target_db_name)
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

# Test it
if __name__ == "__main__":
    # Test with existing DB
    print("Test 1: Check 'salesdb' (exists)...")
    print(check_target_database("salesdb"))
    
    # Test with non-existing DB
    print("\nTest 2: Check 'salesdb_dev_copy' (should not exist)...")
    print(check_target_database("salesdb_dev_copy"))
