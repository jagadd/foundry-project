"""
orchestrator.py -- Multi-agent orchestrator with Human-in-the-Loop (v1.1-ctx)
Author: jagadeesan.vg@cognizant.com - 2276259

Wires 3 agents: Triage > Restore > Learning (on failure)
Uses Foundry Responses API: project.get_openai_client(agent_name=...)

v1.1   - DB name validation gate before restore execution.
         User-provided names resolved against real source DB names from blob storage.
         Improved no-match handling: blob empty vs no-match-but-available.

v1.1-ctx - Pipeline context accumulator.
           Full context (triage analysis, tool results, db_name, original request)
           is now passed to the Learning Agent and Restore Agent.
           Fixes the Knowledge/Learning Agent SOP quality issue where context was incomplete.

         - Triage tool failure gate: blocks restore when pre-flight tools error,
           triggers Learning Agent with full pipeline context even when the LLM
           still routes to restore.

         - Gate moved before routing logic so it fires regardless of whether
           the LLM routes to restore or asks for confirmation.
"""
import os, json, sys, re
from datetime import datetime
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from check_disk_space import check_disk_space
from verify_backup_blob import verify_backup_exists
from check_target_db import check_target_database
from restore_database import restore_database
from generate_sop import generate_sop
from suggest_tool import suggest_tool
from lookup_backup import lookup_backups

load_dotenv()

# -- Setup Client --
project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
MODEL = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

# -- Agent Names --
TRIAGE_AGENT = "DBA-Triage-Agent"
RESTORE_AGENT = "DBA-Restore-Agent"
LEARNING_AGENT = "DBA-Learning-Agent"

# -- Approval Mode --
REQUIRE_APPROVAL = True

# -- Tool Dispatcher --
TOOL_MAP = {
    "check_disk_space": lambda args: check_disk_space(),
    "verify_backup_blob": lambda args: verify_backup_exists(args.get("db_name", "")),
    "check_target_db": lambda args: check_target_database(args.get("db_name", "")),
    "restore_database": lambda args: restore_database(args.get("db_name", "")),
    "generate_sop": lambda args: generate_sop(args.get("failure_context", "{}")),
    "suggest_tool": lambda args: suggest_tool(args.get("failure_context", "{}")),
    "lookup_backups": lambda args: lookup_backups(),
}

APPROVAL_REQUIRED_TOOLS = {
    "restore_database": "DESTRUCTIVE: This will restore/overwrite a database.",
    "suggest_tool": "This may create a new Python tool file on the VM.",
}



# ============================================================
# DB NAME RESOLUTION (v1.1)
# ============================================================

def resolve_db_name(user_input):
    """
    Resolve user-provided DB name against real source DB names from blob backups.
    Returns:
        (result, match_type)
        - 'exact':  result = canonical DB name (str)
        - 'fuzzy':  result = list of candidate DB names
        - 'none':   result = list of all available DB names (may be empty)
    """
    data = lookup_backups()
    available = data.get("available_databases", [])
    source_names = [db["source_db"] for db in available]
    user_lower = user_input.lower().strip()

    # 1. Exact match (case-insensitive)
    for name in source_names:
        if name.lower() == user_lower:
            return name, "exact"

    # 2. Substring match
    substring_matches = [
        n for n in source_names
        if user_lower in n.lower() or n.lower() in user_lower
    ]
    if substring_matches:
        return substring_matches, "fuzzy"

    # 3. difflib fuzzy match
    from difflib import get_close_matches
    close = get_close_matches(
        user_lower, [n.lower() for n in source_names], n=3, cutoff=0.4
    )
    if close:
        candidates = []
        for c in close:
            for name in source_names:
                if name.lower() == c and name not in candidates:
                    candidates.append(name)
        if candidates:
            return candidates, "fuzzy"

    # 4. No match
    return source_names, "none"


def validate_restore_args(arguments):
    """
    Safety net: called inside execute_tool before restore_database runs.
    Validates db_name against real source DBs. Corrects or rejects.
    Returns corrected arguments dict, or None if rejected.
    """
    raw_name = arguments.get("db_name", "")
    if not raw_name:
        return arguments

    resolved, match_type = resolve_db_name(raw_name)

    if match_type == "exact":
        if resolved != raw_name:
            print(f"  [SAFETY NET] Corrected case: '{raw_name}' -> '{resolved}'")
            arguments["db_name"] = resolved
        return arguments

    if match_type == "fuzzy":
        candidates = resolved
        print(f"\n  [SAFETY NET] Agent passed '{raw_name}' -- not an exact source DB name.")
        print("  Candidates from blob storage:")
        for idx, c in enumerate(candidates, 1):
            print(f"    {idx}. {c}")
        while True:
            choice = input(f"  Select [1-{len(candidates)}] or 'n' to cancel: ").strip().lower()
            if choice == "n":
                print("  Cancelled by operator.")
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                selected = candidates[int(choice) - 1]
                print(f"  Confirmed: '{selected}'")
                arguments["db_name"] = selected
                return arguments
            print(f"  Enter 1-{len(candidates)} or 'n'")

    # no match -- handle empty blob vs no-match-but-available
    if not resolved:
        print("\n  [SAFETY NET] No backups found in blob storage.")
        print("  Possible causes: backup pipeline not run, backups deleted, SAS token issue.")
        manual = input("  Enter exact source DB name manually, or 'n' to cancel: ").strip()
        if manual.lower() == "n" or not manual:
            return None
        arguments["db_name"] = manual
        return arguments

    print(f"\n  [SAFETY NET] '{raw_name}' does not match any source database.")
    print("  Available:")
    for idx, c in enumerate(resolved, 1):
        print(f"    {idx}. {c}")
    while True:
        choice = input(f"  Select [1-{len(resolved)}] or 'n' to cancel: ").strip().lower()
        if choice == "n":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(resolved):
            arguments["db_name"] = resolved[int(choice) - 1]
            print(f"  Confirmed: '{resolved[int(choice) - 1]}'")
            return arguments
        print(f"  Enter 1-{len(resolved)} or 'n'")


# ============================================================
# APPROVAL + TOOL EXECUTION
# ============================================================

def ask_approval(message):
    """Prompt operator for approval. Returns True if approved."""
    if not REQUIRE_APPROVAL:
        print("  Auto-approved (REQUIRE_APPROVAL=False)")
        return True
    print(f"\n{'-- ' * 20}")
    print("  APPROVAL REQUIRED")
    print(f"  {message}")
    print(f"{'-- ' * 20}")
    while True:
        choice = input("  Approve? [y/n/details]: ").strip().lower()
        if choice in ("y", "yes"):
            print("  Approved.")
            return True
        elif choice in ("n", "no"):
            print("  Rejected by operator.")
            return False
        elif choice in ("d", "details"):
            print("  Review the context above before approving.")
        else:
            print("  Please enter y, n, or d")


def execute_tool(tool_name, arguments):
    """Execute a tool call with optional validation and approval gates."""
    print(f"  Tool call: {tool_name}({json.dumps(arguments)})")

    # v1.1 -- Safety net: validate DB name before restore
    if tool_name == "restore_database":
        corrected = validate_restore_args(arguments)
        if corrected is None:
            return json.dumps({
                "status": "REJECTED",
                "message": "DB name validation failed. Restore cancelled."
            })
        arguments = corrected

    if tool_name in APPROVAL_REQUIRED_TOOLS:
        reason = APPROVAL_REQUIRED_TOOLS[tool_name]
        approved = ask_approval(
            f"{reason}\n     Tool: {tool_name}\n     Args: {json.dumps(arguments, indent=2)}"
        )
        if not approved:
            return json.dumps({"status": "REJECTED", "message": f"Operator rejected {tool_name}"})

    try:
        if tool_name in TOOL_MAP:
            result = TOOL_MAP[tool_name](arguments)
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": str(e)}

    result_str = json.dumps(result) if isinstance(result, dict) else str(result)
    print(f"  Result: {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
    return result_str


# ============================================================
# AGENT RUNNER
# ============================================================

def run_agent(agent_name, user_message, context=""):
    """Run a Foundry agent with tool call loop."""
    print(f"\n{'='*60}")
    print(f"Running: {agent_name}")
    print(f"Input: {user_message[:150]}...")
    print(f"{'='*60}")

    full_input = user_message
    if context:
        full_input = f"CONTEXT FROM PREVIOUS AGENT:\n{context}\n\nREQUEST:\n{user_message}"

    tool_calls_log = []
    tool_results_log = []

    try:
        openai = project.get_openai_client(agent_name=agent_name)
        response = openai.responses.create(
            model=MODEL,
            input=full_input,
        )

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            tool_calls = [item for item in response.output if item.type == "function_call"]
            if not tool_calls:
                break

            tool_results = []
            for tc in tool_calls:
                func_name = tc.name
                func_args = json.loads(tc.arguments) if tc.arguments else {}
                tool_calls_log.append({"tool": func_name, "args": func_args})
                result_str = execute_tool(func_name, func_args)
                tool_results_log.append({"tool": func_name, "result": result_str})
                tool_results.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result_str,
                })

            response = openai.responses.create(
                model=MODEL,
                input=tool_results,
                previous_response_id=response.id,
            )

        final_text = response.output_text if response.output_text else "No text response from agent."
        print(f"\n{agent_name} says:\n{final_text[:500]}")

        return {"status": "success", "response": final_text, "tool_calls": tool_calls_log, "tool_results": tool_results_log}

    except Exception as e:
        print(f"\n{agent_name} error: {e}")
        return {"status": "error", "response": str(e), "tool_calls": tool_calls_log, "tool_results": tool_results_log}


# ============================================================
# ORCHESTRATOR
# ============================================================

def orchestrate(user_request):
    """Main orchestration flow: Triage > Validate > Restore > Learning."""
    print("\n" + "==" * 30)
    print(f"  INCOMING REQUEST: {user_request}")
    print("==" * 30)

    timestamp = datetime.now().isoformat()

    # -- Pipeline context accumulator (v1.1-ctx) --
    # This dict accumulates context from every stage so that downstream agents
    # (especially Learning Agent) receive the full picture for SOP generation.
    pipeline_context = {
        "original_request": user_request,
        "timestamp": timestamp,
        "db_name": "",
        "triage": {},
        "restore": {},
    }

    # === STEP 1: TRIAGE ===
    triage_result = run_agent(TRIAGE_AGENT, user_request)

    if triage_result["status"] == "error":
        print("\nTriage failed. Triggering Learning Agent...")
        pipeline_context["triage"] = {
            "status": triage_result["status"],
            "response": triage_result["response"],
            "tool_calls": triage_result.get("tool_calls", []),
            "tool_results": triage_result.get("tool_results", []),
        }
        failure_context = json.dumps(pipeline_context, indent=2)
        learning_result = run_agent(LEARNING_AGENT,
            f"Triage FAILED. Analyze full pipeline context and generate SOP.\n\nFULL PIPELINE CONTEXT:\n{failure_context}")
        return {"overall_status": "FAILED_AT_TRIAGE", "triage": triage_result, "learning": learning_result}

    triage_response = triage_result["response"]

    # Populate pipeline context with triage output
    pipeline_context["triage"] = {
        "status": triage_result["status"],
        "response": triage_response,
        "tool_calls": triage_result.get("tool_calls", []),
        "tool_results": triage_result.get("tool_results", []),
    }

    # === TRIAGE TOOL FAILURE GATE (v1.1-ctx) ===
    # Check immediately after triage completes, BEFORE routing logic.
    # If any triage tool returned an error, block the entire pipeline and
    # trigger Learning Agent with full context -- regardless of whether the
    # LLM decided to route to restore or ask for confirmation.
    triage_tool_failures = [
        tr for tr in triage_result.get("tool_results", [])
        if '"error"' in tr.get("result", "").lower()
    ]

    if triage_tool_failures:
        print("\n  [TRIAGE TOOL FAILURE DETECTED]")
        print(f"  {len(triage_tool_failures)} tool(s) returned errors during triage:")
        for tr in triage_tool_failures:
            print(f"    - {tr['tool']}: {tr['result'][:150]}")
        print("  Pipeline blocked. Triggering Learning Agent...")

        pipeline_context["triage_tool_failures"] = triage_tool_failures
        failure_context = json.dumps(pipeline_context, indent=2)
        learning_result = run_agent(
            LEARNING_AGENT,
            "Triage pre-flight checks had tool failures. Orchestrator blocked the pipeline. "
            "Analyze and generate SOP.\n\n"
            f"FULL PIPELINE CONTEXT:\n{failure_context}",
        )
        return {
            "overall_status": "BLOCKED_TRIAGE_TOOL_FAILURE",
            "triage": triage_result,
            "learning": learning_result,
        }

    # === ROUTING DETECTION ===
    
    # === ROUTING DETECTION ===
    route_to_restore = False
    db_name = ""

    # Parse triage response for explicit routing JSON
    for line in triage_response.split("\n"):
        line = line.strip()
        if line.startswith("{") and "route_to" in line:
            try:
                routing = json.loads(line)
                if routing.get("route_to") == "restore_agent" and routing.get("checks_passed"):
                    route_to_restore = True
                    db_name = routing.get("db_name", "")
            except json.JSONDecodeError:
                pass
            break

    if not route_to_restore:
        print("\nTriage completed -- no restore routing needed.")
        return {"overall_status": "TRIAGE_HANDLED", "triage": triage_result}


    # Record validated db_name in pipeline context
    pipeline_context["db_name"] = db_name

    # === STEP 2: RESTORE ===
    restore_input = f"Restore database '{db_name}'. Triage checks passed. Proceed with restore."
    restore_result = run_agent(
        RESTORE_AGENT,
        restore_input,
        context=json.dumps(pipeline_context["triage"], indent=2),
    )

    restore_response = restore_result["response"]

    # Populate pipeline context with restore output
    pipeline_context["restore"] = {
        "status": restore_result["status"],
        "response": restore_response,
        "tool_calls": restore_result.get("tool_calls", []),
        "tool_results": restore_result.get("tool_results", []),
    }

    # v1.1.1 -- BUG-2 fix: check actual tool results for REJECTED status,
    # not just LLM narrative text (which may omit failure keywords).
    tool_results = restore_result.get("tool_results", [])
    any_tool_rejected = any(
        '"REJECTED"' in tr.get("result", "")
        for tr in tool_results
    )
    restore_actually_ran = any(
        tr["tool"] == "restore_database" and '"REJECTED"' not in tr.get("result", "")
        and '"error"' not in tr.get("result", "").lower()
        for tr in tool_results
    )
    restore_failed = (
        restore_result["status"] == "error"
        or any_tool_rejected
        or any(w in restore_response.lower() for w in ["failed", "error", "rejected"])
        or not restore_actually_ran
    )

    if not restore_failed:
        print("\n" + "==" * 30)
        print("  RESTORE COMPLETED SUCCESSFULLY")
        print("==" * 30)
        return {"overall_status": "SUCCESS", "triage": triage_result, "restore": restore_result}

    # === STEP 3: LEARNING (on failure) ===
    print("\nRestore failed. Triggering Learning Agent...")
    failure_context = json.dumps(pipeline_context, indent=2)
    learning_result = run_agent(
        LEARNING_AGENT,
        "Restore FAILED. Analyze full pipeline context, generate SOP, upload, suggest tool."
        f"\n\nFULL PIPELINE CONTEXT:\n{failure_context}",
    )

    print("\n" + "==" * 30)
    print("  LEARNING COMPLETE")
    print("==" * 30)

    return {
        "overall_status": "RESTORE_FAILED_BUT_LEARNED",
        "triage": triage_result, "restore": restore_result, "learning": learning_result,
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    banner = (
        "\n============================================================\n"
        "  DBA Operations Agent -- Multi-Agent Orchestrator v1.1-ctx\n"
        "\n"
        "  Agents: Triage > Restore > Learning\n"
        "  Features: DB Name Validation, Human-in-the-Loop Approval,\n"
        "            Pipeline Context Accumulator, Triage Tool Failure Gate\n"
        "  Approval Mode: " + ("ON" if REQUIRE_APPROVAL else "OFF") + "\n"
        "============================================================\n"
    )
    print(banner)

    if len(sys.argv) > 1:
        request = " ".join(sys.argv[1:])
    else:
        print("Example requests:")
        print('  - "Restore EnterpriseSales on the target server"')
        print('  - "Restore sales db from source to target"')
        print('  - "Check health of all databases"')
        print()
        request = input("Enter your request: ").strip()

    if not request:
        print("No request. Exiting.")
        sys.exit(1)

    result = orchestrate(request)

    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nLog saved to: {log_file}")
    print(f"Overall Status: {result['overall_status']}")
