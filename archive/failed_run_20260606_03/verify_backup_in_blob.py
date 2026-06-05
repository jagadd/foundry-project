import os
from datetime import datetime, timezone, timedelta
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

AZURE_BLOB_URL = os.getenv('AZURE_BLOB_URL')
AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
BACKUP_CONTAINER = os.getenv('BACKUP_CONTAINER', 'backupfromazsqlmi')


def verify_backup_exists_and_recent(blob_name: str, hours_freshness: int = 48) -> bool:
    """Check if the specified backup file exists in blob storage and is modified within the given freshness interval."""
    try:
        blob_service_client = BlobServiceClient(account_url=AZURE_BLOB_URL, credential=AZURE_SAS_TOKEN)
        container_client = blob_service_client.get_container_client(BACKUP_CONTAINER)
        blob_client = container_client.get_blob_client(blob_name)

        blob_properties = blob_client.get_blob_properties()
        last_modified = blob_properties.last_modified

        now = datetime.now(timezone.utc)
        if now - last_modified <= timedelta(hours=hours_freshness):
            return True
        else:
            print(f"Backup file '{blob_name}' is older than {hours_freshness} hours.")
            return False
    except Exception as e:
        print(f"Backup file '{blob_name}' not found or inaccessible: {e}")
        return False


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Verify Azure Blob backup file existence and freshness.')
    parser.add_argument('--backup-file', required=True, help='Backup file name to verify in blob container')
    parser.add_argument('--hours', type=int, default=48, help='Freshness interval in hours')

    args = parser.parse_args()

    exists_and_recent = verify_backup_exists_and_recent(args.backup_file, args.hours)
    if exists_and_recent:
        print(f"Backup file '{args.backup_file}' exists and is recent.")
        exit(0)
    else:
        print(f"Backup file '{args.backup_file}' missing or outdated.")
        exit(1)
