"""
generate_sop.py -- Auto-generate SOP from failure using LLM (Foundry v2 format)
Author: jagadeesan.vg@cognizant.com - 2276259
"""
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential

load_dotenv()

project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
model = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

TEMP_AGENT_NAME = "sop-generator-temp"


def generate_sop(failure_context):
    if isinstance(failure_context, str):
        try:
            failure_context = json.loads(failure_context)
        except (json.JSONDecodeError, ValueError):
            # Deeply nested escaped JSON (e.g., D:\ paths) can break parsing.
            # Use raw string as-is -- the LLM prompt still works with unformatted text.
            failure_context = {"raw_context": failure_context}

    prompt = f"""You are a senior DBA knowledge engineer working in an Azure cloud environment.
A database operation FAILED. Generate a detailed SOP in Markdown.

ENVIRONMENT ARCHITECTURE (use this to inform your analysis):
- Source: Azure SQL Managed Instance (production)
- Backup storage: Azure Blob Storage (container: backupfromazsqlmi, storage account: 2276259blob)
- Backups are pushed from SQL MI to Blob as .bak files
- Target: SQL Server 2025 on a Windows VM (10.10.0.5)
- Restore method: RESTORE FROM URL using SAS credential (NOT local disk)
- Automation runs from a Linux dev VM connecting remotely via pyodbc
- Tools auto-discover backup files by listing the blob container

FAILURE CONTEXT:
{json.dumps(failure_context, indent=2)}

ANALYSIS REQUIREMENTS:
- Consider the FULL architecture above when analyzing root cause
- If a file was not found, think about ALL possible locations: blob storage,
  naming conventions, container paths, SAS token validity, network access
- Do not assume backups are on local disk unless evidence proves it
- Suggest solutions that work within this Azure cloud architecture
- Consider: blob listing failures, SAS expiry, network/firewall issues,
  wrong container, naming mismatch between source DB and backup file names

Use this structure:
# SOP-AUTO-<timestamp> : <Short Title>
## Classification
- **Category**: (RESTORE | BACKUP | CONNECTIVITY | DISK | PERMISSION | OTHER)
- **Severity**: (P1 | P2 | P3)
- **Auto-Generated**: Yes
- **Generated On**: <datetime>
## Problem Description
## Root Cause Analysis
(Consider all architectural components that could contribute)
## Resolution Steps
(Steps must be specific to Azure Blob + SQL Server restore architecture)
## Prevention
## Suggested Tool Improvement
"""

    try:
        project.agents.delete(TEMP_AGENT_NAME)
    except Exception:
        pass

    project.agents.create_version(
        agent_name=TEMP_AGENT_NAME,
        definition=PromptAgentDefinition(
            model=model,
            instructions="Generate structured SOP documents for Azure cloud DBA operations. Output ONLY the markdown SOP.",
        ),
        description="Temporary agent for SOP generation",
    )

    openai_client = project.get_openai_client(agent_name=TEMP_AGENT_NAME)
    response = openai_client.responses.create(
        model=model,
        input=prompt,
    )

    result = {"status": "FAILED"}
    sop_content = response.output_text
    if sop_content:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sop_id = f"SOP-AUTO-{timestamp}"
        filename = f"knowledge/staging/{sop_id}.md"
        with open(filename, "w") as f:
            f.write(sop_content)
        result = {
            "status": "SUCCESS",
            "sop_id": sop_id,
            "filename": filename,
            "content_preview": sop_content[:300] + "...",
        }

    try:
        project.agents.delete(TEMP_AGENT_NAME)
    except Exception:
        pass

    return result


if __name__ == "__main__":
    sample = {
        "operation": "RESTORE",
        "db_name": "salesdb",
        "error": "Backup file not found",
        "timestamp": datetime.now().isoformat(),
    }
    print(json.dumps(generate_sop(sample), indent=2))
