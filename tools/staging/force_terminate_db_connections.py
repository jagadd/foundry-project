import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

SQLVM_SERVER = os.getenv('SQLVM_SERVER')
SQLVM_UID = os.getenv('SQLVM_UID')
SQLVM_PWD = os.getenv('SQLVM_PWD')
SQLVM_DB = 'master'

CONN_STR = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SQLVM_SERVER};DATABASE={SQLVM_DB};UID={SQLVM_UID};PWD={SQLVM_PWD};TrustServerCertificate=yes"


def force_terminate_db_connections(db_name: str):
    """Terminate all active user connections to the specified database."""
    with pyodbc.connect(CONN_STR, autocommit=True) as conn:
        cursor = conn.cursor()

        # Get list of session_ids (spid) except current session that are connected to the target db
        query = f"""
        SELECT session_id FROM sys.dm_exec_sessions ses
        INNER JOIN sys.dm_exec_connections con ON ses.session_id = con.session_id
        WHERE database_id = DB_ID(?) AND ses.session_id != @@SPID AND ses.is_user_process = 1
        """
        cursor.execute(query, (db_name,))
        sessions = cursor.fetchall()

        # Kill each session
        for (session_id,) in sessions:
            try:
                cursor.execute(f"KILL {session_id}")
            except Exception as e:
                raise RuntimeError(f"Failed to kill session {{session_id}}: {{e}}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python force_terminate_db_connections.py <database_name>")
        sys.exit(1)

    db_name_arg = sys.argv[1]
    try:
        force_terminate_db_connections(db_name_arg)
        print(f"Successfully terminated active connections to database '{{db_name_arg}}'.")
    except Exception as err:
        print(f"Error: {{err}}")
        sys.exit(2)
