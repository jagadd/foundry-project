import os
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

AZURE_BLOB_URL = os.getenv('AZURE_BLOB_URL')
AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
CONTAINER_NAME = 'backupfromazsqlmi'

class BackupBlobVerifier:
    def __init__(self, blob_url, sas_token, container_name):
        self.blob_service_client = BlobServiceClient(account_url=blob_url, credential=sas_token)
        self.container_client = self.blob_service_client.get_container_client(container_name)

    def backup_exists(self, backup_name: str) -> bool:
        blob_name = backup_name if backup_name.endswith('.bak') else backup_name + '.bak'
        try:
            blobs_list = self.container_client.list_blobs(name_starts_with=blob_name)
            for blob in blobs_list:
                if blob.name.lower() == blob_name.lower():
                    return True
            return False
        except Exception:
            return False

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('Usage: python verify_backup_blob.py <DatabaseName>')
        sys.exit(1)
    db_name = sys.argv[1]
    verifier = BackupBlobVerifier(AZURE_BLOB_URL, AZURE_SAS_TOKEN, CONTAINER_NAME)
    exists = verifier.backup_exists(db_name)
    if exists:
        print(f'Backup file {db_name}.bak exists in blob storage.')
        sys.exit(0)
    else:
        print(f'Backup file {db_name}.bak NOT found in blob storage.')
        sys.exit(2)