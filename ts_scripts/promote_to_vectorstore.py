"""
promote_to_vectorstore.py -- Promote a staging file to the DBA_Knowledge_Base vector store
Author: jagadeesan.vg@cognizant.com - 2276259

Uses openai.vector_stores.files.upload_and_poll to add files directly
to the existing vector store. No delete/recreate needed.

Usage: python promote_to_vectorstore.py knowledge/staging/SOP-AUTO-XXXXXXXX.md
"""
import os
import sys
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

load_dotenv()

if len(sys.argv) < 2:
    print("Usage: python promote_to_vectorstore.py <file_path>")
    print("Example: python promote_to_vectorstore.py knowledge/staging/SOP-AUTO-20260606_032427.md")
    sys.exit(1)

file_path = sys.argv[1]

if not os.path.exists(file_path):
    print(f"File not found: {file_path}")
    sys.exit(1)

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
print(f"\nFile to promote: {file_path}")
print(f"File size: {round(os.path.getsize(file_path) / 1024, 1)}KB")
print("-" * 60)

choice = input("Proceed with upload and vectorization? [y/n]: ").strip().lower()
if choice != "y":
    print("Cancelled.")
    sys.exit(0)

# Step 2: Upload and attach in one step (no recreate needed)
print("\nUploading and attaching to vector store...")
with open(file_path, "rb") as f:
    vs_file = openai.vector_stores.files.upload_and_poll(
        vector_store_id=vs_id,
        file=f,
    )
print(f"  File ID: {vs_file.id}")
print(f"  Status: {vs_file.status}")

# Step 3: Verify updated count
vs_detail = openai.vector_stores.retrieve(vector_store_id=vs_id)
new_count = vs_detail.file_counts.total if vs_detail.file_counts else 0
print(f"\nVector store now has {new_count} file(s). (was {current_count})")

# Step 4: Move file from staging to promoted
promoted_dir = "knowledge/promoted"
os.makedirs(promoted_dir, exist_ok=True)
promoted_path = os.path.join(promoted_dir, os.path.basename(file_path))
os.rename(file_path, promoted_path)
print(f"Moved: {file_path} -> {promoted_path}")

print("\nDone. File added to vector store. No agent update needed.")