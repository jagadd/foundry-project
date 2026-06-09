import pyodbc
import dotenv
import os
from time import sleep

def load_env_vars():
    dotenv.load_dotenv()
    required_vars = ["SQLVM_SERVER", "SQLVM_DATABASE", "SQLVM_USERNAME", "SQLVM_PASSWORD"]
    env = {}
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            raise EnvironmentError(f"Environment variable {var} not set")
        env[var] = value
    return env

def connect_to_sql_server(server, database, username, password):
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, autocommit=True)

def find_active_sessions(cursor, db_name):
    query = f"""
    SELECT session_id, login_name, program_name
    FROM sys.dm_exec_sessions
    WHERE database_id = DB_ID(?)
      AND session_id <> @@SPID
      AND is_user_process = 1
    """
    cursor.execute(query, db_name)
    sessions = cursor.fetchall()
    return sessions

def kill_session(cursor, session_id):
    try:
        cursor.execute(f"KILL {session_id};")
    except Exception as e:
        pass  # Ignore errors killing session

def disconnect_active_sessions(db_name, wait_seconds=5, max_retries=3):
    env = load_env_vars()
    conn = connect_to_sql_server(env["SQLVM_SERVER"], env["SQLVM_DATABASE"], env["SQLVM_USERNAME"], env["SQLVM_PASSWORD"])
    cursor = conn.cursor()

    retries = 0
    while retries < max_retries:
        sessions = find_active_sessions(cursor, db_name)
        if not sessions:
            return True
        for session in sessions:
            kill_session(cursor, session.session_id)
        sleep(wait_seconds)
        retries += 1

    # One last check
    sessions = find_active_sessions(cursor, db_name)
    cursor.close()
    conn.close()
    return not sessions

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python disconnect_active_sessions.py <database_name>")
        sys.exit(1)
    db_name = sys.argv[1]
    success = disconnect_active_sessions(db_name)
    if success:
        print(f"All active sessions disconnected for database {db_name}.")
        sys.exit(0)
    else:
        print(f"Failed to disconnect all active sessions for database {db_name}.")
        sys.exit(2)
