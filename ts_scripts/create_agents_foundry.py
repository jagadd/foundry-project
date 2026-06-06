"""
create_agents_foundry.py -- Create or update 3 agents in Foundry (v1.1)
Author: jagadeesan.vg@cognizant.com - 2276259

Uses the Foundry API with SDK model classes:
  - FunctionTool for function definitions
  - FileSearchTool for vector store search
  - PromptAgentDefinition for agent config
"""
import os
import json
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    FunctionTool,
    FileSearchTool,
)
from azure.identity import DefaultAzureCredential

load_dotenv()

project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
model = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

# -- Load vector store ID --
vs_id_file = ".vector_store_id"
if not os.path.exists(vs_id_file):
    print(f"ERROR: {vs_id_file} not found. Run upload_knowledge.py first.")
    exit(1)

with open(vs_id_file) as f:
    vector_store_id = f.read().strip()

print(f"Vector store ID: {vector_store_id}")
print("=" * 60)

# -- Check existing agents --
print("Checking existing agents...")
existing_agents = {agent.name: agent for agent in project.agents.list()}
for name in existing_agents:
    print(f"  Found: {name}")
if not existing_agents:
    print("  No existing agents found.")
print()


# ============================================================
# TOOL DEFINITIONS (using SDK model classes)
# ============================================================

check_disk_space_fn = FunctionTool(
    name="check_disk_space",
    description="Check disk space on SQL Server 2025 VM.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
)

check_target_db_fn = FunctionTool(
    name="check_target_db",
    description="Check if DB exists and its state on SQL VM.",
    parameters={
        "type": "object",
        "properties": {
            "db_name": {"type": "string", "description": "Database name"}
        },
        "required": ["db_name"],
        "additionalProperties": False,
    },
)

restore_database_fn = FunctionTool(
    name="restore_database",
    description="Restore DB on SQL VM from .bak file.",
    parameters={
        "type": "object",
        "properties": {
            "db_name": {"type": "string", "description": "Database name"},
            "backup_path": {"type": "string", "description": "Path to .bak file"},
        },
        "required": ["db_name"],
        "additionalProperties": False,
    },
)

generate_sop_fn = FunctionTool(
    name="generate_sop",
    description="Auto-generate SOP from failure context using LLM.",
    parameters={
        "type": "object",
        "properties": {
            "failure_context": {
                "type": "string",
                "description": "JSON string of failure context",
            }
        },
        "required": ["failure_context"],
        "additionalProperties": False,
    },
)

upload_sop_fn = FunctionTool(
    name="upload_sop_to_vectorstore",
    description="Upload SOP file to Foundry vector store.",
    parameters={
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Path to SOP markdown file",
            }
        },
        "required": ["filepath"],
        "additionalProperties": False,
    },
)

suggest_tool_fn = FunctionTool(
    name="suggest_tool",
    description="Analyze failure and suggest/create new Python tool.",
    parameters={
        "type": "object",
        "properties": {
            "failure_context": {
                "type": "string",
                "description": "JSON string of failure context",
            }
        },
        "required": ["failure_context"],
        "additionalProperties": False,
    },
)

file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])


# ============================================================
# AGENT INSTRUCTIONS
# ============================================================

TRIAGE_INSTRUCTIONS = (
    "You are the DBA Triage Agent for Cognizant's dbops-agent system.\n"
    "\n"
    "YOUR ROLE:\n"
    "1. Receive incoming requests (restore, health-check, incident)\n"
    "2. Classify: RESTORE | HEALTH_CHECK | INCIDENT | UNKNOWN\n"
    "3. For RESTORE requests:\n"
    "   - FIRST, review the request for logical sense. This system restores\n"
    "     FROM Azure SQL MI (production/source) TO SQL Server VM (non-production/target).\n"
    "     If the user appears to request a reverse direction (e.g., 'from destination to source',\n"
    "     'from target to production', 'from non-prod to prod', 'from VM to MI'),\n"
    "     flag this in your response and ask the user to confirm the intended direction\n"
    "     before running any checks. Do NOT route to restore agent until direction is clarified.\n"
    "   - Run check_disk_space to verify space on target VM\n"
    "   - Run check_target_db to see current DB state\n"
    "   - Consult SOPs from knowledge base\n"
    "   - If all checks PASS respond:\n"
    "     {'route_to': 'restore_agent', 'db_name': '<name>', 'checks_passed': true}\n"
    "   - If checks FAIL: explain what failed, do NOT route\n"
    "4. For other types: handle directly or explain next steps\n"
    "\n"
    "RULES: Always run checks before routing. Be concise. Reference SOP IDs."
)

RESTORE_INSTRUCTIONS = (
    "You are the DBA Restore Agent.\n"
    "\n"
    "YOUR ROLE:\n"
    "1. Receive validated restore requests from Triage Agent\n"
    "2. Execute restore_database tool\n"
    "3. Validate with check_target_db post-restore\n"
    "4. Return structured report:\n"
    "   {'operation': 'RESTORE', 'db_name': '<name>', 'status': 'SUCCESS/FAILED', 'db_state': '<state>'}\n"
    "\n"
    "RULES: Only execute if checks_passed=true. Always validate post-restore. Be concise."
)

LEARNING_INSTRUCTIONS = (
    "You are the DBA Learning Agent -- the self-improving component of dbops-agent.\n"
    "\n"
    "TRIGGERED WHEN: An operation FAILS (or on-demand for review).\n"
    "\n"
    "YOUR STEPS:\n"
    "1. ANALYZE root cause from the error and context\n"
    "2. GENERATE SOP -- call generate_sop with failure context JSON\n"
    "3. UPLOAD SOP -- call upload_sop_to_vectorstore with the new SOP file path\n"
    "   (All agents can then find this fix in future operations)\n"
    "4. SUGGEST TOOL -- call suggest_tool to check if a new Python tool could prevent this\n"
    "   If created, flag for human review (never auto-deploy)\n"
    "5. RETURN learning report:\n"
    "   {\n"
    "     'learning_triggered_by': '<failed operation>',\n"
    "     'sop_generated': '<SOP-ID>',\n"
    "     'sop_uploaded': true/false,\n"
    "     'new_tool_suggested': true/false,\n"
    "     'tool_name': '<if created>',\n"
    "     'summary': '<what was learned>'\n"
    "   }\n"
    "\n"
    "PURPOSE: Every failure makes the system smarter. Without this agent, the same failure\n"
    "produces the same result. With it, the system already has the fix next time.\n"
    "\n"
    "RULES: Always generate SOP. Always try suggest_tool. Flag new tools for human review."
)


# ============================================================
# CREATE / UPDATE AGENTS
# ============================================================

def create_or_update_agent(agent_name, instructions, tools, description):
    """Create a new agent or update existing one. Returns agent details."""
    action = "Updating" if agent_name in existing_agents else "Creating"
    print(f"{action} agent: {agent_name}...")

    result = project.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=model,
            instructions=instructions,
            tools=tools,
        ),
        description=description,
    )

    print(f"  Name: {result.name}")
    print(f"  Version: {result.version}")
    print(f"  Status: {result.status}")
    print()
    return result


# Agent 1: Triage
triage = create_or_update_agent(
    agent_name="DBA-Triage-Agent",
    instructions=TRIAGE_INSTRUCTIONS,
    tools=[check_disk_space_fn, check_target_db_fn, file_search_tool],
    description="DBA Triage Agent -- classifies requests, validates direction, runs pre-checks",
)

# Agent 2: Restore
restore = create_or_update_agent(
    agent_name="DBA-Restore-Agent",
    instructions=RESTORE_INSTRUCTIONS,
    tools=[restore_database_fn, check_target_db_fn, file_search_tool],
    description="DBA Restore Agent -- executes and validates restores",
)

# Agent 3: Learning
learning = create_or_update_agent(
    agent_name="DBA-Learning-Agent",
    instructions=LEARNING_INSTRUCTIONS,
    tools=[generate_sop_fn, upload_sop_fn, suggest_tool_fn, file_search_tool],
    description="DBA Learning Agent -- learns from failures and creates SOPs",
)


# ============================================================
# SAVE AGENT INFO
# ============================================================

agent_info = {
    "triage": {"name": triage.name, "version": triage.version, "id": triage.id},
    "restore": {"name": restore.name, "version": restore.version, "id": restore.id},
    "learning": {"name": learning.name, "version": learning.version, "id": learning.id},
    "vector_store_id": vector_store_id,
    "model": model,
}

with open(".agent_ids_v2.json", "w") as f:
    json.dump(agent_info, f, indent=2)

print("=" * 60)
print("Agent info saved to .agent_ids_v2.json")
print(json.dumps(agent_info, indent=2))
print()

# Verify no duplicates
print("Verifying no duplicate agents...")
final_agents = list(project.agents.list())
from collections import Counter
name_counts = Counter(a.name for a in final_agents)
duplicates = {n: c for n, c in name_counts.items() if c > 1}
if duplicates:
    print("WARNING: Duplicate agents detected:")
    for name, count in duplicates.items():
        print(f"  {name}: {count} instances")
else:
    print(f"  All clean. {len(final_agents)} agents, no duplicates.")

print()
print("=" * 60)
print("  Agent setup complete (v1.1)")
print()
print("  1. DBA-Triage-Agent    -- Classify, validate direction, pre-checks")
print("  2. DBA-Restore-Agent   -- Execute and validate restores")
print("  3. DBA-Learning-Agent  -- Learn from failures, generate SOPs")
print()
print(f"  Vector store: {vector_store_id}")
print(f"  Model: {model}")
print()
print("  Runtime: project.get_openai_client(agent_name=...)")
print("  Protocol: Responses API")
print("=" * 60)
