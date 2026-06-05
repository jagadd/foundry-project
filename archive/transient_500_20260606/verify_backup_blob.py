import os
from azure.storage.blob import BlobClient
from dotenv import load_dotenv

def verify_backup_blob(container_name: str, blob_name: str) -> bool:
    load_dotenv()
    storage_account_url = os.getenv('AZURE_BLOB_URL')
    sas_token = os.getenv('AZURE_SAS_TOKEN')

    if not storage_account_url or not sas_token:
        raise EnvironmentError('Missing AZURE_BLOB_URL or AZURE_SAS_TOKEN in environment variables')

    blob_url = f"{storage_account_url}/{container_name}/{blob_name}?{sas_token}"
    blob = BlobClient.from_blob_url(blob_url)

    try:
        props = blob.get_blob_properties()
        return True
    except Exception as e:
        return False


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        print('Usage: python verify_backup_blob.py <container_name> <backup_filename.bak>')
        sys.exit(1)

    container = sys.argv[1]
    blob_name = sys.argv[2]
    exists = verify_backup_blob(container, blob_name)
    if exists:
        print(f'Backup file {blob_name} exists and is accessible in container {container}.')
        sys.exit(0)
    else:
        print(f'Backup file {blob_name} does not exist or is inaccessible in container {container}.')
        sys.exit(2)
