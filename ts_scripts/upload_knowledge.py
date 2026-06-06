import os
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FilePurpose
from azure.identity import DefaultAzureCredential

load_dotenv()

client = AgentsClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential()
)

# Upload files
print("Uploading knowledge files...")

sop = client.files.upload_and_poll(
    file_path="knowledge/SOP-RESTORE-001.md",
    purpose=FilePurpose.AGENTS
)
print(f"✅ SOP uploaded: {sop.id}")

inc1 = client.files.upload_and_poll(
    file_path="knowledge/INC-4821.md",
    purpose=FilePurpose.AGENTS
)
print(f"✅ INC-4821 uploaded: {inc1.id}")

inc2 = client.files.upload_and_poll(
    file_path="knowledge/INC-5102.md",
    purpose=FilePurpose.AGENTS
)
print(f"✅ INC-5102 uploaded: {inc2.id}")

# Create vector store
print("\nCreating vector store...")
vector_store = client.vector_stores.create_and_poll(
    file_ids=[sop.id, inc1.id, inc2.id],
    name="DBA_Knowledge_Base"
)
print(f"✅ Vector store created: {vector_store.id}")
print(f"   Name: {vector_store.name}")
print(f"   File count: {vector_store.file_counts}")

# Save for later use
with open(".vector_store_id", "w") as f:
    f.write(vector_store.id)
print(f"\n✅ Saved to .vector_store_id")
