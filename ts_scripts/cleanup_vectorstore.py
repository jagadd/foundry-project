"""
cleanup_vectorstore.py -- List and remove duplicate/unwanted files from vector store
Author: jagadeesan.vg@cognizant.com - 2276259

Usage:
  List files:   python cleanup_vectorstore.py
  Delete file:  python cleanup_vectorstore.py delete <file_id>
"""
import os
import sys
from collections import defaultdict
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

load_dotenv()

project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
openai = project.get_openai_client()

vs_id = open(".vector_store_id").read().strip()
print(f"Vector store: {vs_id}")
print("=" * 80)

# List all files in vector store
vs_files = list(openai.vector_stores.files.list(vector_store_id=vs_id))
print(f"\n{'#':<4} {'FILENAME':<40} {'FILE_ID':<35} {'SIZE':<10} {'STATUS'}")
print("-" * 100)

file_details = []
for idx, vf in enumerate(vs_files, 1):
    # Get file details
    try:
        detail = openai.files.retrieve(file_id=vf.id)
        fname = detail.filename or "n/a"
        size = detail.bytes or 0
        size_str = f"{round(size / 1024, 1)}KB" if size else "0KB"
    except Exception:
        fname = "n/a"
        size_str = "n/a"
    status = vf.status or "n/a"
    print(f"{idx:<4} {fname:<40} {vf.id:<35} {size_str:<10} {status}")
    file_details.append({"idx": idx, "filename": fname, "id": vf.id, "size_str": size_str})

print("-" * 100)
print(f"Total files in vector store: {len(vs_files)}")

# Detect duplicates by filename
name_map = defaultdict(list)
for fd in file_details:
    name_map[fd["filename"]].append(fd)

dups = {n: entries for n, entries in name_map.items() if len(entries) > 1}
if dups:
    print("\nDUPLICATES FOUND:")
    for name, entries in dups.items():
        print(f"  {name} (count: {len(entries)})")
        for e in entries:
            print(f"    #{e['idx']} ID: {e['id']}")

# Handle delete command
if len(sys.argv) >= 3 and sys.argv[1] == "delete":
    file_id = sys.argv[2]
    print(f"\nDeleting file {file_id} from vector store...")
    try:
        openai.vector_stores.files.delete(
            vector_store_id=vs_id,
            file_id=file_id,
        )
        print(f"  Removed from vector store.")
    except Exception as e:
        print(f"  Error: {e}")

    # Verify
    remaining = list(openai.vector_stores.files.list(vector_store_id=vs_id))
    print(f"  Files remaining: {len(remaining)}")

elif len(sys.argv) == 1:
    if dups:
        print("\nTo remove a duplicate, run:")
        print("  python ts_scripts/cleanup_vectorstore.py delete <FILE_ID>")
        print("\nKeep the newer one, delete the older duplicate.")
else:
    print("\nUsage:")
    print("  List:   python ts_scripts/cleanup_vectorstore.py")
    print("  Delete: python ts_scripts/cleanup_vectorstore.py delete <file_id>")