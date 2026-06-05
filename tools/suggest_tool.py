"""
suggest_tool.py -- Analyze failure and suggest new Python tools (Foundry v2 format)
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

TEMP_AGENT_NAME = "tool-suggester-temp"


def suggest_tool(failure_context):
    if isinstance(failure_context, str):
        failure_context = json.loads(failure_context)

    prompt = f"""You are a senior DBA automation engineer working in an Azure cloud environment.
A database operation failed. Analyze if a NEW reusable Python tool could prevent this.

ENVIRONMENT ARCHITECTURE (tools must work within this):
- Source: Azure SQL Managed Instance (production)
- Backup storage: Azure Blob Storage (container: backupfromazsqlmi, storage account: 2276259blob)
- Backups are .bak files in blob, accessed via SAS token
- Target: SQL Server 2025 on Windows VM (10.10.0.5), connected via pyodbc
- Restore method: RESTORE FROM URL with SAS credential
- Automation runs from Linux dev VM (not on the SQL Server itself)
- Python packages available: pyodbc, azure-storage-blob, python-dotenv

FAILURE CONTEXT:
{json.dumps(failure_context, indent=2)}

EXISTING TOOLS (do not recreate these):
- check_disk_space.py: Checks disk space on SQL VM via pyodbc
- check_target_db.py: Checks if DB exists on SQL VM
- restore_database.py: Restores DB from blob URL using SAS credential
- find_backup.py: Queries msdb backup history on SQL VM

REQUIREMENTS FOR SUGGESTED TOOL:
- Must work with Azure Blob Storage (not local filesystem)
- Must connect remotely (pyodbc for SQL, azure-storage-blob for blob)
- Must use environment variables from .env (AZURE_BLOB_URL, AZURE_SAS_TOKEN, SQLVM_SERVER, etc.)
- Do not use os.path.exists or local file checks for backup verification
- Do not use any emoji or icons in code or comments

IF a new tool would help, respond with ONLY this JSON:
{{"tool_needed": true, "tool_name": "<file>.py", "description": "<one line>", "python_code": "<full code>"}}

IF not needed, respond with ONLY this JSON:
{{"tool_needed": false, "reason": "<why existing tools are sufficient>"}}
"""

    try:
        project.agents.delete(TEMP_AGENT_NAME)
    except Exception:
        pass

    project.agents.create_version(
        agent_name=TEMP_AGENT_NAME,
        definition=PromptAgentDefinition(
            model=model,
            instructions="Analyze failures and suggest Python tools for Azure cloud DBA automation. Output ONLY valid JSON.",
        ),
        description="Temporary agent for tool suggestion",
    )

    openai_client = project.get_openai_client(agent_name=TEMP_AGENT_NAME)
    response = openai_client.responses.create(
        model=model,
        input=prompt,
    )

    result = {"status": "FAILED"}
    raw_text = response.output_text
    if raw_text:
        try:
            cleaned = raw_text.strip().strip("```json").strip("```").strip()
            suggestion = json.loads(cleaned)
            if suggestion.get("tool_needed"):
                tool_path = f"tools/staging/{suggestion['tool_name']}"
                with open(tool_path, "w") as f:
                    f.write(suggestion["python_code"])
                result = {
                    "status": "SUCCESS",
                    "tool_created": True,
                    "tool_path": tool_path,
                    "description": suggestion["description"],
                }
            else:
                result = {
                    "status": "SUCCESS",
                    "tool_created": False,
                    "reason": suggestion.get("reason"),
                }
        except json.JSONDecodeError:
            result = {"status": "PARTIAL", "raw": raw_text[:500]}

    try:
        project.agents.delete(TEMP_AGENT_NAME)
    except Exception:
        pass

    return result


if __name__ == "__main__":
    sample = {
        "operation": "RESTORE",
        "db_name": "salesdb",
        "error": "Backup file not found in blob",
        "timestamp": datetime.now().isoformat(),
    }
    print(json.dumps(suggest_tool(sample), indent=2))
