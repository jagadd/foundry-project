"""
rollback_agents.py -- Rollback agents to v1.1 or inspect current state
Author: jagadeesan.vg@cognizant.com - 2276259

Usage:
    python rollback_agents.py --list       # List current agents and versions
    python rollback_agents.py --backup     # Save current agent state to backup file
    python rollback_agents.py --rollback   # Revert all 3 agents to v1.1 instructions and tools

WARNING: --rollback will overwrite current agent instructions and tool assignments
         with the original v1.1 definitions. Use only if v1.2 deployment caused issues.
"""
import os
import sys
import json
import argparse
from datetime import datetime
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

vs_id_file = ".vector_store_id"
if not os.path.exists(vs_id_file):
    print(f"ERROR: {vs_id_file} not found.")
    sys.exit(1)

with open(vs_id_file) as f:
    vector_store_id = f.read().strip()


# ============================================================
# v1.1 TOOL DEFINITIONS (original)
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
# v1.1 INSTRUCTIONS (original -- exact copy from create_agents_foundry.py v1.1)
# ============================================================

TRIAGE_INSTRUCTIONS_V11 = """You are the DBA Triage Agent for Cognizant's dbops-agent system.

YOUR ROLE:
1. Receive incoming requests (restore, health-check, incident)
2. Classify: RESTORE | HEALTH_CHECK | INCIDENT | UNKNOWN
3. For RESTORE requests:
   - FIRST, review the request for logical sense. This system restores
     FROM Azure SQL MI (production/source) TO SQL Server VM (non-production/target).
     If the user appears to request a reverse direction (e.g., "from destination to source",
     "from target to production", "from non-prod to prod", "from VM to MI"),
     flag this in your response and ask the user to confirm the intended direction
     before running any checks. Do NOT route to restore agent until direction is clarified.
   - Run check_disk_space to verify space on target VM
   - Run check_target_db to see current DB state
   - Consult SOPs from knowledge base
   - If all checks PASS respond:
     {"route_to": "restore_agent", "db_name": "<name>", "checks_passed": true}
   - If checks FAIL: explain what failed, do NOT route
4. For other types: handle directly or explain next steps

RULES: Always run checks before routing. Be concise. Reference SOP IDs."""

RESTORE_INSTRUCTIONS_V11 = """You are the DBA Restore Agent.

YOUR ROLE:
1. Receive validated restore requests from Triage Agent
2. Execute restore_database tool
3. Validate with check_target_db post-restore
4. Return structured report:
   {"operation": "RESTORE", "db_name": "<name>", "status": "SUCCESS/FAILED", "db_state": "<state>"}

RULES: Only execute if checks_passed=true. Always validate post-restore. Be concise."""

LEARNING_INSTRUCTIONS_V11 = """You are the DBA Learning Agent -- the self-improving component of dbops-agent.

TRIGGERED WHEN: An operation FAILS (or on-demand for review).

YOUR STEPS:
1. ANALYZE root cause from the error and context
2. GENERATE SOP -- call generate_sop with failure context JSON
3. UPLOAD SOP -- call upload_sop_to_vectorstore with the new SOP file path
   (All agents can then find this fix in future operations)
4. SUGGEST TOOL -- call suggest_tool to check if a new Python tool could prevent this
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

PURPOSE: Every failure makes the system smarter. Without this agent, the same failure
produces the same result. With it, the system already has the fix next time.

RULES: Always generate SOP. Always try suggest_tool. Flag new tools for human review."""


# ============================================================
# FUNCTIONS
# ============================================================

def get_agent_version(agent):
    """Safely extract the latest version from an AgentDetails object.
    agent.versions is a dict-like AgentObjectVersions with a 'latest' key.
    agent.versions['latest'] is a dict with 'version', 'status', etc.
    """
    try:
        return agent.versions["latest"]["version"]
    except (KeyError, TypeError, AttributeError):
        pass
    if hasattr(agent, "version"):
        return agent.version
    return "unknown"


def list_agents():
    """List all current agents with version info."""
    print("=" * 60)
    print("  Current Agents")
    print("=" * 60)
    agents = list(project.agents.list())
    if not agents:
        print("  No agents found.")
        return

    for agent in agents:
        ver = get_agent_version(agent)
        print(f"  Name:    {agent.name}")
        print(f"  Version: {ver}")
        print(f"  ID:      {agent.id}")
        print(f"  Status:  {agent.versions.get('latest', {}).get('status', 'unknown')}")
        print()

    print(f"  Total: {len(agents)} agents")
    print("=" * 60)

    # Also check .agent_ids_v2.json
    if os.path.exists(".agent_ids_v2.json"):
        with open(".agent_ids_v2.json") as f:
            saved = json.load(f)
        print()
        print("  Saved agent info (.agent_ids_v2.json):")
        print(f"    Version: {saved.get('version', 'unknown')}")
        print(f"    Created: {saved.get('created_at', 'unknown')}")
        for key in ["triage", "restore", "learning"]:
            if key in saved:
                print(f"    {key}: name={saved[key].get('name')}, version={saved[key].get('version')}")


def backup_agents():
    """Save current agent state to a backup file."""
    agents = list(project.agents.list())
    backup_data = {
        "backup_date": datetime.now().isoformat(),
        "agents": [],
    }
    for agent in agents:
        ver = get_agent_version(agent)
        backup_data["agents"].append({
            "name": agent.name,
            "version": ver,
            "id": agent.id,
            "status": str(agent.versions.get('latest', {}).get('status', 'unknown')),
        })

    backup_file = f".agent_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_file, "w") as f:
        json.dump(backup_data, f, indent=2)

    print(f"  Backup saved to: {backup_file}")
    print(f"  Agents backed up: {len(backup_data['agents'])}")
    for a in backup_data["agents"]:
        print(f"    {a['name']} (version={a['version']})")


def rollback():
    """Revert all 3 agents to v1.1 instructions and tools."""
    print("=" * 60)
    print("  ROLLBACK TO v1.1")
    print("=" * 60)
    print()

    # Safety: backup current state first
    print("  Step 1: Backing up current state before rollback...")
    backup_agents()
    print()

    # Confirm
    print("  WARNING: This will overwrite all 3 agents with v1.1 instructions and tools.")
    print("  Changes:")
    print("    Triage:   Remove lookup_backups, verify_backup_blob. Revert instructions.")
    print("    Restore:  Revert instructions to v1.1.")
    print("    Learning: Re-add upload_sop_fn. Revert instructions to v1.1.")
    print()

    confirm = input("  Type 'ROLLBACK' to confirm: ").strip()
    if confirm != "ROLLBACK":
        print("  Cancelled.")
        return

    print()
    existing_agents = {agent.name: agent for agent in project.agents.list()}

    # Triage -- v1.1 tools (no lookup_backups, no verify_backup_blob)
    print("  Rolling back DBA-Triage-Agent...")
    triage = project.agents.create_version(
        agent_name="DBA-Triage-Agent",
        definition=PromptAgentDefinition(
            model=model,
            instructions=TRIAGE_INSTRUCTIONS_V11,
            tools=[check_disk_space_fn, check_target_db_fn, file_search_tool],
        ),
        description="DBA Triage Agent v1.1 -- ROLLED BACK",
    )
    print(f"    Done. Version: {triage.version}")

    # Restore -- v1.1
    print("  Rolling back DBA-Restore-Agent...")
    restore = project.agents.create_version(
        agent_name="DBA-Restore-Agent",
        definition=PromptAgentDefinition(
            model=model,
            instructions=RESTORE_INSTRUCTIONS_V11,
            tools=[restore_database_fn, check_target_db_fn, file_search_tool],
        ),
        description="DBA Restore Agent v1.1 -- ROLLED BACK",
    )
    print(f"    Done. Version: {restore.version}")

    # Learning -- v1.1 (includes upload_sop_fn)
    print("  Rolling back DBA-Learning-Agent...")
    learning = project.agents.create_version(
        agent_name="DBA-Learning-Agent",
        definition=PromptAgentDefinition(
            model=model,
            instructions=LEARNING_INSTRUCTIONS_V11,
            tools=[generate_sop_fn, upload_sop_fn, suggest_tool_fn, file_search_tool],
        ),
        description="DBA Learning Agent v1.1 -- ROLLED BACK",
    )
    print(f"    Done. Version: {learning.version}")

    # Save rolled-back info
    agent_info = {
        "version": "1.1-rollback",
        "rolled_back_at": datetime.now().isoformat(),
        "triage": {"name": triage.name, "version": triage.version, "id": triage.id},
        "restore": {"name": restore.name, "version": restore.version, "id": restore.id},
        "learning": {"name": learning.name, "version": learning.version, "id": learning.id},
        "vector_store_id": vector_store_id,
        "model": model,
    }

    with open(".agent_ids_v2.json", "w") as f:
        json.dump(agent_info, f, indent=2)

    print()
    print("=" * 60)
    print("  ROLLBACK COMPLETE")
    print()
    print("  All 3 agents reverted to v1.1 instructions and tools.")
    print("  Agent info saved to .agent_ids_v2.json (version: 1.1-rollback)")
    print()
    print("  To verify: python rollback_agents.py --list")
    print("  To re-apply v1.2: python create_agents_foundry_v1.2.py")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Rollback agents to v1.1 or inspect current state"
    )
    parser.add_argument("--list", action="store_true", help="List current agents and versions")
    parser.add_argument("--backup", action="store_true", help="Save current agent state to backup file")
    parser.add_argument("--rollback", action="store_true", help="Revert all 3 agents to v1.1")

    args = parser.parse_args()

    if not any([args.list, args.backup, args.rollback]):
        parser.print_help()
        return

    if args.list:
        list_agents()

    if args.backup:
        backup_agents()

    if args.rollback:
        rollback()


if __name__ == "__main__":
    main()
