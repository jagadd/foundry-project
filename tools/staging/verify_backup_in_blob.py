import os
from datetime import datetime
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv
load_dotenv()

AZURE_BLOB_URL = os.getenv('AZURE_BLOB_URL')
AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
CONTAINER_NAME = os.getenv('AZURE_BLOB_CONTAINER', 'backupfromazsqlmi')
DB_NAME = os.getenv('DB_NAME')

if not all([AZURE_BLOB_URL, AZURE_SAS_TOKEN, CONTAINER_NAME, DB_NAME]):
    raise EnvironmentError('Missing one or more required environment variables: AZURE_BLOB_URL, AZURE_SAS_TOKEN, AZURE_BLOB_CONTAINER, DB_NAME')

# Compose blob service client with SAS token
container_url = f"{AZURE_BLOB_URL}/{CONTAINER_NAME}?{AZURE_SAS_TOKEN}"
container_client = ContainerClient.from_container_url(container_url)


def list_backup_blobs_for_db(db_name):
    prefix = f"{db_name.lower()}"  # assuming backups are prefixed with DB name lowercase
    backup_blobs = []
    # List blobs with .bak extension containing db_name prefix
    blobs = container_client.list_blobs(name_starts_with=prefix)
    for blob in blobs:
        if blob.name.endswith('.bak'):
            backup_blobs.append(blob)
    return backup_blobs


def select_latest_backup(blob_list):
    # Select newest blob by last modified datetime
    if not blob_list:
        return None
    latest_blob = max(blob_list, key=lambda b: b.last_modified)
    return latest_blob


def build_blob_url(blob_name):
    # Build full blob URL with SAS token
    return f"{AZURE_BLOB_URL}/{CONTAINER_NAME}/{blob_name}?{AZURE_SAS_TOKEN}"


def main():
    backups = list_backup_blobs_for_db(DB_NAME)
    if not backups:
        print(f"No .bak backups found in blob container {CONTAINER_NAME} for database {DB_NAME}.")
        return None

    latest_backup_blob = select_latest_backup(backups)
    print(f"Latest backup found: {latest_backup_blob.name}, Last modified: {latest_backup_blob.last_modified}")

    backup_url = build_blob_url(latest_backup_blob.name)
    print(f"Backup URL to use for RESTORE: {backup_url}")
    return backup_url


if __name__ == '__main__':
    main()