import os
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv
import sys

def main():
    load_dotenv()
    blob_url = os.getenv('AZURE_BLOB_URL')  # e.g. https://2276259blob.blob.core.windows.net/backupfromazsqlmi
    sas_token = os.getenv('AZURE_SAS_TOKEN')
    container_name = blob_url.strip('/').split('/')[-1]
    account_url = blob_url.split(container_name)[0].rstrip('/')

    if not (blob_url and sas_token):
        print('Environment variables AZURE_BLOB_URL and AZURE_SAS_TOKEN must be set')
        sys.exit(1)

    try:
        container = ContainerClient(account_url=account_url, container_name=container_name, credential=sas_token)
        blobs_list = list(container.list_blobs(name_starts_with=""))
    except Exception as e:
        print(f'Failed to connect to blob container: {e}')
        sys.exit(2)

    if not blobs_list:
        print('No backup blobs found in the container')
        sys.exit(3)

    # Optionally check for specific *.bak files
    bak_files = [blob.name for blob in blobs_list if blob.name.lower().endswith('.bak')]
    if not bak_files:
        print('No .bak files found in the backup container')
        sys.exit(4)

    print(f'Accessible backup files: {bak_files}')

if __name__ == '__main__':
    main()
