import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

SQLVM_SERVER = os.getenv('SQLVM_SERVER')
SQLVM_DATABASE = 'master'
SQLVM_USERNAME = os.getenv('SQLVM_USERNAME')
SQLVM_PASSWORD = os.getenv('SQLVM_PASSWORD')

CONN_STR = (
    f'DRIVER={{ODBC Driver 18 for SQL Server}};'
    f'SERVER={SQLVM_SERVER};'
    f'DATABASE={SQLVM_DATABASE};'
    f'UID={SQLVM_USERNAME};'
    f'PWD={SQLVM_PASSWORD};'
    'TrustServerCertificate=YES;'
)


def kill_sessions(db_name):
    with pyodbc.connect(CONN_STR, autocommit=True) as conn:
        cursor = conn.cursor()
        # Find session SPIDs connected to the target database, excluding current session
        cursor.execute("""
            SELECT session_id
            FROM sys.dm_exec_sessions s
            JOIN sys.dm_exec_connections c ON s.session_id = c.session_id
            WHERE DB_NAME(c.database_id) = ?
              AND s.is_user_process = 1
              AND s.session_id != @@SPID
        """, db_name)

        sessions = cursor.fetchall()
        if not sessions:
            return 0

        spids = [str(row.session_id) for row in sessions]

        for spid in spids:
            # Execute KILL command for each session
            cursor.execute(f'KILL {spid}')

        return len(spids)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('Usage: python kill_active_db_sessions.py <database_name>')
        sys.exit(1)

    db_name = sys.argv[1]
    killed = kill_sessions(db_name)
    print(f'Killed {killed} active session(s) on database "{db_name}" to allow exclusive access.')
