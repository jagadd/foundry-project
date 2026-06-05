"""
create_agents.py – Phase 4: Create 3 agents in Foundry
Author: jagadeesan.vg@cognizant.com - 2276259
"""
import os, json
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FileSearchTool
from azure.identity import DefaultAzureCredential
load_dotenv()

client = AgentsClient(endpoint=os.getenv("PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
model = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4-1-mini")

with open(".vector_store_id") as f:
    vector_store_id = f.read().strip()

file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])

# ── Function Schemas ──
check_disk_space_fn = {"type":"function","function":{"name":"check_disk_space",
    "description":"Check disk space on SQL Server 2025 VM.",
    "parameters":{"type":"object","properties":{},"required":[]}}}

check_target_db_fn = {"type":"function","function":{"name":"check_target_db",
    "description":"Check if DB exists and its state on SQL VM.",
    "parameters":{"type":"object","properties":{
        "db_name":{"type":"string","description":"Database name"}},
    "required":["db_name"]}}}

restore_database_fn = {"type":"function","function":{"name":"restore_database",
    "description":"Restore DB on SQL VM from .bak file.",
    "parameters":{"type":"object","properties":{
        "db_name":{"type":"string","description":"Database name"},
        "backup_path":{"type":"string","description":"Path to .bak file"}},
    "required":["db_name"]}}}

generate_sop_fn = {"type":"function","function":{"name":"generate_sop",
    "description":"Auto-generate SOP from failure context using LLM.",
    "parameters":{"type":"object","properties":{
        "failure_context":{"type":"string","description":"JSON string of failure context"}},
    "required":["failure_context"]}}}

upload_sop_fn = {"type":"function","function":{"name":"upload_sop_to_vectorstore",
    "description":"Upload SOP file to Foundry vector store.",
    "parameters":{"type":"object","properties":{
        "filepath":{"type":"string","description":"Path to SOP markdown file"}},
    "required":["filepath"]}}}

suggest_tool_fn = {"type":"function","function":{"name":"suggest_tool",
    "description":"Analyze failure and suggest/create new Python tool.",
    "parameters":{"type":"object","properties":{
        "failure_context":{"type":"string","description":"JSON string of failure context"}},
    "required":["failure_context"]}}}

# ══════════════════════════════════════════
#  AGENT 1: TRIAGE
# ══════════════════════════════════════════
print("Creating Triage Agent...")
triage = client.create_agent(
    model=model,
    name="DBA-Triage-Agent",
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
    tools=[check_disk_space_fn, check_target_db_fn] + file_search_tool.definitions,
    tool_resources=file_search_tool.resources,
)
print(f"✅ Triage Agent: {triage.id}")

# ══════════════════════════════════════════
#  AGENT 2: RESTORE
# ══════════════════════════════════════════
print("Creating Restore Agent...")
restore = client.create_agent(
    model=model,
    name="DBA-Restore-Agent",
    instructions="""You are the DBA Restore Agent.

YOUR ROLE:
1. Receive validated restore requests from Triage Agent
2. Execute restore_database tool
3. Validate with check_target_db post-restore
4. Return structured report:
   {"operation": "RESTORE", "db_name": "<>", "status": "SUCCESS/FAILED", "db_state": "<>"}

RULES: Only execute if checks_passed=true. Always validate post-restore. Be concise.""",
    tools=[restore_database_fn, check_target_db_fn] + file_search_tool.definitions,
    tool_resources=file_search_tool.resources,
)
print(f"✅ Restore Agent: {restore.id}")

# ══════════════════════════════════════════
#  AGENT 3: LEARNING 🧠
# ══════════════════════════════════════════
print("Creating Learning Agent...")
learning = client.create_agent(
    model=model,
    name="DBA-Learning-Agent",
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
    tools=[generate_sop_fn, upload_sop_fn, suggest_tool_fn] + file_search_tool.definitions,
    tool_resources=file_search_tool.resources,
)
print(f"✅ Learning Agent: {learning.id}")

# ── Save IDs ──
agent_ids = {
    "triage_agent_id": triage.id,
    "restore_agent_id": restore.id,
    "learning_agent_id": learning.id,
}
with open(".agent_ids.json", "w") as f:
    json.dump(agent_ids, f, indent=2)

print(f"\n📄 Saved to .agent_ids.json")
print(json.dumps(agent_ids, indent=2))
print("""
╔══════════════════════════════════════════════════════╗
║  🎯 Phase 4 Complete — 3 Agents Created!             ║
║                                                      ║
║  1. DBA-Triage-Agent   → Classify & Route            ║
║  2. DBA-Restore-Agent  → Execute & Validate          ║
║  3. DBA-Learning-Agent → Learn & Improve 🧠          ║
║                                                      ║
║  Next → Phase 5: orchestrator.py                     ║
╚══════════════════════════════════════════════════════╝
""")
