"""
upload_knowledge.py -- Upload seed knowledge files to existing DBA_Knowledge_Base vector store
Author: jagadeesan.vg@cognizant.com - 2276259

Uploads manually created knowledge files (SOPs, incidents) to the EXISTING
vector store. Does NOT create a new vector store or overwrite .vector_store_id.

Uses openai.vector_stores.files.upload_and_poll to add files directly
to the existing vector store. No delete/recreate needed.

Usage: python upload_knowledge.py
"""
import os
import sys
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

load_dotenv()

# -- Files to upload -- add/remove as needed --
FILES_TO_UPLOAD = [
    "knowledge/SOP-RESTORE-001.md",
]

# -- Load existing vector store ID --
vs_id_file = ".vector_store_id"
if not os.path.exists(vs_id_file):
    print(f"Vector store ID file not found: {vs_id_file}")
    sys.exit(1)

vs_id = open(vs_id_file).read().strip()

project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
openai = project.get_openai_client()

# Step 1: Show current state
vs_detail = openai.vector_stores.retrieve(vector_store_id=vs_id)
current_count = vs_detail.file_counts.total if vs_detail.file_counts else 0
print(f"Vector store: {vs_detail.name} ({vs_id})")
print(f"Current files: {current_count}")
print("-" * 60)

# Step 2: Validate files
valid_files = []
for file_path in FILES_TO_UPLOAD:
    if not os.path.exists(file_path):
        print(f"  [SKIP] File not found: {file_path}")
    else:
        size_kb = round(os.path.getsize(file_path) / 1024, 1)
        print(f"  [READY] {file_path} ({size_kb}KB)")
        valid_files.append(file_path)

if not valid_files:
    print("\nNo valid files to upload.")
    sys.exit(1)

print(f"\n{len(valid_files)} file(s) ready for upload.")
print("-" * 60)

choice = input("Proceed with upload and vectorization? [y/n]: ").strip().lower()
if choice != "y":
    print("Cancelled.")
    sys.exit(0)

# Step 3: Upload and attach each file to existing vector store
uploaded = 0
for file_path in valid_files:
    print(f"\nUploading: {file_path}")
    with open(file_path, "rb") as f:
        vs_file = openai.vector_stores.files.upload_and_poll(
            vector_store_id=vs_id,
            file=f,
        )
    print(f"  File ID: {vs_file.id}")
    print(f"  Status: {vs_file.status}")
    uploaded += 1

# Step 4: Verify updated count
vs_detail = openai.vector_stores.retrieve(vector_store_id=vs_id)
new_count = vs_detail.file_counts.total if vs_detail.file_counts else 0
print(f"\n{'=' * 60}")
print(f"Uploaded {uploaded} file(s)")
print(f"Vector store now has {new_count} file(s) (was {current_count})")
print("No agent update needed.")
