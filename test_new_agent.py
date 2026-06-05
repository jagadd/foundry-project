"""
test_new_agent.py – TASK 1: Verify new Foundry agent API pattern
Author: jagadeesan.vg@cognizant.com - 2276259

Creates a dummy agent "test-new-format-dummy" using the new Foundry
agents.create_version() API with PromptAgentDefinition, then tests
a conversation via project.get_openai_client(agent_name=...) using
the Responses API (the protocol used by Foundry prompt agents).
"""
import os
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential

load_dotenv()

AGENT_NAME = "test-new-format-dummy"
MODEL = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

# ── Step 1: Create AIProjectClient ──
print("Connecting to Foundry project...")
project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,          # Required for agent endpoints
)

# ── Step 2: Check if dummy agent already exists; delete if so ──
try:
    existing = project.agents.get(AGENT_NAME)
    print(f"⚠️  Agent '{AGENT_NAME}' already exists — deleting first...")
    project.agents.delete(AGENT_NAME)
    print(f"   Deleted.")
except Exception:
    pass  # Agent doesn't exist, proceed

# ── Step 3: Create agent version using new Foundry API ──
print(f"\nCreating agent '{AGENT_NAME}' via agents.create_version()...")

definition = PromptAgentDefinition(
    model=MODEL,
    instructions="You are a test agent. Reply with: New Foundry format works!",
)

agent = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=definition,
    description="Dummy agent to verify new Foundry API pattern from code",
)

print(f"✅ Agent created successfully!")
print(f"   Name:    {agent.name}")
print(f"   Version: {agent.version}")
print(f"   Status:  {agent.status}")
print(f"   Kind:    {agent.definition.get('kind', 'N/A')}")
print(f"   ID:      {agent.id}")

# ── Step 4: Test a conversation via get_openai_client + Responses API ──
# Foundry prompt agents expose the "responses" protocol, not chat.completions
print(f"\n── Testing conversation via Responses API ──")
print(f"   (agent endpoint: {{project}}/agents/{AGENT_NAME}/endpoint/protocols/openai)")

openai_client = project.get_openai_client(agent_name=AGENT_NAME)

response = openai_client.responses.create(
    model=MODEL,
    input="Hello",
)

# Extract text output from response
reply = response.output_text
print(f"   User:  Hello")
print(f"   Agent: {reply}")

# ── Step 5: Cleanup — delete the dummy agent ──
print(f"\n── Cleaning up dummy agent '{AGENT_NAME}' ──")
project.agents.delete(AGENT_NAME)
print(f"✅ Agent '{AGENT_NAME}' deleted.")

print("""
╔══════════════════════════════════════════════════════╗
║  🎯 TASK 1 Complete — New Foundry API pattern works! ║
║                                                      ║
║  ✅ agents.create_version() with PromptAgentDefinition║
║  ✅ get_openai_client(agent_name=...) + Responses API ║
║  ✅ agents.delete() for cleanup                       ║
╚══════════════════════════════════════════════════════╝
""")
