
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

# Read existing vector store ID
with open(".vector_store_id") as f:
    vector_store_id = f.read().strip()

print(f"Using existing vector store: {vector_store_id}")

# Upload file
sop = client.files.upload_and_poll(
    file_path="knowledge/SOP-RESTORE-001.md",
    purpose=FilePurpose.AGENTS
)
print(f"✅ SOP uploaded: {sop.id}")

# Add to EXISTING vector store (not create new)
client.vector_store_files.create(
    vector_store_id=vector_store_id,
    file_id=sop.id
)
print(f"✅ Added to vector store: {vector_store_id}")
