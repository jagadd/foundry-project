"""
orchestrator.py -- Multi-agent orchestrator with Human-in-the-Loop (v1.1)
Author: jagadeesan.vg@cognizant.com - 2276259

Wires 3 agents: Triage > Restore > Learning (on failure)
Uses Foundry Responses API: project.get_openai_client(agent_name=...)

v1.1 - DB name validation gate before restore execution.
       User-provided names resolved against real source DB names from blob storage.
       Improved no-match handling: blob empty vs no-match-but-available.
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

IGNORE_WORDS = {
    "restore", "on", "the", "target", "server", "database",
    "from", "source", "to", "db", "backup", "copy", "please",
    "can", "you", "run", "do", "a", "my", "this", "that",
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

    # === STEP 1: TRIAGE ===
    triage_result = run_agent(TRIAGE_AGENT, user_request)

    if triage_result["status"] == "error":
        print("\nTriage failed. Triggering Learning Agent...")
        failure_context = json.dumps({
            "operation": "TRIAGE", "error": triage_result["response"],
            "original_request": user_request, "timestamp": timestamp,
        })
        learning_result = run_agent(LEARNING_AGENT,
            f"Analyze this failure and generate SOP: {failure_context}")
        return {"overall_status": "FAILED_AT_TRIAGE", "triage": triage_result, "learning": learning_result}

    triage_response = triage_result["response"]
    route_to_restore = False
    db_name = ""

    try:
        for line in triage_response.split("\n"):
            line = line.strip()
            if line.startswith("{") and "route_to" in line:
                routing = json.loads(line)
                if routing.get("route_to") == "restore_agent" and routing.get("checks_passed"):
                    route_to_restore = True
                    db_name = routing.get("db_name", "")
                break
    except json.JSONDecodeError:
        pass

    if not route_to_restore:
        lower_resp = triage_response.lower()
        checks_ok = any(phrase in lower_resp for phrase in [
            "checks_passed", "checks passed", "check pass",
            "pre-flight checks", "all checks pass",
            "sufficient", "no conflict", "no active connection",
        ])
        is_restore = any(phrase in lower_resp for phrase in [
            "restore", "route_to", "restore_agent",
        ])
        if checks_ok and is_restore:
            route_to_restore = True
            for word in re.findall(r"[a-zA-Z_]+", user_request.lower()):
                if word not in IGNORE_WORDS:
                    db_name = word
                    break

    if not route_to_restore:
        print("\nTriage completed -- no restore routing needed.")
        return {"overall_status": "TRIAGE_HANDLED", "triage": triage_result}

    # === APPROVAL GATE 1: Confirm restore intent ===
    approved = ask_approval(
        f"Triage recommends RESTORING database: '{db_name}'\n"
        f"     Summary: {triage_response[:200]}...\n"
        f"     This will overwrite the target database."
    )
    if not approved:
        return {"overall_status": "RESTORE_REJECTED", "triage": triage_result}

    # === DB NAME VALIDATION GATE (v1.1) ===
    print("\n  [DB NAME VALIDATION]")
    print(f"  User-provided name: '{db_name}'")
    print("  Checking against source databases in blob storage...")

    resolved, match_type = resolve_db_name(db_name)

    if match_type == "exact":
        print(f"  Exact match confirmed: '{resolved}'")
        db_name = resolved

    elif match_type == "fuzzy":
        candidates = resolved
        print(f"  '{db_name}' is not an exact source database name.")
        print("  Possible matches:")
        for idx, c in enumerate(candidates, 1):
            print(f"    {idx}. {c}")
        while True:
            choice = input(f"  Select the correct database [1-{len(candidates)}] or 'n' to cancel: ").strip().lower()
            if choice == "n":
                print("  Restore cancelled by operator.")
                return {
                    "overall_status": "RESTORE_CANCELLED_NAME_MISMATCH",
                    "triage": triage_result,
                    "reason": f"User-provided name '{db_name}' not confirmed.",
                }
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                db_name = candidates[int(choice) - 1]
                print(f"  Confirmed: will restore as '{db_name}'")
                break
            print(f"  Invalid input. Enter 1-{len(candidates)} or 'n'")

    elif match_type == "none":
        if not resolved:
            # Blob storage has no backups at all
            print("  No backups found in blob storage.")
            print("  Possible causes: backup pipeline not run, backups deleted, SAS token issue.")
            manual = input("  Enter exact source DB name manually, or 'n' to cancel: ").strip()
            if manual.lower() == "n" or not manual:
                return {
                    "overall_status": "RESTORE_CANCELLED_NO_BACKUPS",
                    "triage": triage_result,
                    "reason": "No backups found in blob storage.",
                }
            db_name = manual
            print(f"  Using manually entered name: '{db_name}'")
        else:
            # Blob has backups but none match user input
            print(f"  '{db_name}' does not match any source database in blob storage.")
            print("  Available databases:")
            for idx, c in enumerate(resolved, 1):
                print(f"    {idx}. {c}")
            while True:
                choice = input(f"  Select from available [1-{len(resolved)}] or 'n' to cancel: ").strip().lower()
                if choice == "n":
                    return {
                        "overall_status": "RESTORE_CANCELLED_NO_MATCH",
                        "triage": triage_result,
                        "reason": f"Operator cancelled. Available: {', '.join(resolved)}",
                    }
                if choice.isdigit() and 1 <= int(choice) <= len(resolved):
                    db_name = resolved[int(choice) - 1]
                    print(f"  Confirmed: will restore as '{db_name}'")
                    break
                print(f"  Enter 1-{len(resolved)} or 'n'")

    # === STEP 2: RESTORE ===
    restore_input = f"Restore database '{db_name}'. Triage checks passed. Proceed with restore."
    restore_result = run_agent(RESTORE_AGENT, restore_input, context=triage_response)

    restore_response = restore_result["response"]

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
    failure_context = json.dumps({
        "operation": "RESTORE", "db_name": db_name,
        "error": restore_response,
        "tools_used": [tc["tool"] for tc in restore_result.get("tool_calls", [])],
        "timestamp": timestamp,
    })
    learning_result = run_agent(LEARNING_AGENT,
        f"Restore FAILED. Analyze, generate SOP, upload, suggest tool.\n\nFAILURE:\n{failure_context}")

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
        "  DBA Operations Agent -- Multi-Agent Orchestrator v1.1\n"
        "\n"
        "  Agents: Triage > Restore > Learning\n"
        "  Features: DB Name Validation, Human-in-the-Loop Approval\n"
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
