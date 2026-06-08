import os
import json
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

AZURE_BLOB_URL = os.getenv('AZURE_BLOB_URL')
AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
BLOB_CONTAINER = os.getenv('AZURE_BLOB_CONTAINER')
BACKUP_FILE_NAME = os.getenv('BACKUP_FILE_NAME')  # example: EnterpriseSales.bak

if not all([AZURE_BLOB_URL, AZURE_SAS_TOKEN, BLOB_CONTAINER, BACKUP_FILE_NAME]):
    raise EnvironmentError('Required environment variables are missing: AZURE_BLOB_URL, AZURE_SAS_TOKEN, AZURE_BLOB_CONTAINER, BACKUP_FILE_NAME')

class BackupBlobVerifier:
    def __init__(self, blob_url, sas_token, container_name):
        # Construct full blob service client with SAS token appended
        service_url = f"{blob_url}?{sas_token}"
        self.blob_service_client = BlobServiceClient(account_url=blob_url, credential=sas_token)
        self.container_name = container_name

    def verify_backup_exists(self, backup_file_name: str) -> bool:
        container_client = self.blob_service_client.get_container_client(self.container_name)
        try:
            blobs_list = list(container_client.list_blobs(name_starts_with=backup_file_name))
            for blob in blobs_list:
                if blob.name == backup_file_name and blob.size > 0:
                    return True
            return False
        except Exception as e:
            raise RuntimeError(f'Error accessing blob storage: {str(e)}')

    def get_backup_properties(self, backup_file_name: str) -> dict:
        container_client = self.blob_service_client.get_container_client(self.container_name)
        blob_client = container_client.get_blob_client(backup_file_name)
        props = blob_client.get_blob_properties()
        return {
            'size': props.size,
            'last_modified': props.last_modified.isoformat()
        }

if __name__ == '__main__':
    verifier = BackupBlobVerifier(AZURE_BLOB_URL, AZURE_SAS_TOKEN, BLOB_CONTAINER)
    try:
        exists = verifier.verify_backup_exists(BACKUP_FILE_NAME)
        if not exists:
            print(json.dumps({'error': f'Backup file {BACKUP_FILE_NAME} not found or empty in container {BLOB_CONTAINER}'}))
            exit(1)
        props = verifier.get_backup_properties(BACKUP_FILE_NAME)
        print(json.dumps({'status': 'success', 'backup_file': BACKUP_FILE_NAME, 'properties': props}))
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        exit(2)
