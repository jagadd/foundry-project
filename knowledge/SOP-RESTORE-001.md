# SOP: Restore Production Database to Non-Production

## Version: 1.0
## Last Updated: 2026-06-05
## Author: jagadeesan.vg@cognizant.com - 2276259

## Architecture
- Production Source: Azure SQL Managed Instance
- Non-Production Target: SQL Server 2025 on Azure VM (10.10.0.5)
- Transfer Method: BACKUP TO URL → Azure Blob Storage → RESTORE FROM URL

## Backup Selection Rules
- Always use COPY_ONLY backups for non-prod refresh
- Backup must be less than 48 hours old
- Must include CHECKSUM for integrity verification
- Must include COMPRESSION for faster blob transfer
- Prefer the most recent full backup

## Pre-Flight Checklist (MANDATORY before any restore)
1. Verify target VM disk space >= 1.5x backup size
2. Check if target database already exists on VM
3. If target exists: count active connections, plan SINGLE_USER with ROLLBACK IMMEDIATE
4. Run RESTORE FILELISTONLY to get file layout
5. Plan MOVE statements for correct drive mapping on target VM

## Database-Specific Rules
| Database  | Special Requirement |
|-----------|-------------------|
| salesdb   | Mask Customer.Email and Customer.Phone post-restore |

(Add new databases here as needed. Agent will pick up changes on next run.)

## Post-Restore Mandatory Steps
1. Set database to MULTI_USER
2. Fix orphaned users: ALTER USER [x] WITH LOGIN = [x]
3. Run EXEC sp_updatestats
4. Apply data masking if required by database policy
5. Verify DB state = ONLINE
6. Test SELECT on key tables to confirm data accessible
7. Verify user access

## Approval Matrix
| Target Environment | Approval Required |
|-------------------|-------------------|
| Dev               | DBA self-approve |
| Test/QA           | DBA lead approval |
| UAT/Staging       | Manager + DBA lead |
| Production        | BLOCKED - this SOP is non-prod restore only |

## Rollback
DROP DATABASE [target_db_name] on the target VM.

## Escalation
- Disk space issues: Contact cloud infra team
- Network or blob access issues: Contact networking team
- Repeated failures: Escalate to DBA lead
