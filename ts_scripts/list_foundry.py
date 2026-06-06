"""
list_foundry_agents.py -- List all agents in Foundry project, detect duplicates
Author: jagadeesan.vg@cognizant.com - 2276259

Uses: project.agents.list() (azure-ai-projects SDK v2.x)
"""
import os
from collections import defaultdict
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

load_dotenv()

project = AIProjectClient(
    endpoint=os.getenv("PROJECT_ENDPOINT"),
    credential=DefaultAzureCredential(),
    allow_preview=True,
)

print("Fetching agents from Foundry project...")
print(f"Endpoint: {os.getenv('PROJECT_ENDPOINT')}")
print("=" * 80)

try:
    agents_paged = project.agents.list()
    agent_list = list(agents_paged)
except Exception as e:
    print(f"Error listing agents: {e}")
    print()
    print("Trying to inspect available methods on project.agents:")
    print([m for m in dir(project.agents) if not m.startswith("_")])
    exit(1)

if not agent_list:
    print("No agents found in this project.")
    exit(0)

# Display all agents
print(f"{'#':<4} {'NAME':<35} {'KIND':<12} {'DETAILS'}")
print("-" * 80)

name_map = defaultdict(list)

for idx, agent in enumerate(agent_list, 1):
    name = getattr(agent, "name", None) or "(unnamed)"
    kind = getattr(agent, "kind", None) or "n/a"

    details_parts = []
    for attr in ["description", "created_at", "id"]:
        val = getattr(agent, attr, None)
        if val:
            details_parts.append(f"{attr}={val}")

    details = ", ".join(details_parts) if details_parts else "n/a"
    print(f"{idx:<4} {name:<35} {kind:<12} {details}")
    name_map[name].append(agent)

print("-" * 80)
print(f"Total agents: {len(agent_list)}")
print(f"Unique names: {len(name_map)}")

# Flag duplicates
duplicates = {name: entries for name, entries in name_map.items() if len(entries) > 1}

if duplicates:
    print()
    print("WARNING: DUPLICATE AGENT NAMES DETECTED")
    print("=" * 80)
    for name, entries in duplicates.items():
        print(f"  Name: {name}  (count: {len(entries)})")
        for agent in entries:
            agent_id = getattr(agent, "id", "n/a")
            created = getattr(agent, "created_at", "n/a")
            print(f"    ID: {agent_id}  Created: {created}")
    print()
    print("To delete a duplicate agent by name:")
    print("  project.agents.delete(agent_name='<AGENT_NAME>')")
    print()
    print("To delete a specific version:")
    print("  project.agents.delete_version(agent_name='<AGENT_NAME>', agent_version='<VERSION>')")
else:
    print()
    print("No duplicate agent names found.")