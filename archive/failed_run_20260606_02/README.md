# Failed Run 2 -- 2026-06-06 01:58

## Improvement from Run 1
- Restore Agent no longer hallucinated local disk path (D:\backups\...)
- Instead guessed blob file name "salesdb.bak" -- closer but still wrong
- Learning Agent SOP now mentions Azure Blob as alternative
- Suggested tool handles BOTH local and blob (actual improvement)

## Still wrong
- Restore Agent should not pass backup_path at all, let tool auto-discover
- SOP still primarily local-focused
- Tool is decent but should be blob-first, not local-first

## Root cause
- Restore Agent instructions say "do not pass local paths" but don't say
  "do not guess file names -- omit backup_path to auto-discover"
- generate_sop.py and suggest_tool.py prompts still too shallow
