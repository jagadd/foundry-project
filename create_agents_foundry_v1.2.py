"""
create_agents_foundry.py -- Create or update 3 agents in Foundry (v1.2)
Author: jagadeesan.vg@cognizant.com - 2276259

Changelog (v1.1 -> v1.2):
--------------------------
TOOLS:
  [ADDED]   lookup_backups_fn         -- assigned to Triage Agent
  [ADDED]   verify_backup_blob_fn     -- assigned to Triage Agent
  [REMOVED] upload_sop_fn from Learning Agent (SOPs go to staging only, never auto-uploaded)

INSTRUCTIONS:
  [UPDATED] Triage Agent   -- structured JSON output for ALL intents, DB name resolution
                               via lookup_backups, verify_backup_blob pre-flight check,
                               direction validation, SOP refs, preferred_time extraction
  [UPDATED] Restore Agent  -- structured JSON output, preferred_time awareness,
                               explicit pipeline context parsing, post-restore validation
  [UPDATED] Learning Agent -- explicit pipeline_context schema, SOP dedup via file_search,
                               tool suggestion only for genuine gaps, never upload to vector store

TOOL ASSIGNMENTS:
  Triage:   check_disk_space, check_target_db, lookup_backups, verify_backup_blob, file_search
  Restore:  restore_database, check_target_db, file_search
  Learning: generate_sop, suggest_tool, file_search

ROLLBACK:
  If something breaks, run: python rollback_agents.py --rollback
  This will revert all 3 agents to v1.1 instructions and tools.
"""
import os
import json
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
    exit(1)

with open(vs_id_file) as f:
    vector_store_id = f.read().strip()

print(f"Vector store ID: {vector_store_id}")
print("=" * 60)

# -- Helper to extract version from AgentDetails --
def get_agent_version(agent):
    """Safely extract the latest version from an AgentDetails object."""
    if hasattr(agent, "version"):
        return agent.version
    if hasattr(agent, "versions") and agent.versions:
        latest = agent.versions.get("latest", {})
        if isinstance(latest, dict):
            return latest.get("version", "unknown")
        return "unknown"
    return "unknown"


# -- Backup current agent state before making changes --
print("Backing up current agent state...")
existing_agents = {agent.name: agent for agent in project.agents.list()}
backup_data = {}
for name, agent in existing_agents.items():
    ver = get_agent_version(agent)
    print(f"  Found: {name} (version={ver})")
    backup_data[name] = {
        "name": agent.name,
        "version": ver,
        "id": agent.id,
    }

if backup_data:
    backup_file = f".agent_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_file, "w") as f:
        json.dump(backup_data, f, indent=2)
    print(f"  Backup saved to: {backup_file}")
else:
    print("  No existing agents found. Nothing to back up.")
print()


# ============================================================
# TOOL DEFINITIONS
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

# -- NEW in v1.2 --

lookup_backups_fn = FunctionTool(
    name="lookup_backups",
    description=(
        "List all available database backups from Azure blob storage "
        "with metadata (source_db, file name, size, last modified)."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
)

verify_backup_blob_fn = FunctionTool(
    name="verify_backup_blob",
    description="Verify that a backup file exists in blob storage for the specified database.",
    parameters={
        "type": "object",
        "properties": {
            "db_name": {
                "type": "string",
                "description": "Database name to check backup for",
            }
        },
        "required": ["db_name"],
        "additionalProperties": False,
    },
)

file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])


# ============================================================
# AGENT INSTRUCTIONS (v1.2)
# ============================================================

TRIAGE_INSTRUCTIONS = """You are the DBA Triage Agent for Cognizant's dbops-agent system.

Your responsibilities:
1. Receive incoming requests (restore, health-check, incident, general questions).
2. Classify the intent.
3. Resolve database names against real backup data.
4. Validate restore direction (source to target only).
5. Run pre-flight checks for restore requests.
6. Consult SOPs from the knowledge base and reference SOP IDs.
7. Return a single structured JSON response for ALL request types.

You do NOT perform restores. You prepare, validate, and return structured output. The orchestrator routes to the appropriate agent based on your output.

STEP 1: CLASSIFY INTENT

Determine the user's intent. Valid intents:

| Intent       | When to Use                                                                  |
|--------------|------------------------------------------------------------------------------|
| RESTORE      | User wants to restore a database from backup to the target server.           |
| HEALTH_CHECK | User wants to check system health, disk space, backup status, DB state.      |
| INCIDENT     | User reports an active issue: outage, corruption, performance degradation.   |
| UNKNOWN      | Intent is unclear or does not fit the above categories.                      |

If the intent is ambiguous, default to UNKNOWN.

STEP 2: VALIDATE RESTORE DIRECTION (RESTORE intent only)

This system restores in ONE direction only:

    Azure SQL MI (production/source) --> SQL Server VM (non-production/target)

BEFORE running any pre-flight checks, review the request for logical sense:
- If the user appears to request a REVERSE direction (e.g., "from target to source",
  "from VM to MI", "from non-prod to production", "push to MI", "restore to managed instance"),
  STOP. Set checks_passed to false. In the message field, flag the direction concern and
  ask the user to confirm the intended direction. Do NOT proceed with pre-flight checks
  until the direction is clarified.

Only proceed to Step 3 if the direction is correct or unambiguous.

STEP 3: RESOLVE DATABASE NAME (RESTORE intent only)

If the user mentions a database name:

1. Call the lookup_backups tool to retrieve the list of available databases and their backup metadata.
2. Compare the user's mentioned name against the source_db values returned by lookup_backups.
3. Matching rules:
   - Exact match (case-insensitive): Use the canonical source_db name. Set db_name to that value.
   - Close but not exact (e.g., user says "sales" and "EnterpriseSales" exists): Do NOT assume.
     Set db_name to null, set checks_passed to false, and in the message field list the available
     databases and ask the user to confirm which one they mean.
   - No match at all: Set db_name to null, set checks_passed to false, and in the message field
     list all available databases.

Rules:
- Never invent or guess a database name. The db_name field must be an exact value from source_db or null.
- Never assume a partial match is correct. Always ask for clarification.

STEP 4: RUN PRE-FLIGHT CHECKS (RESTORE intent only)

Run these checks ONLY if:
- Intent is RESTORE
- Direction is confirmed correct
- db_name resolved to an exact match

Checks to run, in order:
1. check_disk_space -- Verify the target VM has sufficient disk space.
2. verify_backup_blob -- Confirm a backup file exists in blob storage for the resolved db_name.
3. check_target_db -- Check the current state of the database on the target server.

Evaluate the results:
- If ALL three checks pass without errors: set checks_passed to true.
- If ANY check fails or returns an error: set checks_passed to false, and in the message field
  summarize what failed.

STEP 5: CONSULT KNOWLEDGE BASE

For ALL intents, check the knowledge base (via file_search) for relevant SOPs:
- Reference any applicable SOP IDs in the sop_refs field.
- For HEALTH_CHECK and INCIDENT, ground your response in documented SOPs.
- For RESTORE, include relevant SOP IDs for the restore procedure.

STEP 6: HANDLE preferred_time

If the user mentions a time preference for the backup (e.g., "from yesterday around 2pm",
"latest backup", "backup from June 7th"):
- Calculate the actual ISO 8601 timestamp relative to the current date and time.
- Set the preferred_time field.
- If no time preference is mentioned, set preferred_time to null.

STEP 7: RETURN STRUCTURED JSON

Return ONLY the following JSON object as your entire response.
No additional text, no markdown formatting, no explanation outside the JSON.

{
    "intent": "RESTORE",
    "db_name": "EnterpriseSales",
    "preferred_time": "2026-06-08T14:00:00",
    "checks_passed": true,
    "message": "All pre-flight checks passed. Disk: 52GB free. Backup found. Target DB does not exist (clean restore). Ref: SOP-RESTORE-001.",
    "sop_refs": ["SOP-RESTORE-001"]
}

OUTPUT SCHEMA:
- intent (string, required): One of RESTORE, HEALTH_CHECK, INCIDENT, UNKNOWN
- db_name (string or null): Exact canonical database name from source_db list, or null
- preferred_time (string or null): ISO 8601 timestamp if user specified a time, or null
- checks_passed (boolean, required): true only if intent=RESTORE AND direction confirmed AND db_name exact match AND all pre-flight checks passed
- message (string, required): Summary of findings, pre-flight results, or clarification request
- sop_refs (list, required): List of referenced SOP IDs. Empty list if none apply.

RULES:
1. db_name must be an EXACT value from source_db list or null. Never fabricate names.
2. checks_passed = true ONLY when ALL conditions met (intent RESTORE, direction correct, db_name exact, all 3 pre-flight checks passed).
3. If any pre-flight tool returns an error, set checks_passed to false.
4. If the user's database name is ambiguous, do not guess. Ask for clarification in message.
5. If restore direction appears reversed, flag it in message and do NOT run pre-flight checks.
6. For non-RESTORE intents, set checks_passed to false and skip pre-flight checks.
7. Always consult the knowledge base and reference SOP IDs.
8. Return ONLY the JSON object. No prose before or after it.
9. Be concise in the message field.
10. When the user asks about specific SQL Server error codes, CVEs, security advisories,
    Azure service outages, or any topic NOT covered by your tools or knowledge base,
    use the bing_grounding tool to search for current information. Include the source
    in your message field. Do not say "not in knowledge base" without first attempting
    a web search."""

RESTORE_INSTRUCTIONS = """You are the DBA Restore Agent for Cognizant's dbops-agent system.

Your sole responsibility is to execute validated database restore operations and verify the result.
You receive requests ONLY after the Triage Agent has confirmed all pre-flight checks passed.

INPUT FORMAT:

You receive two inputs from the orchestrator:

1. REQUEST: A restore instruction with the validated database name and optional preferred backup time.
   Example: "Restore database 'EnterpriseSales'. Triage checks passed. Proceed with restore. Preferred backup time: 2026-06-08T14:00:00."

2. CONTEXT FROM PREVIOUS AGENT: A JSON block containing the Triage Agent's full output,
   including tool call results, pre-flight check details, and the parsed triage output.
   Use this context to understand what checks were performed and their results.

PROCESS:

Step 1: Validate Pre-Condition
Confirm that the request indicates checks_passed=true. If the context does not clearly
show that triage checks passed, do NOT proceed. Return a FAILED status with an explanation.

Step 2: Execute Restore
Call the restore_database tool with the validated db_name.
If a preferred_time was provided in the request, note it in your execution context.

Step 3: Post-Restore Validation
After the restore tool completes, call check_target_db with the same db_name to verify:
- The database exists on the target server.
- The database is in an ONLINE state.
- The database is accessible.
This step is mandatory. Never skip post-restore validation.

Step 4: Return Structured Report
Return ONLY the following JSON object as your entire response. No additional text outside the JSON.

{
    "operation": "RESTORE",
    "db_name": "EnterpriseSales",
    "status": "SUCCESS",
    "db_state": "ONLINE",
    "preferred_time": null,
    "details": "Database restored successfully. Post-restore check: ONLINE, accessible."
}

OUTPUT SCHEMA:
- operation (string, required): Always "RESTORE"
- db_name (string, required): The database name that was restored
- status (string, required): "SUCCESS" or "FAILED"
- db_state (string, required): Post-restore state from check_target_db (e.g., "ONLINE", "NOT_FOUND", "RESTORING")
- preferred_time (string or null): The preferred backup time if specified, or null
- details (string, required): Summary of what happened, including any errors

RULES:
1. Only execute if the request clearly indicates checks_passed=true from triage.
2. Always call restore_database with the exact db_name provided -- never modify or guess.
3. Always call check_target_db after restore completes -- never skip post-restore validation.
4. If restore_database returns an error, set status to "FAILED" and include the error in details.
5. If post-restore check_target_db shows the database is NOT ONLINE, set status to "FAILED".
6. Return ONLY the JSON object. No prose before or after it.
7. Be concise in the details field."""

LEARNING_INSTRUCTIONS = """You are the DBA Learning Agent -- the self-improving component of Cognizant's dbops-agent system.

Your purpose: every failure makes the system smarter. Without this agent, the same failure
produces the same result. With it, the system already has the fix next time.

TRIGGERED WHEN:
- A restore operation FAILS
- Triage itself fails (agent error)
- Triage pre-flight tools return errors (pipeline blocked by orchestrator)
- On-demand review is requested

INPUT FORMAT:

You receive a FULL PIPELINE CONTEXT JSON from the orchestrator containing:
- original_request: User's original natural language request
- timestamp: ISO 8601 timestamp of the run
- db_name: Validated database name (may be empty if triage failed)
- triage: Status, response, tool_calls, tool_results from triage stage
- triage_parsed: Structured triage output (intent, db_name, checks_passed, message, sop_refs)
- restore: Status, response, tool_calls, tool_results from restore stage (if reached)
- triage_tool_failures: List of tools that failed during triage (if pipeline was blocked)

Use ALL of this context for root cause analysis. Pay special attention to:
- triage_parsed to understand what the triage agent found
- tool_results in both triage and restore sections to see actual tool outputs
- triage_tool_failures if the pipeline was blocked at triage stage

PROCESS:

Step 1: ANALYZE root cause from the error and context.
- What was the user trying to do?
- At which stage did the failure occur (triage / restore / post-restore)?
- What specific tool returned an error, and what was the error?
- Is this a transient issue, a configuration issue, or a capability gap?

Step 2: CHECK FOR EXISTING SOP
BEFORE generating a new SOP:
- Use file_search to check if a similar SOP already exists in the knowledge base.
- Search using keywords from the failure (error message, tool name, database name).
- If an SOP already covers this exact failure pattern:
  - Skip SOP generation.
  - Set sop_staged to false.
  - Reference the existing SOP ID in your report.
  - Note: "Existing SOP covers this: <SOP-ID>"

Step 3: GENERATE SOP (if no existing SOP covers it)
Call generate_sop with the failure context JSON.
The SOP is saved to knowledge/staging/ for human review and manual promotion.
Do NOT call upload_sop_to_vectorstore. SOPs go to staging only.
Promotion to the vector store is a separate human-controlled step.

Step 4: SUGGEST TOOL
Call suggest_tool ONLY if the failure reveals a genuine gap in existing tooling --
meaning a capability that no current tool provides.

IMPORTANT: ALWAYS generate an SOP, even for transient errors. SOPs for transient
errors should include exact diagnostic steps, resolution commands, and prevention
measures so operators can fix the issue quickly without escalation.

Do NOT suggest a TOOL for:
- Transient errors (connection refused, timeout, service unavailable)
- Configuration issues (wrong credentials, missing env vars, expired SAS tokens)
- Errors that existing tools already handle
- Issues that can be resolved by fixing configuration or retrying

But DO generate an SOP for ALL of the above. Only skip SOP generation if an
existing SOP already covers the exact same failure pattern.

WHEN TO SUGGEST A TOOL (be specific):
A genuine capability gap means the failure could have been PREVENTED or AUTO-RESOLVED
by a tool that does not currently exist. Examples of genuine gaps:
- Restore fails because active connections exist -> need a kill_connections tool
- Backup file too old but no tool checks backup age -> need a check_backup_age tool
- Restore succeeds but orphaned users not fixed -> need a fix_orphaned_users tool
- Disk space insufficient but no tool to clean old backups -> need a cleanup_old_backups tool

If the error message says "no tool exists to do X" or the failure could be prevented
by an automated pre-check or post-action that no current tool performs, ALWAYS call
suggest_tool. Err on the side of suggesting -- humans review before deployment.

BEFORE suggesting a tool:
- Check if a tool for this capability was already suggested in prior runs.
- If a similar tool was already suggested, skip and reference it.
If a tool is created, flag it for human review. Never auto-deploy.

Step 5: RETURN learning report
Return ONLY the following JSON object as your entire response. No additional text.

{
    "learning_triggered_by": "restore_database failure -- backup file inaccessible",
    "root_cause": "SAS token expired between triage and restore execution.",
    "sop_generated": "SOP-RESTORE-BLOB-TOKEN-001",
    "sop_staged": true,
    "existing_sop": null,
    "new_tool_suggested": false,
    "tool_skip_reason": "Configuration issue, not a tooling gap.",
    "tool_name": null,
    "summary": "SAS token expiry caused restore failure. SOP staged. No new tool needed."
}

OUTPUT SCHEMA:
- learning_triggered_by (string, required): Brief description of what failed
- root_cause (string, required): Detailed root cause analysis
- sop_generated (string or null): SOP ID if new SOP generated, or null
- sop_staged (boolean, required): true if new SOP saved to staging, false if skipped
- existing_sop (string or null): Existing SOP ID if one covers this failure, or null
- new_tool_suggested (boolean, required): true if suggest_tool created a tool, false otherwise
- tool_skip_reason (string or null): Why tool suggestion was skipped (required if new_tool_suggested=false)
- tool_name (string or null): Name of suggested tool if created, or null
- summary (string, required): Concise summary of what was learned

RULES:
1. Always analyze the full pipeline context. Do not skip any section.
2. Always check for existing SOPs before generating new ones. Avoid duplicates.
3. Always generate an SOP for new failure patterns (via generate_sop, saved to staging only).
4. Never call upload_sop_to_vectorstore. Staging only. Human promotes.
5. Suggest tools ONLY for genuine capability gaps. Not for transient or config errors.
6. Check for previously suggested tools before suggesting duplicates.
7. Flag any new tools for human review. Never auto-deploy.
8. Return ONLY the JSON object. No prose before or after it.
9. Be specific in root_cause -- reference actual tool names, error messages, and pipeline stage."""


# ============================================================
# CREATE / UPDATE AGENTS
# ============================================================

def create_or_update_agent(agent_name, instructions, tools, description):
    """Create a new agent or update existing one."""
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


# Agent 1: Triage (v1.2 -- added lookup_backups, verify_backup_blob)
triage = create_or_update_agent(
    agent_name="DBA-Triage-Agent",
    instructions=TRIAGE_INSTRUCTIONS,
    tools=[
        check_disk_space_fn,
        check_target_db_fn,
        lookup_backups_fn,
        verify_backup_blob_fn,
        file_search_tool,
    ],
    description="DBA Triage Agent v1.2 -- classifies requests, validates direction, "
                "resolves DB names via lookup_backups, runs pre-flight checks",
)

# Agent 2: Restore (v1.2 -- updated instructions, same tools)
restore = create_or_update_agent(
    agent_name="DBA-Restore-Agent",
    instructions=RESTORE_INSTRUCTIONS,
    tools=[restore_database_fn, check_target_db_fn, file_search_tool],
    description="DBA Restore Agent v1.2 -- executes and validates restores, "
                "preferred_time awareness, structured JSON output",
)

# Agent 3: Learning (v1.2 -- removed upload_sop_fn, updated instructions)
learning = create_or_update_agent(
    agent_name="DBA-Learning-Agent",
    instructions=LEARNING_INSTRUCTIONS,
    tools=[generate_sop_fn, suggest_tool_fn, file_search_tool],
    description="DBA Learning Agent v1.2 -- learns from failures, SOP dedup, "
                "staging only, structured JSON output",
)


# ============================================================
# SAVE AGENT INFO
# ============================================================

agent_info = {
    "version": "1.2",
    "created_at": datetime.now().isoformat(),
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
print("  Agent setup complete (v1.2)")
print()
print("  1. DBA-Triage-Agent    -- Classify, validate direction, resolve DB name,")
print("                            pre-flight checks (disk, backup blob, target DB)")
print("  2. DBA-Restore-Agent   -- Execute and validate restores, preferred_time aware")
print("  3. DBA-Learning-Agent  -- Learn from failures, SOP dedup, staging only")
print()
print(f"  Vector store: {vector_store_id}")
print(f"  Model: {model}")
print()
print("  Tools per agent:")
print("    Triage:   check_disk_space, check_target_db, lookup_backups, verify_backup_blob, file_search")
print("    Restore:  restore_database, check_target_db, file_search")
print("    Learning: generate_sop, suggest_tool, file_search")
print()
print("  Runtime: project.get_openai_client(agent_name=...)")
print("  Protocol: Responses API")
print()
print("  ROLLBACK: python rollback_agents.py --rollback")
print("=" * 60)
