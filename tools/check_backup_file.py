import os

def check_backup_file(backup_path):
    #raise Exception("SIMULATED: backup file not exists or not accessible")
    """
    Check if the backup file exists and is accessible.
    :param backup_path: Path to the backup file
    :return: True if file exists and is readable, False otherwise
    """
    return os.path.isfile(backup_path) and os.access(backup_path, os.R_OK)

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('Usage: python check_backup_file.py <backup_file_path>')
        sys.exit(1)

    backup_file = sys.argv[1]
    if check_backup_file(backup_file):
        print('Backup file exists and is accessible.')
        sys.exit(0)
    else:
        print('Backup file not found or not accessible.')
        sys.exit(2)