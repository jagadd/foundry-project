"""
list_foundry_vectorstores.py -- List all files, vector stores, and detect duplicates
Author: jagadeesan.vg@cognizant.com - 2276259

Uses: azure.ai.agents.AgentsClient
- client.files.list().data -> list of FileInfo objects
- client.vector_stores.list() -> ItemPaged, use list()
- client.vector_stores.get(vector_store_id) -> VectorStore detail
"""
import os
from collections import defaultdict
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

load_dotenv()

client = AgentsClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

print("Fetching files and vector stores from Foundry project...")
print(f"Endpoint: {os.environ['PROJECT_ENDPOINT']}")
print("=" * 80)

# --- SECTION 1: List all uploaded files ---
print("\n[UPLOADED FILES]")
print("-" * 80)

files_list = []
try:
    response = client.files.list()
    files_list = response.data or []

    if not files_list:
        print("No files found.")
    else:
        file_name_map = defaultdict(list)
        print(f"{'#':<4} {'FILENAME':<40} {'ID':<30} {'SIZE':<10} {'STATUS':<12} {'CREATED'}")
        print("-" * 120)
        for idx, f in enumerate(files_list, 1):
            fname = f.filename or "n/a"
            fid = f.id or "n/a"
            size = f.bytes or 0
            status = str(f.status or "n/a")
            created = str(f.created_at or "n/a")
            size_str = f"{round(size / 1024, 1)}KB" if size else "0KB"
            # Clean up enum display
            status = status.replace("FileState.", "")
            print(f"{idx:<4} {fname:<40} {fid:<30} {size_str:<10} {status:<12} {created}")
            file_name_map[fname].append(f)

        print("-" * 120)
        print(f"Total files: {len(files_list)}")

        dup_files = {n: entries for n, entries in file_name_map.items() if len(entries) > 1}
        if dup_files:
            print("\nWARNING: DUPLICATE FILE NAMES DETECTED")
            for name, entries in dup_files.items():
                print(f"  File: {name}  (count: {len(entries)})")
                for f in entries:
                    print(f"    ID: {f.id}  Created: {f.created_at}")
            print("\n  To delete a duplicate file:")
            print("    client.files.delete(file_id='<FILE_ID>')")
        else:
            print("No duplicate file names found.")

except Exception as e:
    print(f"Error listing files: {e}")

# --- SECTION 2: List all vector stores ---
print("\n\n[VECTOR STORES]")
print("-" * 80)

vs_list = []
try:
    vs_list = list(client.vector_stores.list())

    if not vs_list:
        print("No vector stores found.")
    else:
        vs_name_map = defaultdict(list)
        print(f"{'#':<4} {'NAME':<30} {'ID':<45} {'STATUS':<12} {'FILES'}")
        print("-" * 120)
        for idx, vs in enumerate(vs_list, 1):
            vs_name = vs.name or "(unnamed)"
            vs_id = vs.id or "n/a"
            status = str(vs.status or "n/a")
            status = status.replace("VectorStoreStatus.", "")
            file_counts = vs.file_counts
            total_files = "n/a"
            if file_counts:
                total_files = getattr(file_counts, "total", "n/a")
            print(f"{idx:<4} {vs_name:<30} {vs_id:<45} {status:<12} {total_files}")
            vs_name_map[vs_name].append(vs)

        print("-" * 120)
        print(f"Total vector stores: {len(vs_list)}")

        dup_vs = {n: entries for n, entries in vs_name_map.items() if len(entries) > 1}
        if dup_vs:
            print("\nWARNING: DUPLICATE VECTOR STORE NAMES DETECTED")
            for name, entries in dup_vs.items():
                print(f"  Store: {name}  (count: {len(entries)})")
                for vs in entries:
                    print(f"    ID: {vs.id}")
            print("\n  To delete a duplicate vector store:")
            print("    client.vector_stores.delete(vector_store_id='<STORE_ID>')")
        else:
            print("No duplicate vector store names found.")

except Exception as e:
    print(f"Error listing vector stores: {e}")

# --- SECTION 3: Map files to vector stores ---
print("\n\n[FILES MAPPED TO VECTOR STORES]")
print("-" * 80)

# Build file ID -> filename lookup
file_lookup = {}
for f in files_list:
    if f.id:
        file_lookup[f.id] = {
            "filename": f.filename or "n/a",
            "size": f.bytes or 0,
            "created": str(f.created_at or "n/a"),
        }

# For each vector store, find which files belong to it
# Since there is no list_files method, we check file IDs
for vs in vs_list:
    vs_name = vs.name or "(unnamed)"
    vs_id = vs.id or "n/a"
    file_counts = vs.file_counts
    total = getattr(file_counts, "total", 0) if file_counts else 0
    print(f"\nVector Store: {vs_name} ({vs_id}) -- {total} file(s)")

    # Try to get vector store detail for file references
    try:
        vs_detail = client.vector_stores.get(vector_store_id=vs_id)
        detail_attrs = [a for a in dir(vs_detail) if not a.startswith("_")]
        # Check for file-related attributes
        for attr in ["file_ids", "files", "file_counts"]:
            val = getattr(vs_detail, attr, None)
            if val and attr != "file_counts":
                print(f"  {attr}: {val}")
    except Exception as e:
        print(f"  Could not fetch detail: {e}")

    print(f"  (File-to-store mapping not available via SDK.")
    print(f"   Check Foundry portal > Knowledge > {vs_name} for file list.)")

# --- SECTION 4: Orphan detection ---
print("\n\n[SUMMARY]")
print("-" * 80)
print(f"Total uploaded files:  {len(files_list)}")
print(f"Total vector stores:   {len(vs_list)}")
vs_file_total = sum(
    getattr(vs.file_counts, "total", 0)
    for vs in vs_list if vs.file_counts
)
print(f"Files in vector stores: {vs_file_total}")
orphan_count = len(files_list) - vs_file_total
if orphan_count > 0:
    print(f"Possible orphan files:  {orphan_count}")
    print("  (Files uploaded but not attached to any vector store)")
    print("  Review the file list above and delete unused files if needed.")
elif orphan_count == 0:
    print("No orphan files detected.")
else:
    print(f"  Note: More files in stores ({vs_file_total}) than total uploaded ({len(files_list)}).")
    print("  This may indicate shared files across stores.")

print("\n" + "=" * 80)
print("Done.")