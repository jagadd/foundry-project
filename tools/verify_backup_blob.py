import os
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv

load_dotenv()

AZURE_BLOB_URL = os.getenv('AZURE_BLOB_URL')
AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
BACKUP_CONTAINER = 'backupfromazsqlmi'


def verify_backup_exists(db_name: str) -> bool:
    container_client = ContainerClient(account_url=AZURE_BLOB_URL, container_name=BACKUP_CONTAINER, credential=AZURE_SAS_TOKEN)
    prefix = f'{db_name}'  # assuming backups start with db_name
    try:
        blobs = container_client.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            if blob.name.endswith('.bak'):
                return True
        return False
    except Exception as e:
        raise RuntimeError(f'Failed to verify backup in blob storage: {e}')


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('Usage: python verify_backup_blob.py <db_name>')
        exit(1)
    db_name = sys.argv[1]
    exists = verify_backup_exists(db_name)
    if exists:
        print(f'Backup file for database "{db_name}" found in blob storage.')
        exit(0)
    else:
        print(f'Backup file for database "{db_name}" NOT found in blob storage.')
        exit(2)
