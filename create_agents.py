"""
create_agents.py -- Create 3 agents in Foundry for dbops-agent
Author: jagadeesan.vg@cognizant.com - 2276259
"""
import os
import json
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FileSearchTool
from azure.identity import DefaultAzureCredential

load_dotenv()

client = AgentsClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
)
model = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4-1-mini")

with open(".vector_store_id") as f:
    vector_store_id = f.read().strip()

file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])

# -- Function Schemas --

check_disk_space_fn = {
    "type": "function",
    "function": {
        "name": "check_disk_space",
        "description": "Check available disk space on SQL Server 2025 VM. Returns drive info with total, free MB and percentage.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

check_target_db_fn = {
    "type": "function",
    "function": {
        "name": "check_target_db",
        "description": "Check if a database exists on the target SQL Server 2025 VM, its state, and active connections.",
        "parameters": {
            "type": "object",
            "properties": {
                "db_name": {"type": "string", "description": "Database name to check"},
            },
            "required": ["db_name"],
        },
    },
}

restore_database_fn = {
    "type": "function",
    "function": {
        "name": "restore_database",
        "description": (
            "Restore a database on the target SQL Server 2025 VM from a .bak file "
            "stored in Azure Blob Storage (container: backupfromazsqlmi). "
            "The tool uses RESTORE FROM URL with SAS credential -- NOT local disk. "
            "If backup_path is omitted, the tool auto-discovers the latest .bak "
            "matching the db_name from the blob container."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "db_name": {
                    "type": "string",
                    "description": "Target database name for the restored DB",
                },

            },
            "required": ["db_name"],
        },
    },
}

generate_sop_fn = {
    "type": "function",
    "function": {
        "name": "generate_sop",
        "description": "Auto-generate an SOP document from failure context using LLM.",
        "parameters": {
            "type": "object",
            "properties": {
                "failure_context": {
                    "type": "string",
                    "description": "JSON string of failure context",
                },
            },
            "required": ["failure_context"],
        },
    },
}

upload_sop_fn = {
    "type": "function",
    "function": {
        "name": "upload_sop_to_vectorstore",
        "description": "Upload a generated SOP markdown file to Foundry vector store for knowledge retrieval.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Path to SOP markdown file",
                },
            },
            "required": ["filepath"],
        },
    },
}

suggest_tool_fn = {
    "type": "function",
    "function": {
        "name": "suggest_tool",
        "description": "Analyze a failure and suggest or create a new Python tool to prevent it in future.",
        "parameters": {
            "type": "object",
            "properties": {
                "failure_context": {
                    "type": "string",
                    "description": "JSON string of failure context",
                },
            },
            "required": ["failure_context"],
        },
    },
}


# ============================================================
#  AGENT 1: TRIAGE
# ============================================================
print("Creating Triage Agent...")
triage = client.create_agent(
    model=model,
    name="DBA-Triage-Agent",
    instructions="""You are the DBA Triage Agent for the dbops-agent system.

ROLE:
1. Receive incoming requests (restore, health-check, incident).
2. Classify the request: RESTORE | HEALTH_CHECK | INCIDENT | UNKNOWN.
3. For RESTORE requests:
   - Run check_disk_space to verify the target VM has enough free space.
   - Run check_target_db to check if the target database already exists and its state.
   - Consult SOPs from the knowledge base for any pre-restore requirements.
   - If all checks PASS, respond with exactly:
     {"route_to": "restore_agent", "db_name": "<name>", "checks_passed": true}
   - If checks FAIL, explain what failed and do NOT route.
4. For other request types, handle directly or explain next steps.

RULES:
- Always run both checks before routing a restore request.
- Be concise and reference SOP IDs when applicable.
- Do not make assumptions about backup locations or paths.""",
    tools=[check_disk_space_fn, check_target_db_fn] + file_search_tool.definitions,
    tool_resources=file_search_tool.resources,
)
print(f"  Triage Agent: {triage.id}")


# ============================================================
#  AGENT 2: RESTORE
# ============================================================
print("Creating Restore Agent...")
restore = client.create_agent(
    model=model,
    name="DBA-Restore-Agent",
    instructions="""You are the DBA Restore Agent.

ARCHITECTURE:
- Backup .bak files are stored in Azure Blob Storage, NOT on local disk.
- Container: backupfromazsqlmi (storage account: 2276259blob).
- The restore_database tool uses RESTORE FROM URL with a SAS credential.
- If you do not know the exact backup file name, pass ONLY db_name to the
  restore_database tool. It will auto-discover the latest .bak from blob.
- NEVER pass local disk paths like D:\\backups\\... as backup_path.
- If you pass backup_path, it must be the blob file name only, e.g.
  EnterpriseHR_Full_20260605_180505.bak

ROLE:
1. Receive validated restore requests from the Triage Agent.
2. Call restore_database with db_name (and optionally backup_path as blob file name).
3. If restore succeeds, call check_target_db to verify the database is ONLINE.
4. Return a structured report:
   {"operation": "RESTORE", "db_name": "<name>", "status": "SUCCESS/FAILED",
    "db_state": "<state>", "backup_used": "<blob file name>"}

RULES:
- Only execute if the triage context confirms checks_passed=true.
- Always verify post-restore with check_target_db.
- Be concise. Do not hallucinate file paths.""",
    tools=[restore_database_fn, check_target_db_fn] + file_search_tool.definitions,
    tool_resources=file_search_tool.resources,
)
print(f"  Restore Agent: {restore.id}")


# ============================================================
#  AGENT 3: LEARNING
# ============================================================
print("Creating Learning Agent...")
learning = client.create_agent(
    model=model,
    name="DBA-Learning-Agent",
    instructions="""You are the DBA Learning Agent -- the self-improving component of dbops-agent.

ARCHITECTURE CONTEXT:
- Backups are in Azure Blob Storage (not local disk).
- Restores use RESTORE FROM URL with SAS credentials.
- Target is SQL Server 2025 on a Windows VM (10.10.0.5).
- Tools run from a Linux dev VM connecting remotely.

TRIGGERED WHEN: An operation fails, or on-demand for review.

STEPS:
1. ANALYZE the root cause from the error and context provided.
2. GENERATE SOP: Call generate_sop with the failure context JSON.
3. UPLOAD SOP: Call upload_sop_to_vectorstore with the new SOP file path.
4. SUGGEST TOOL: Call suggest_tool to check if a new Python tool could prevent
   this failure. If a tool is created, flag it for human review.
5. RETURN a learning report:
   {
     "learning_triggered_by": "<failed operation>",
     "sop_generated": "<SOP-ID>",
     "sop_uploaded": true/false,
     "new_tool_suggested": true/false,
     "tool_name": "<if created>",
     "summary": "<what was learned>"
   }

RULES:
- Always generate an SOP.
- Always call suggest_tool.
- New tools must be flagged for human review, never auto-deployed.
- When analyzing failures, consider the blob-based architecture.
  Do not suggest local filesystem solutions for backup-related issues.""",
    tools=[generate_sop_fn, upload_sop_fn, suggest_tool_fn] + file_search_tool.definitions,
    tool_resources=file_search_tool.resources,
)
print(f"  Learning Agent: {learning.id}")


# -- Save IDs --
agent_ids = {
    "triage_agent_id": triage.id,
    "restore_agent_id": restore.id,
    "learning_agent_id": learning.id,
}
with open(".agent_ids.json", "w") as f:
    json.dump(agent_ids, f, indent=2)

print(f"\nSaved to .agent_ids.json")
print(json.dumps(agent_ids, indent=2))
print("\n-- All 3 agents created --")
print("  1. DBA-Triage-Agent   : Classify and route")
print("  2. DBA-Restore-Agent  : Execute restore from Azure Blob")
print("  3. DBA-Learning-Agent : Analyze failures, generate SOPs, suggest tools")
