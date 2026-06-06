import os
import pyodbc
from azure.storage.blob import BlobClient
from dotenv import load_dotenv

load_dotenv()

AZURE_BLOB_URL = os.getenv('AZURE_BLOB_URL')
AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
SQLVM_SERVER = os.getenv('SQLVM_SERVER')
SQLVM_DATABASE = 'master'
SQLVM_USERNAME = os.getenv('SQLVM_USERNAME')
SQLVM_PASSWORD = os.getenv('SQLVM_PASSWORD')

class BackupValidationError(Exception):
    pass

def get_backup_file_header(backup_url: str) -> dict:
    """
    Connect to SQL Server and run RESTORE HEADERONLY from URL to get backup metadata.
    """
    conn_str = (
        f'DRIVER={{ODBC Driver 18 for SQL Server}};'
        f'SERVER={SQLVM_SERVER};DATABASE={SQLVM_DATABASE};'
        f'UID={SQLVM_USERNAME};PWD={SQLVM_PASSWORD};'
        f'TrustServerCertificate=yes'
    )
    with pyodbc.connect(conn_str, autocommit=True) as conn:
        cursor = conn.cursor()
        query = f"RESTORE HEADERONLY FROM URL='{backup_url}'"
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        row = cursor.fetchone()
        if not row:
            raise BackupValidationError('No backup header info found in file')
        header_info = dict(zip(columns, row))
        return header_info

def validate_backup_database_name(expected_db: str, blob_url: str) -> None:
    """
    Validates that the backup file's database name matches the expected database.
    Raises BackupValidationError if mismatch or issues.
    """
    try:
        header = get_backup_file_header(blob_url)
    except Exception as ex:
        raise BackupValidationError(f'Failed to read backup header: {ex}')

    backup_db_name = header.get('DatabaseName')
    if backup_db_name is None:
        raise BackupValidationError('DatabaseName not found in backup header')

    if backup_db_name.lower() != expected_db.lower():
        raise BackupValidationError(
            f"Backup file database name '{backup_db_name}' does not match expected '{expected_db}'"
        )

def main():
    import sys
    if len(sys.argv) != 3:
        print('Usage: python validate_backup_contents.py <backup_blob_url> <expected_database_name>')
        sys.exit(1)
    backup_blob_url = sys.argv[1]
    expected_db_name = sys.argv[2]

    try:
        validate_backup_database_name(expected_db_name, backup_blob_url)
        print('Backup validation successful. Database names match.')
        sys.exit(0)
    except BackupValidationError as e:
        print(f'Backup validation failed: {e}')
        sys.exit(2)

if __name__ == '__main__':
    main()
