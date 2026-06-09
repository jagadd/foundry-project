"""
test_orchestrator.py -- Test runner for orchestrator v1.2-lean
Author: jagadeesan.vg@cognizant.com - 2276259

Runs predefined scenarios against the orchestrator and validates results.
Each scenario tests a specific path through the triage/restore/learning pipeline.

Usage:
    python test_orchestrator.py                  # Run all scenarios
    python test_orchestrator.py --scenario 1     # Run scenario #1 only
    python test_orchestrator.py --scenario 1,5,8 # Run specific scenarios
    python test_orchestrator.py --dry-run        # List all scenarios without executing
"""
import os, sys, json, argparse
from datetime import datetime

# -- Import orchestrator --
# Adjust the import if your file is named differently.
# Default: orchestrator_v1.2.py in the same directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from orchestrator_v1_2 import orchestrate
except ImportError:
    try:
        from orchestrator import orchestrate
    except ImportError:
        print("ERROR: Cannot import orchestrate().")
        print("Ensure orchestrator_v1.2.py (renamed to orchestrator_v1_2.py)")
        print("or orchestrator.py is in the same directory.")
        sys.exit(1)


# ============================================================
# TEST SCENARIOS
# ============================================================

SCENARIOS = [
    # ----------------------------------------------------------
    # RESTORE PATH -- Happy Path
    # ----------------------------------------------------------
    {
        "id": 1,
        "name": "Restore -- happy path (exact name)",
        "request": "Restore EnterpriseSales on the target server",
        "expected_intent": "RESTORE",
        "expected_overall_status": "SUCCESS",
        "description": "Exact DB name, standard restore request. Should pass triage, "
                       "execute restore, and return SUCCESS.",
    },
    {
        "id": 2,
        "name": "Restore -- exact name + preferred_time",
        "request": "Restore EnterpriseHR from yesterday around 2pm",
        "expected_intent": "RESTORE",
        "expected_overall_status": "SUCCESS",
        "description": "Exact DB name with a time preference. Triage should extract "
                       "preferred_time as ISO 8601 and pass it to Restore Agent.",
    },
    {
        "id": 3,
        "name": "Restore -- ambiguous DB name",
        "request": "Restore sales db on target",
        "expected_intent": "RESTORE",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Ambiguous name ('sales db'). Triage should set db_name=null, "
                       "checks_passed=false, and ask for clarification in message.",
    },
    {
        "id": 4,
        "name": "Restore -- non-existent DB",
        "request": "Restore NonExistentDB on the target",
        "expected_intent": "RESTORE",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "DB name not in source list. Triage should list available DBs "
                       "and set checks_passed=false.",
    },
    {
        "id": 5,
        "name": "Restore -- reverse direction (explicit)",
        "request": "Restore EnterpriseFinance from target VM back to production MI",
        "expected_intent": "RESTORE",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "User requests reverse direction (VM to MI). Triage should flag "
                       "the direction concern and NOT run pre-flight checks.",
    },
    {
        "id": 6,
        "name": "Restore -- reverse direction (no DB name)",
        "request": "Restore from non-prod to prod",
        "expected_intent": "RESTORE",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Reverse direction without specifying a DB. Triage should flag "
                       "direction issue and ask for both direction confirmation and DB name.",
    },
    {
        "id": 7,
        "name": "Restore -- minimal request",
        "request": "Restore EnterpriseHR",
        "expected_intent": "RESTORE",
        "expected_overall_status": "SUCCESS",
        "description": "Minimal restore request with just the DB name. Should still "
                       "pass triage checks and route to restore.",
    },

    # ----------------------------------------------------------
    # HEALTH_CHECK PATH
    # ----------------------------------------------------------
    {
        "id": 8,
        "name": "Health check -- disk space",
        "request": "Check disk space on the target server",
        "expected_intent": "HEALTH_CHECK",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Health check request for disk space. Triage handles directly, "
                       "no restore routing.",
    },
    {
        "id": 9,
        "name": "Health check -- database state",
        "request": "What is the current state of all databases on target?",
        "expected_intent": "HEALTH_CHECK",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Health check for DB states on target VM. Triage handles directly.",
    },
    {
        "id": 10,
        "name": "Health check -- backup pipeline",
        "request": "Is the backup pipeline running properly?",
        "expected_intent": "HEALTH_CHECK",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Health check about backup pipeline status. Triage should call "
                       "lookup_backups and report findings.",
    },

    # ----------------------------------------------------------
    # INCIDENT PATH
    # ----------------------------------------------------------
    {
        "id": 11,
        "name": "Incident -- database corruption",
        "request": "Target VM database is corrupted and not responding",
        "expected_intent": "INCIDENT",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Incident report: DB corruption. Triage should classify as INCIDENT "
                       "and provide recommended steps with SOP references.",
    },
    {
        "id": 12,
        "name": "Incident -- repeated restore failure",
        "request": "EnterpriseHR restore failed 3 times today, urgent",
        "expected_intent": "INCIDENT",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Incident: repeated failures. Triage should classify as INCIDENT "
                       "(not RESTORE) due to urgency and repeated failure pattern.",
    },
    {
        "id": 13,
        "name": "Incident -- server down",
        "request": "SQL Server on target VM is down",
        "expected_intent": "INCIDENT",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Incident: server down. Triage should classify as INCIDENT and "
                       "provide troubleshooting steps.",
    },

    # ----------------------------------------------------------
    # UNKNOWN PATH
    # ----------------------------------------------------------
    {
        "id": 14,
        "name": "Unknown -- SOP question",
        "request": "What is the SOP for failed restores?",
        "expected_intent": "UNKNOWN",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "General knowledge question about SOPs. Triage should classify "
                       "as UNKNOWN and provide SOP references.",
    },
    {
        "id": 15,
        "name": "Unknown -- out of scope",
        "request": "How do I add a new user to SQL Server?",
        "expected_intent": "UNKNOWN",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Out of scope for dbops-agent. Triage should classify as UNKNOWN "
                       "and explain the system's scope.",
    },
    {
        "id": 16,
        "name": "Unknown -- completely ambiguous",
        "request": "Hello",
        "expected_intent": "UNKNOWN",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Ambiguous single-word input. Triage should classify as UNKNOWN "
                       "and explain available capabilities.",
    },

    # ----------------------------------------------------------
    # EDGE CASES
    # ----------------------------------------------------------
    {
        "id": 17,
        "name": "Edge -- multiple DBs in one request",
        "request": "Restore EnterpriseSales and EnterpriseHR on target",
        "expected_intent": "RESTORE",
        "expected_overall_status": "TRIAGE_HANDLED",
        "description": "Two DB names in one request. Triage should handle this -- either "
                       "ask user to submit one at a time, or pick one and clarify. "
                       "checks_passed should be false (ambiguous scope).",
    },
    {
        "id": 18,
        "name": "Edge -- ALL CAPS input",
        "request": "RESTORE ENTERPRISESALES ON TARGET",
        "expected_intent": "RESTORE",
        "expected_overall_status": "SUCCESS",
        "description": "All caps input. Triage should still resolve DB name "
                       "(case-insensitive match) and proceed normally.",
    },
    {
        "id": 19,
        "name": "Edge -- all lowercase input",
        "request": "restore enterprisesales on target",
        "expected_intent": "RESTORE",
        "expected_overall_status": "SUCCESS",
        "description": "All lowercase input. Triage should still resolve DB name "
                       "(case-insensitive match) and proceed normally.",
    },
    {
        "id": 20,
        "name": "Edge -- multi-step request",
        "request": "Check disk space then restore EnterpriseSales",
        "expected_intent": "RESTORE",
        "expected_overall_status": "SUCCESS",
        "description": "Multi-step request. Triage runs disk check as part of pre-flight "
                       "anyway. Should classify as RESTORE and proceed with checks.",
    },
]


# ============================================================
# HELPERS
# ============================================================

def print_separator(char="=", width=70):
    print(char * width)


def print_scenario_header(scenario):
    print_separator()
    print(f"  SCENARIO #{scenario['id']}: {scenario['name']}")
    print_separator("-")
    print(f"  Request:   {scenario['request']}")
    print(f"  Expected:  intent={scenario['expected_intent']}, "
          f"status={scenario['expected_overall_status']}")
    print(f"  Tests:     {scenario['description']}")
    print_separator("-")


def extract_triage_parsed(result):
    """Extract triage_parsed from the result if available."""
    triage = result.get("triage", {})
    response_text = triage.get("response", "")

    # Try to parse the triage response as JSON (same logic as orchestrator)
    try:
        return json.loads(response_text.strip())
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        start = response_text.index("{")
        end = response_text.rindex("}") + 1
        return json.loads(response_text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    return None


def print_result_summary(scenario, result):
    """Print a concise summary of the test result."""
    overall = result.get("overall_status", "N/A")
    expected = scenario["expected_overall_status"]

    print(f"\n  RESULT: overall_status = {overall}")

    # Triage parsed output
    triage_parsed = extract_triage_parsed(result)
    if triage_parsed:
        print(f"  Triage parsed:")
        print(f"    intent:         {triage_parsed.get('intent', 'N/A')}")
        print(f"    db_name:        {triage_parsed.get('db_name', 'N/A')}")
        print(f"    checks_passed:  {triage_parsed.get('checks_passed', 'N/A')}")
        print(f"    preferred_time: {triage_parsed.get('preferred_time', 'N/A')}")
        print(f"    sop_refs:       {triage_parsed.get('sop_refs', [])}")
        msg = triage_parsed.get("message", "")
        if msg:
            print(f"    message:        {msg[:200]}")

    # Restore output (if present)
    restore = result.get("restore", {})
    if restore:
        print(f"  Restore status: {restore.get('status', 'N/A')}")
        restore_resp = restore.get("response", "")
        if restore_resp:
            print(f"    response:     {restore_resp[:200]}")

    # Learning output (if present)
    learning = result.get("learning", {})
    if learning:
        print(f"  Learning status: {learning.get('status', 'N/A')}")
        learning_resp = learning.get("response", "")
        if learning_resp:
            print(f"    response:     {learning_resp[:200]}")

    # Pass/Fail check
    # For RESTORE scenarios, SUCCESS or RESTORE_FAILED_BUT_LEARNED are valid
    # For non-RESTORE, TRIAGE_HANDLED is expected
    # Also accept BLOCKED_TRIAGE_TOOL_FAILURE and FAILED_AT_TRIAGE as valid
    # failure paths (they mean the system correctly handled the error)
    match = overall == expected
    status_label = "PASS" if match else "MISMATCH"
    print(f"\n  VERDICT: {status_label} (expected={expected}, actual={overall})")
    return match


def run_dry_run():
    """Print all scenarios without executing."""
    print_separator()
    print("  DRY RUN -- Listing all test scenarios")
    print_separator()
    print()

    for s in SCENARIOS:
        print(f"  #{s['id']:2d}  {s['name']}")
        print(f"       Request:  {s['request']}")
        print(f"       Expected: intent={s['expected_intent']}, status={s['expected_overall_status']}")
        print(f"       Tests:    {s['description']}")
        print()

    print_separator()
    print(f"  Total scenarios: {len(SCENARIOS)}")
    print_separator()


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Test runner for orchestrator v1.2-lean")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Run specific scenario(s) by ID. Comma-separated for multiple. E.g., --scenario 1,5,8",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List all scenarios without executing.",
    )
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
        return

    # Determine which scenarios to run
    if args.scenario:
        try:
            ids = [int(x.strip()) for x in args.scenario.split(",")]
        except ValueError:
            print("ERROR: --scenario must be comma-separated integers. E.g., --scenario 1,5,8")
            sys.exit(1)
        scenarios_to_run = [s for s in SCENARIOS if s["id"] in ids]
        not_found = [i for i in ids if i not in [s["id"] for s in SCENARIOS]]
        if not_found:
            print(f"WARNING: Scenario IDs not found: {not_found}")
        if not scenarios_to_run:
            print("ERROR: No valid scenarios to run.")
            sys.exit(1)
    else:
        scenarios_to_run = SCENARIOS

    # Banner
    print_separator("=")
    print("  DBA Operations Agent -- Test Runner v1.2")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Scenarios: {len(scenarios_to_run)} of {len(SCENARIOS)}")
    print_separator("=")

    # Run scenarios
    all_results = []
    summary = []

    for scenario in scenarios_to_run:
        print_scenario_header(scenario)

        try:
            result = orchestrate(scenario["request"])
            match = print_result_summary(scenario, result)

            all_results.append({
                "scenario": scenario,
                "result": result,
                "match": match,
            })
            summary.append({
                "id": scenario["id"],
                "name": scenario["name"],
                "expected": scenario["expected_overall_status"],
                "actual": result.get("overall_status", "ERROR"),
                "match": match,
            })

        except Exception as e:
            print(f"\n  EXCEPTION: {e}")
            all_results.append({
                "scenario": scenario,
                "result": {"overall_status": "EXCEPTION", "error": str(e)},
                "match": False,
            })
            summary.append({
                "id": scenario["id"],
                "name": scenario["name"],
                "expected": scenario["expected_overall_status"],
                "actual": "EXCEPTION",
                "match": False,
            })

        print()

    # Summary table
    print_separator("=")
    print("  TEST SUMMARY")
    print_separator("=")
    print()
    print(f"  {'#':>3}  {'Scenario':<45} {'Expected':<28} {'Actual':<28} {'Result':<8}")
    print(f"  {'---':>3}  {'---':<45} {'---':<28} {'---':<28} {'---':<8}")

    pass_count = 0
    fail_count = 0

    for s in summary:
        verdict = "PASS" if s["match"] else "MISMATCH"
        if s["match"]:
            pass_count += 1
        else:
            fail_count += 1
        print(f"  {s['id']:>3}  {s['name']:<45} {s['expected']:<28} {s['actual']:<28} {verdict:<8}")

    print()
    print_separator("-")
    print(f"  PASS: {pass_count}  |  MISMATCH: {fail_count}  |  TOTAL: {len(summary)}")
    print_separator("-")

    if fail_count > 0:
        print()
        print("  NOTE: MISMATCH does not always mean a bug.")
        print("  The LLM may classify differently than expected.")
        print("  Review each MISMATCH to determine if it is a genuine issue")
        print("  or an acceptable LLM classification variation.")

    # Save results
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_data = {
        "run_date": datetime.now().isoformat(),
        "scenarios_run": len(scenarios_to_run),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "summary": summary,
        "detailed_results": [
            {
                "scenario_id": r["scenario"]["id"],
                "scenario_name": r["scenario"]["name"],
                "request": r["scenario"]["request"],
                "expected_status": r["scenario"]["expected_overall_status"],
                "actual_status": r["result"].get("overall_status", "N/A"),
                "match": r["match"],
                "full_result": r["result"],
            }
            for r in all_results
        ],
    }

    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=2)

    print(f"\n  Full log saved to: {log_file}")
    print()


if __name__ == "__main__":
    main()
