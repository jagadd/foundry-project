import os
from datetime import datetime, timedelta
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

def validate_backup_blob(db_name: str, container_name: str, storage_account_url: str, sas_token: str) -> str:
    load_dotenv()

    # Connect to blob service
    blob_service = BlobServiceClient(account_url=storage_account_url, credential=sas_token)
    container_client = blob_service.get_container_client(container_name)

    # List blobs matching copy_only salesdb backup pattern
    prefix = f"{db_name}_COPY_ONLY"
    recent_blobs = []

    for blob in container_client.list_blobs(name_starts_with=prefix):
        # Check blob last modified time
        if blob.last_modified is None:
            continue
        # Convert to UTC and check age
        age = datetime.utcnow() - blob.last_modified.replace(tzinfo=None)
        if age <= timedelta(hours=48):
            recent_blobs.append(blob.name)

    if not recent_blobs:
        raise FileNotFoundError(f"No {db_name} COPY_ONLY backup files found in the last 48 hours in container {container_name}.")

    # Prefer the most recent backup file
    recent_blobs.sort(reverse=True)
    return recent_blobs[0]


if __name__ == '__main__':
    import sys

    load_dotenv()
    container = os.getenv("AZURE_BLOB_CONTAINER", "backupfromazsqlmi")
    storage_url = os.getenv("AZURE_BLOB_URL")
    sas_token = os.getenv("AZURE_SAS_TOKEN")

    if not all([storage_url, sas_token]):
        print("Environment variables AZURE_BLOB_URL and AZURE_SAS_TOKEN must be set.", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python validate_backup_blob.py <db_name>", file=sys.stderr)
        sys.exit(1)

    database = sys.argv[1]

    try:
        valid_backup = validate_backup_blob(database, container, storage_url, sas_token)
        print(valid_backup)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
