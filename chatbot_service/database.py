import sqlite3
import os
import hashlib
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

DB_PATH = Path(__file__).parent / "chatbot.db"
SECRET_KEY_PATH = Path(__file__).parent / ".secret_key"

def get_cipher():
    """Retrieve or generate encryption key for API Keys."""
    if not SECRET_KEY_PATH.exists():
        key = Fernet.generate_key()
        with open(SECRET_KEY_PATH, "wb") as f:
            f.write(key)
    else:
        with open(SECRET_KEY_PATH, "rb") as f:
            key = f.read()
    return Fernet(key)

def encrypt_key(plain_text: str) -> str:
    if not plain_text:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(plain_text.encode('utf-8')).decode('utf-8')

def decrypt_key(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        cipher = get_cipher()
        return cipher.decrypt(cipher_text.encode('utf-8')).decode('utf-8')
    except Exception:
        return ""

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize SQLite tables for Chatbot Microservice."""
    conn = get_db()
    cursor = conn.cursor()

    # System Configuration Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        is_active INTEGER DEFAULT 1,
        api_key_enc TEXT DEFAULT '',
        model_name TEXT DEFAULT 'gemini-flash-latest',
        system_prompt TEXT DEFAULT 'You are an AI Assistant for the TicketSolve system. Respond politely, concisely, accurately, and strictly in English based on the system documentation provided.'
    )
    """)

    # Admin User Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)

    # Custom Knowledge Base Table (Editable by System Admin)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custom_knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Chat History Log Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id TEXT DEFAULT 'guest',
        role TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Seed Default Configuration if empty
    cursor.execute("SELECT COUNT(*) FROM system_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO system_config (id, is_active, api_key_enc, model_name, system_prompt)
            VALUES (1, 1, '', 'gemini-flash-latest', 'You are an AI Assistant for the TicketSolve system. Respond politely, concisely, and accurately based strictly on the system documentation provided.')
        """)

    # Seed Default Knowledge Base Guide if empty
    cursor.execute("SELECT COUNT(*) FROM custom_knowledge")
    if cursor.fetchone()[0] == 0:
        default_guide = """# TicketSolve System Knowledge Base & Guide

## System Overview
TicketSolve is a Multi-Tenant Issue & Ticket Management System built for organizations to manage technical tickets, assign issues to engineers, track statuses, and automate notifications.

## Key Features & Workflows
1. **Ticket Management**: Create, edit, assign, resolve, and delete tickets. Statuses include Open, In Progress, Deploy Request, Ready to Deploy, Resolved, and Closed.
2. **Company & Multi-Tenancy**: Organizations operate with strict data isolation. System Administrators manage all companies.
3. **Notification Rules**: Configurable email notifications sent upon ticket status changes or assignments.
4. **Monthly PDF Reports**: Export monthly ticket summaries as formatted PDF reports.
5. **Audit Logs & Backups**: Track system audit logs and execute system backups.
"""
        cursor.execute("INSERT INTO custom_knowledge (title, content) VALUES (?, ?)", ("TicketSolve Main System Guide", default_guide))

    # Seed Default Admin (Username: admin, Password: adminpassword)
    cursor.execute("SELECT COUNT(*) FROM admin_users")
    if cursor.fetchone()[0] == 0:
        default_hash = hash_password("adminpassword")
        cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", default_hash))

    conn.commit()
    conn.close()

def get_config():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, api_key_enc, model_name, system_prompt FROM system_config WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "is_active": bool(row["is_active"]),
            "api_key": decrypt_key(row["api_key_enc"]),
            "model_name": row["model_name"],
            "system_prompt": row["system_prompt"]
        }
    return {"is_active": True, "api_key": "", "model_name": "gemini-flash-latest", "system_prompt": ""}

def update_config(is_active: bool, api_key: str = None, model_name: str = None, system_prompt: str = None):
    conn = get_db()
    cursor = conn.cursor()
    
    current = get_config()
    new_is_active = 1 if is_active else 0
    new_api_key_enc = encrypt_key(api_key) if api_key is not None else encrypt_key(current["api_key"])
    new_model = model_name if model_name is not None else current["model_name"]
    new_prompt = system_prompt if system_prompt is not None else current["system_prompt"]

    cursor.execute("""
        UPDATE system_config
        SET is_active = ?, api_key_enc = ?, model_name = ?, system_prompt = ?
        WHERE id = 1
    """, (new_is_active, new_api_key_enc, new_model, new_prompt))
    conn.commit()
    conn.close()

# --- Custom Knowledge Base Functions ---

def get_custom_knowledge_entries():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, content, is_active, updated_at FROM custom_knowledge ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_custom_knowledge_entry(title: str, content: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO custom_knowledge (title, content) VALUES (?, ?)", (title, content))
    conn.commit()
    conn.close()

def update_custom_knowledge_entry(entry_id: int, title: str, content: str, is_active: bool = True):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE custom_knowledge
        SET title = ?, content = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (title, content, 1 if is_active else 0, entry_id))
    conn.commit()
    conn.close()

def delete_custom_knowledge_entry(entry_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_knowledge WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
