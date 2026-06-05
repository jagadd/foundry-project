"""
create_agents_foundry.py – Phase 4 (v2): Create 3 agents in new Foundry format
Author: jagadeesan.vg@cognizant.com - 2276259

Uses the NEW Foundry API pattern:
  - AIProjectClient from azure.ai.projects
  - agents.create_version() with PromptAgentDefinition
  - FunctionTool / FileSearchTool definitions embedded in the agent definition
  - Runtime via project.get_openai_client(agent_name=...) + Responses API

NOTE: DO NOT run this if agents already exist from GUI migration.
      To update an existing agent, create_version() will create version N+1.
"""
import os, json
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

with open(".vector_store_id") as f:
    vector_store_id = f.read().strip()

# ── Tool Definitions (new Foundry format) ──
# Function tools — dict format accepted by PromptAgentDefinition
check_disk_space_fn = {
    "type": "function",
    "function": {
        "name": "check_disk_space",
        "description": "Check disk space on SQL Server 2025 VM.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

check_target_db_fn = {
    "type": "function",
    "function": {
        "name": "check_target_db",
        "description": "Check if DB exists and its state on SQL VM.",
        "parameters": {
            "type": "object",
            "properties": {
                "db_name": {"type": "string", "description": "Database name"}
            },
            "required": ["db_name"],
        },
    },
}

restore_database_fn = {
    "type": "function",
    "function": {
        "name": "restore_database",
        "description": "Restore DB on SQL VM from .bak file.",
        "parameters": {
            "type": "object",
            "properties": {
                "db_name": {"type": "string", "description": "Database name"},
                "backup_path": {"type": "string", "description": "Path to .bak file"},
            },
            "required": ["db_name"],
        },
    },
}

generate_sop_fn = {
    "type": "function",
    "function": {
        "name": "generate_sop",
        "description": "Auto-generate SOP from failure context using LLM.",
        "parameters": {
            "type": "object",
            "properties": {
                "failure_context": {
                    "type": "string",
                    "description": "JSON string of failure context",
                }
            },
            "required": ["failure_context"],
        },
    },
}

upload_sop_fn = {
    "type": "function",
    "function": {
        "name": "upload_sop_to_vectorstore",
        "description": "Upload SOP file to Foundry vector store.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Path to SOP markdown file",
                }
            },
            "required": ["filepath"],
        },
    },
}

suggest_tool_fn = {
    "type": "function",
    "function": {
        "name": "suggest_tool",
        "description": "Analyze failure and suggest/create new Python tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "failure_context": {
                    "type": "string",
                    "description": "JSON string of failure context",
                }
            },
            "required": ["failure_context"],
        },
    },
}

# FileSearchTool definition for the vector store
file_search_tool = {
    "type": "file_search",
    "file_search": {"vector_store_ids": [vector_store_id]},
}

# ══════════════════════════════════════════
#  AGENT 1: TRIAGE
# ══════════════════════════════════════════
TRIAGE_NAME = "dba-triage-agent"

print(f"Creating/updating agent '{TRIAGE_NAME}'...")
triage = project.agents.create_version(
    agent_name=TRIAGE_NAME,
    definition=PromptAgentDefinition(
        model=model,
        instructions="""You are the DBA Triage Agent for Cognizant's dbops-agent system.

YOUR ROLE:
1. Receive incoming requests (restore, health-check, incident)
2. Classify: RESTORE | HEALTH_CHECK | INCIDENT | UNKNOWN
3. For RESTORE requests:
   - Run check_disk_space to verify space on target VM
   - Run check_target_db to see current DB state
   - Consult SOPs from knowledge base
   - If all checks PASS respond:
     {"route_to": "restore_agent", "db_name": "<name>", "checks_passed": true}
   - If checks FAIL: explain what failed, do NOT route
4. For other types: handle directly or explain next steps

RULES: Always run checks before routing. Be concise. Reference SOP IDs.""",
        tools=[check_disk_space_fn, check_target_db_fn, file_search_tool],
    ),
    description="DBA Triage Agent — classifies requests and runs pre-checks",
)
print(f"✅ Triage Agent: {triage.name} v{triage.version} ({triage.status})")

# ══════════════════════════════════════════
#  AGENT 2: RESTORE
# ══════════════════════════════════════════
RESTORE_NAME = "dba-restore-agent"

print(f"\nCreating/updating agent '{RESTORE_NAME}'...")
restore = project.agents.create_version(
    agent_name=RESTORE_NAME,
    definition=PromptAgentDefinition(
        model=model,
        instructions="""You are the DBA Restore Agent.

YOUR ROLE:
1. Receive validated restore requests from Triage Agent
2. Execute restore_database tool
3. Validate with check_target_db post-restore
4. Return structured report:
   {"operation": "RESTORE", "db_name": "<>", "status": "SUCCESS/FAILED", "db_state": "<>"}

RULES: Only execute if checks_passed=true. Always validate post-restore. Be concise.""",
        tools=[restore_database_fn, check_target_db_fn, file_search_tool],
    ),
    description="DBA Restore Agent — executes and validates restores",
)
print(f"✅ Restore Agent: {restore.name} v{restore.version} ({restore.status})")

# ══════════════════════════════════════════
#  AGENT 3: LEARNING 🧠
# ══════════════════════════════════════════
LEARNING_NAME = "dba-learning-agent"

print(f"\nCreating/updating agent '{LEARNING_NAME}'...")
learning = project.agents.create_version(
    agent_name=LEARNING_NAME,
    definition=PromptAgentDefinition(
        model=model,
        instructions="""You are the DBA Learning Agent — the self-improving brain of dbops-agent.

TRIGGERED WHEN: An operation FAILS (or on-demand for review).

YOUR STEPS:
1. ANALYZE root cause from the error + context
2. GENERATE SOP — call generate_sop with failure context JSON
3. UPLOAD SOP — call upload_sop_to_vectorstore with the new SOP file path
   (Now ALL agents can find this fix in future operations!)
4. SUGGEST TOOL — call suggest_tool to check if a new Python tool could prevent this
   If created, flag for human review (never auto-deploy)
5. RETURN learning report:
   {
     "learning_triggered_by": "<failed operation>",
     "sop_generated": "<SOP-ID>",
     "sop_uploaded": true/false,
     "new_tool_suggested": true/false,
     "tool_name": "<if created>",
     "summary": "<what was learned>"
   }

WHY YOU EXIST: Every failure makes the system SMARTER. Without you, same failure = same result. With you, same failure = already has the fix.

RULES: Always generate SOP. Always try suggest_tool. Flag new tools for human review.""",
        tools=[generate_sop_fn, upload_sop_fn, suggest_tool_fn, file_search_tool],
    ),
    description="DBA Learning Agent — learns from failures and creates SOPs",
)
print(f"✅ Learning Agent: {learning.name} v{learning.version} ({learning.status})")

# ── Save agent info (v2 format: name + version) ──
agent_info = {
    "triage": {"name": triage.name, "version": triage.version, "id": triage.id},
    "restore": {"name": restore.name, "version": restore.version, "id": restore.id},
    "learning": {"name": learning.name, "version": learning.version, "id": learning.id},
}
with open(".agent_ids_v2.json", "w") as f:
    json.dump(agent_info, f, indent=2)

print(f"\n📄 Saved to .agent_ids_v2.json")
print(json.dumps(agent_info, indent=2))
print("""
╔══════════════════════════════════════════════════════╗
║  🎯 Phase 4 Complete — 3 Agents (Foundry v2 format) ║
║                                                      ║
║  1. dba-triage-agent   → Classify & Route            ║
║  2. dba-restore-agent  → Execute & Validate          ║
║  3. dba-learning-agent → Learn & Improve 🧠          ║
║                                                      ║
║  Runtime: project.get_openai_client(agent_name=...)  ║
║  Protocol: Responses API                             ║
║                                                      ║
║  Next → Phase 5: orchestrator.py (Responses API)     ║
╚══════════════════════════════════════════════════════╝
""")
