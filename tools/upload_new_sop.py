"""
upload_new_sop.py – Upload auto-generated SOP to Foundry vector store (Foundry v2 format)
Author: jagadeesan.vg@cognizant.com - 2276259

NOTE: File upload and vector store operations are still only available through
      the AgentsClient from azure.ai.agents. The AIProjectClient (azure.ai.projects)
      does not expose file/vector store APIs. This is by design — file storage is
      a service-level operation, not a project-level one.
"""
import os, json
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FilePurpose
from azure.identity import DefaultAzureCredential

load_dotenv()

# File/vector store operations require AgentsClient
agents_client = AgentsClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
)


def upload_sop_to_vectorstore(filepath):
    with open(".vector_store_id") as f:
        vector_store_id = f.read().strip()

    result = {"filepath": filepath}
    try:
        uploaded = agents_client.files.upload_and_poll(
            file_path=filepath, purpose=FilePurpose.AGENTS
        )
        agents_client.vector_store_files.create(
            vector_store_id=vector_store_id, file_id=uploaded.id
        )
        result.update({
            "status": "SUCCESS",
            "file_id": uploaded.id,
            "vector_store_id": vector_store_id,
        })
    except Exception as e:
        result.update({"status": "FAILED", "error": str(e)})
    return result


if __name__ == "__main__":
    import sys
    print(json.dumps(upload_sop_to_vectorstore(sys.argv[1]), indent=2))
