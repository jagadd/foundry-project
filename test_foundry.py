import os
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

load_dotenv()

client = AgentsClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential()
)

agent = client.create_agent(
    model=os.environ["MODEL_DEPLOYMENT_NAME"],
    name="test-agent",
    instructions="You are a helpful assistant. Reply in one sentence."
)
print(f"Agent created: {agent.id}")

thread = client.threads.create()
client.messages.create(
    thread_id=thread.id,
    role="user",
    content="Say hello to a DBA named Jagadeesan"
)

run = client.runs.create_and_process(
    thread_id=thread.id,
    agent_id=agent.id
)
print(f"Run status: {run.status}")

if run.status == "failed":
    print(f"Run error: {run.last_error}")
else:
    messages = client.messages.list(thread_id=thread.id)
    for msg in messages:
        if msg.role == "assistant":
            print(f"Agent says: {msg.text_messages[0].text.value}")

client.delete_agent(agent.id)
print("Test agent cleaned up")
