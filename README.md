
## v1.0 Known Issues

1. Fuzzy blob matching can silently restore wrong database (eSales matched EnterpriseSales)
2. Restore Agent still passes backup_path despite instructions -- orchestrator overrides to None
3. Learning Agent retries upload_sop_to_vectorstore 3-4 times before giving up (harmless)
4. Triage Agent does not always call verify_backup_blob even though it has the tool
5. Running create_agents.py creates duplicates -- must delete old agents first
6. Auto-generated SOPs contaminated vector store -- fixed with staging approach
7. Orchestrator success/failure detection is based on keyword matching in agent response text -- if agent avoids words like "failed" or "error", orchestrator marks it SUCCESS even when the tool returned FAILED
7. Orchestrator success/failure detection is based on keyword matching in agent response text -- if agent avoids words like "failed" or "error", orchestrator marks it SUCCESS even when the tool returned FAILED
