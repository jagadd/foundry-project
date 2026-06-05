import os

def verify_backup_path(backup_path):
    """Verify if the backup file exists, is a file, and is accessible for reading."""
    if not os.path.exists(backup_path):
        return False, f"Backup file not found at {backup_path}"
    if not os.path.isfile(backup_path):
        return False, f"Specified path is not a file: {backup_path}"
    if not os.access(backup_path, os.R_OK):
        return False, f"No read permission for backup file: {backup_path}"
    return True, "Backup file is valid and accessible"

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python verify_backup_path.py <backup_file_path>")
        sys.exit(1)

    path = sys.argv[1]
    valid, message = verify_backup_path(path)
    if valid:
        print(message)
        sys.exit(0)
    else:
        print(message)
        sys.exit(2)