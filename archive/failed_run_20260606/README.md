# Failed Run Archive -- 2026-06-06 01:15

## Purpose
Preserved as a reference to demonstrate that LLM-generated artifacts
(SOPs, tools) are only as good as the context provided to the agents.

## What went wrong
- The Restore Agent had no knowledge of the blob-based backup architecture.
- It hallucinated a local disk path: D:\backups\salesdb_COPY_ONLY.bak
- The restore failed, triggering the Learning Agent.
- The Learning Agent generated an SOP and a tool, both based on the
  incorrect assumption that backups are on local disk.

## Files
- SOP-AUTO-20260606_011142.md : SOP suggesting local filesystem checks (wrong)
- verify_backup_path.py : Tool using os.path.exists for local files (wrong)
- run_20260606_011518.json : Full orchestrator run log

## Lesson
Agent instructions must include architecture context. Without it,
the LLM reasons correctly about the wrong environment.
