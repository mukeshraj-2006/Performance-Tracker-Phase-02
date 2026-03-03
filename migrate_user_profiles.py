"""
migrate_user_profiles.py
Safe, non-destructive migration script.
Creates the user_profiles table if it does not already exist.
Does NOT touch any existing table, column, or data.
"""
import sqlite3

DB_PATH = 'neri.db'

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if table already exists -- if so, do nothing
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'")
    if cursor.fetchone():
        print("[OK] user_profiles table already exists -- no changes made.")
        conn.close()
        return

    # Create the table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            full_name TEXT,
            profession_type TEXT,
            field_of_interest TEXT,
            degree TEXT,
            branch TEXT,
            year_of_study TEXT,
            institution TEXT,
            industry TEXT,
            role TEXT,
            experience_years TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    print("[OK] user_profiles table created successfully.")
    conn.close()

if __name__ == '__main__':
    migrate()
