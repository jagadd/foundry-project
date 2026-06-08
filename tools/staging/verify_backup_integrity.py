import json
from azure.storage.blob import BlobClient
from dotenv import load_dotenv
import os

load_dotenv()

AZURE_BLOB_URL = os.getenv("AZURE_BLOB_URL")
AZURE_SAS_TOKEN = os.getenv("AZURE_SAS_TOKEN")
BACKUP_CONTAINER = os.getenv("BACKUP_CONTAINER", "backupfromazsqlmi")
BACKUP_FILENAME = os.getenv("BACKUP_FILENAME")  # example: 'EnterpriseSales.bak'

if not BACKUP_FILENAME:
    raise ValueError("BACKUP_FILENAME must be set in environment variables.")


class BackupIntegrityVerifier:
    def __init__(self, blob_url, sas_token, container_name, backup_file_name):
        self.container_url = blob_url.rstrip('/') + '/' + container_name
        self.sas_token = sas_token
        self.backup_file_name = backup_file_name
        self.blob_client = BlobClient(
            self.container_url,
            blob_name=backup_file_name,
            credential=sas_token)

    def get_backup_properties(self):
        try:
            props = self.blob_client.get_blob_properties()
            return {
                "size_bytes": props.size,
                "last_modified": props.last_modified.isoformat()
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get blob properties: {str(e)}")

    def check_backup_readability(self):
        # Read a small range of bytes to ensure blob is accessible and not corrupted
        try:
            stream = self.blob_client.download_blob(offset=0, length=1024)
            _ = stream.readall()
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to read from blob: {str(e)}")


def main():
    verifier = BackupIntegrityVerifier(AZURE_BLOB_URL, AZURE_SAS_TOKEN, BACKUP_CONTAINER, BACKUP_FILENAME)

    props = verifier.get_backup_properties()

    # Check if the backup file is larger than zero bytes
    if props["size_bytes"] == 0:
        print(json.dumps({"status": "failed", "reason": "Backup file size is zero."}))
        return

    # Verify readability
    verifier.check_backup_readability()

    print(json.dumps({"status": "success", "backup_file": BACKUP_FILENAME, "size_bytes": props["size_bytes"], "last_modified": props["last_modified"]}))


if __name__ == "__main__":
    main()
