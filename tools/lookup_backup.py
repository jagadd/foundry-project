"""
lookup_backup.py -- List all available backup files in Azure Blob Storage
and extract canonical source database names.
Author: jagadeesan.vg@cognizant.com - 2276259

Used by orchestrator to validate and resolve user-provided database names
before passing to restore_database.
"""
import os
import re
import json
from datetime import datetime, timezone
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv

load_dotenv()

AZURE_BLOB_URL = os.getenv("AZURE_BLOB_URL")
AZURE_SAS_TOKEN = os.getenv("AZURE_SAS_TOKEN", "").lstrip("?")

# Backup type suffixes to strip from DB name
BACKUP_TYPE_SUFFIXES = re.compile(
    r'(_Full|_Diff|_Log|_CopyOnly|_Copy|_FULL|_DIFF|_LOG)$', re.IGNORECASE
)


def _extract_source_db(filename):
    """
    Extract canonical source DB name from backup filename.
    Handles patterns like:
      EnterpriseSales_20260605_2110.bak        -> EnterpriseSales
      eSales_Full_20260606_000000.bak          -> eSales
      SomeDB_CopyOnly_20260601_1430.bak        -> SomeDB
      SomeDB_Diff_20260601_143000.bak          -> SomeDB
    """
    base = filename.rsplit('.', 1)[0]  # remove .bak

    # Remove timestamp: _YYYYMMDD_HHMM or _YYYYMMDD_HHMMSS
    base = re.sub(r'_\d{8}_\d{4,6}$', '', base)

    # Remove backup type suffix
    base = BACKUP_TYPE_SUFFIXES.sub('', base)

    return base


def lookup_backups():
    """
    List all .bak files in blob container, extract canonical source DB names.
    Returns dict with available_databases list (latest backup per source DB).
    """
    container_url = f"{AZURE_BLOB_URL}?{AZURE_SAS_TOKEN}"
    client = ContainerClient.from_container_url(container_url)

    all_backups = []
    for blob in client.list_blobs():
        if blob.name.lower().endswith(".bak"):
            source_db = _extract_source_db(blob.name)

            age_hours = round(
                (datetime.now(timezone.utc) - blob.last_modified).total_seconds() / 3600, 1
            )

            all_backups.append({
                "source_db": source_db,
                "filename": blob.name,
                "backup_size_mb": round(blob.size / (1024 * 1024), 2),
                "last_modified": blob.last_modified.isoformat(),
                "age_hours": age_hours,
            })

    # Group by source_db, keep only latest per DB
    db_map = {}
    for bak in all_backups:
        db = bak["source_db"]
        if db not in db_map or bak["last_modified"] > db_map[db]["last_modified"]:
            db_map[db] = bak

    available = []
    for db, info in sorted(db_map.items()):
        available.append({
            "source_db": info["source_db"],
            "latest_backup": info["filename"],
            "backup_size_mb": info["backup_size_mb"],
            "last_modified": info["last_modified"],
            "age_hours": info["age_hours"],
        })

    return {"available_databases": available}


if __name__ == "__main__":
    result = lookup_backups()
    print(json.dumps(result, indent=2))
