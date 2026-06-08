import os
import sys
from dotenv import load_dotenv
from azure.storage.blob import BlobClient
import pyodbc

def get_backup_blob_size(blob_url: str, sas_token: str) -> int:
    # blob_url example: https://account.blob.core.windows.net/container/backup.bak
    # Extract container and blob name from URL
    # Simplify by requiring full blob URL + SAS token
    try:
        blob_client = BlobClient(blob_url + sas_token)
        props = blob_client.get_blob_properties()
        return props.size
    except Exception as e:
        print(f"Failed to get blob size: {str(e)}", file=sys.stderr)
        return -1

def get_sql_vm_free_space(server: str, database: str, username: str, password: str, threshold_bytes: int) -> int:
    try:
        conn_str = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            # Query free space on the drive where SQL DATA files reside
            # Assuming default drive, querying free space using xp_fixeddrives
            cursor.execute("EXEC xp_fixeddrives")
            drives = cursor.fetchall()  # [(drive_letter, free_space_in_MB), ...]
            # Simplified: sum all free space on all drives
            total_free_mb = sum(row[1] for row in drives)
            return total_free_mb * 1024 * 1024
    except Exception as e:
        print(f"Failed to get SQL VM free disk space: {str(e)}", file=sys.stderr)
        return -1

def main():
    load_dotenv()

    blob_url = os.getenv("AZURE_BLOB_URL")
    sas_token = os.getenv("AZURE_SAS_TOKEN")
    sql_server = os.getenv("SQLVM_SERVER")
    sql_database = os.getenv("SQL_DATABASE", "master")
    sql_username = os.getenv("SQL_USERNAME")
    sql_password = os.getenv("SQL_PASSWORD")
    if not all([blob_url, sas_token, sql_server, sql_username, sql_password]):
        print("Missing required environment variables", file=sys.stderr)
        sys.exit(1)

    backup_size = get_backup_blob_size(blob_url, sas_token)
    if backup_size < 0:
        print("Error retrieving backup blob size, cannot proceed.", file=sys.stderr)
        sys.exit(1)

    free_space = get_sql_vm_free_space(sql_server, sql_database, sql_username, sql_password, backup_size * 3 // 2)
    if free_space < 0:
        print("Error retrieving SQL VM free disk space, cannot proceed.", file=sys.stderr)
        sys.exit(1)

    required_space = backup_size * 3 // 2

    if free_space >= required_space:
        print(f"Sufficient disk space available: {free_space} bytes free, {required_space} bytes required.")
        sys.exit(0)
    else:
        print(f"Insufficient disk space: {free_space} bytes free, {required_space} bytes required.", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()