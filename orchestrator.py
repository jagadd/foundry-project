"""
orchestrator.py – Phase 5: Multi-agent orchestrator with Human-in-the-Loop
Author: jagadeesan.vg@cognizant.com - 2276259

Wires 3 agents: Triage → Restore → Learning (on failure)
Uses new Foundry Responses API: project.get_openai_client(agent_name=...)
"""
import os, json, sys
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
# upload_sop_to_vectorstore removed -- Option A: stage for human review
from suggest_tool import suggest_tool

load_dotenv()

# ── Setup Client ──
project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
MODEL = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

# ── Agent Names ──
TRIAGE_AGENT = "DBA-Triage-Agent"
RESTORE_AGENT = "DBA-Restore-Agent"
LEARNING_AGENT = "DBA-Learning-Agent"

# ── Approval Mode ──
REQUIRE_APPROVAL = True

# ── Tool Dispatcher ──
TOOL_MAP = {
    "check_disk_space": lambda args: check_disk_space(),
    "verify_backup_blob": lambda args: verify_backup_exists(args.get("db_name", "")),
    "check_target_db": lambda args: check_target_database(args.get("db_name", "")),
    "restore_database": lambda args: restore_database(args.get("db_name", "")),
    "generate_sop": lambda args: generate_sop(args.get("failure_context", "{}")),
    "suggest_tool": lambda args: suggest_tool(args.get("failure_context", "{}")),
}

APPROVAL_REQUIRED_TOOLS = {
    "restore_database": "⚠️  DESTRUCTIVE: This will restore/overwrite a database.",
    "suggest_tool": "🔧 This may create a new Python tool file on the VM.",
}


def ask_approval(message: str) -> bool:
    if not REQUIRE_APPROVAL:
        print(f"  🔓 Auto-approved (REQUIRE_APPROVAL=False)")
        return True
    print(f"\n{'⏸️ ' * 20}")
    print(f"  🛑 APPROVAL REQUIRED")
    print(f"  {message}")
    print(f"{'⏸️ ' * 20}")
    while True:
        choice = input("  ➡️  Approve? [y/n/details]: ").strip().lower()
        if choice in ("y", "yes"):
            print("  ✅ Approved!")
            return True
        elif choice in ("n", "no"):
            print("  ❌ Rejected by operator.")
            return False
        elif choice in ("d", "details"):
            print("  ℹ️  Review the context above before approving.")
        else:
            print("  Please enter y, n, or d")


def execute_tool(tool_name: str, arguments: dict) -> str:
    print(f"  🔧 Tool call: {tool_name}({json.dumps(arguments)})")
    if tool_name in APPROVAL_REQUIRED_TOOLS:
        reason = APPROVAL_REQUIRED_TOOLS[tool_name]
        approved = ask_approval(f"{reason}\n     Tool: {tool_name}\n     Args: {json.dumps(arguments, indent=2)}")
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
    print(f"  ✅ Result: {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
    return result_str


def run_agent(agent_name: str, user_message: str, context: str = "") -> dict:
    print(f"\n{'='*60}")
    print(f"🤖 Running: {agent_name}")
    print(f"📩 Input: {user_message[:150]}...")
    print(f"{'='*60}")

    full_input = user_message
    if context:
        full_input = f"CONTEXT FROM PREVIOUS AGENT:\n{context}\n\nREQUEST:\n{user_message}"

    tool_calls_log = []

    try:
        # Get agent-specific OpenAI client
        openai = project.get_openai_client(agent_name=agent_name)

        # Initial request
        response = openai.responses.create(
            model=MODEL,
            input=full_input,
        )

        # Tool call loop
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

        # Extract final text
        # Use convenience property instead
        final_text = response.output_text if response.output_text else "No text response from agent."
        print(f"\n💬 {agent_name} says:\n{final_text[:500]}")

        return {"status": "success", "response": final_text, "tool_calls": tool_calls_log}

    except Exception as e:
        print(f"\n❌ {agent_name} error: {e}")
        return {"status": "error", "response": str(e), "tool_calls": tool_calls_log}


def orchestrate(user_request: str):
    print("\n" + "🔷" * 30)
    print(f"  📋 INCOMING REQUEST: {user_request}")
    print("🔷" * 30)

    timestamp = datetime.now().isoformat()

    # ═══ STEP 1: TRIAGE ═══
    triage_result = run_agent(TRIAGE_AGENT, user_request)

    if triage_result["status"] == "error":
        print("\n❌ Triage failed. Triggering Learning Agent...")
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
            # Extract db name from the original request
            import re
            for word in re.findall(r"[a-zA-Z_]+", user_request.lower()):
                if word not in ("restore", "on", "the", "target", "server", "database"):
                    db_name = word
                    break

    if not route_to_restore:
        print("\n📋 Triage completed — no restore routing needed.")
        return {"overall_status": "TRIAGE_HANDLED", "triage": triage_result}

    # ═══ APPROVAL GATE 1: Confirm restore ═══
    approved = ask_approval(
        f"⚠️  Triage recommends RESTORING database: '{db_name}'\n"
        f"     Summary: {triage_response[:200]}...\n"
        f"     This will overwrite the target database."
    )
    if not approved:
        return {"overall_status": "RESTORE_REJECTED", "triage": triage_result}

    # ═══ STEP 2: RESTORE ═══
    restore_input = f"Restore database '{db_name}'. Triage checks passed. Proceed with restore."
    restore_result = run_agent(RESTORE_AGENT, restore_input, context=triage_response)

    restore_response = restore_result["response"]
    restore_failed = (
        restore_result["status"] == "error"
        or any(w in restore_response.lower() for w in ["failed", "error", "❌", "rejected"])
    )

    if not restore_failed:
        print("\n" + "✅" * 30)
        print("  🎉 RESTORE COMPLETED SUCCESSFULLY!")
        print("✅" * 30)
        return {"overall_status": "SUCCESS", "triage": triage_result, "restore": restore_result}

    # ═══ STEP 3: LEARNING (on failure) ═══
    print("\n⚠️  Restore failed! Triggering Learning Agent... 🧠")
    failure_context = json.dumps({
        "operation": "RESTORE", "db_name": db_name,
        "error": restore_response,
        "tools_used": [tc["tool"] for tc in restore_result.get("tool_calls", [])],
        "timestamp": timestamp,
    })
    learning_result = run_agent(LEARNING_AGENT,
        f"Restore FAILED. Analyze, generate SOP, upload, suggest tool.\n\nFAILURE:\n{failure_context}")

    print("\n" + "🧠" * 30)
    print("  📚 LEARNING COMPLETE — System is now smarter!")
    print("🧠" * 30)

    return {
        "overall_status": "RESTORE_FAILED_BUT_LEARNED",
        "triage": triage_result, "restore": restore_result, "learning": learning_result,
    }


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║  🤖 DBA Operations Agent — Multi-Agent Orchestrator     ║
║                                                          ║
║  Agents: Triage → Restore → Learning                     ║
║  Approval Mode: """ + ("ON 🔒" if REQUIRE_APPROVAL else "OFF 🔓") + """                                      ║
╚══════════════════════════════════════════════════════════╝
    """)

    if len(sys.argv) > 1:
        request = " ".join(sys.argv[1:])
    else:
        print("Example requests:")
        print('  • "Restore salesdb on the target server"')
        print('  • "Check health of all databases"')
        print('  • "Is there enough disk space for a restore?"')
        print()
        request = input("📝 Enter your request: ").strip()

    if not request:
        print("No request. Exiting.")
        sys.exit(1)

    result = orchestrate(request)

    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n📄 Log saved to: {log_file}")
    print(f"🏁 Overall Status: {result['overall_status']}")
