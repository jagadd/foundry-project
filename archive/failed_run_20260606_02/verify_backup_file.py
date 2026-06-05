import os
import sys
from datetime import datetime, timedelta

import azure.storage.blob
from azure.storage.blob import BlobServiceClient

class BackupFileVerifier:
    def __init__(self, backup_path, storage_account_url=None, container_name=None, credential=None):
        self.backup_path = backup_path
        self.storage_account_url = storage_account_url
        self.container_name = container_name
        self.credential = credential

    def is_local_file(self):
        return not (self.backup_path.startswith('https://') or self.backup_path.startswith('http://'))

    def verify_local_backup(self):
        if not os.path.isfile(self.backup_path):
            raise FileNotFoundError(f"Backup file not found at local path: {self.backup_path}")
        # Check read permission
        if not os.access(self.backup_path, os.R_OK):
            raise PermissionError(f"No read permission for backup file: {self.backup_path}")

        # Check file age <= 48 hours
        mtime = datetime.fromtimestamp(os.path.getmtime(self.backup_path))
        age = datetime.now() - mtime
        if age > timedelta(hours=48):
            raise ValueError(f"Backup file is older than 48 hours: {self.backup_path}")

        return True

    def verify_azure_blob_backup(self):
        if not all([self.storage_account_url, self.container_name, self.credential]):
            raise ValueError("Storage account URL, container name and credential must be provided for Azure Blob backups")
        try:
            blob_service_client = BlobServiceClient(account_url=self.storage_account_url, credential=self.credential)
            container_client = blob_service_client.get_container_client(self.container_name)
            blob_client = container_client.get_blob_client(self.backup_path)

            props = blob_client.get_blob_properties()
            last_modified = props.last_modified.replace(tzinfo=None)

            age = datetime.now() - last_modified
            if age > timedelta(hours=48):
                raise ValueError(f"Backup blob is older than 48 hours: {self.backup_path}")

            # Further access verification could be done here
            return True
        except azure.core.exceptions.ResourceNotFoundError:
            raise FileNotFoundError(f"Backup blob not found: {self.backup_path}")
        except Exception as e:
            raise e

    def verify(self):
        if self.is_local_file():
            return self.verify_local_backup()
        else:
            return self.verify_azure_blob_backup()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Verify backup file existence and accessibility')
    parser.add_argument('--path', required=True, help='Backup file path or blob name')
    parser.add_argument('--storage-account-url', help='Azure Storage account URL (for blob storage)')
    parser.add_argument('--container-name', help='Azure Blob container name')
    parser.add_argument('--credential', help='Credential (SAS token or account key) for storage access')

    args = parser.parse_args()

    verifier = BackupFileVerifier(args.path, args.storage_account_url, args.container_name, args.credential)
    try:
        verifier.verify()
        print('Backup file verification succeeded.')
        sys.exit(0)
    except Exception as e:
        print(f'Backup file verification failed: {e}', file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()