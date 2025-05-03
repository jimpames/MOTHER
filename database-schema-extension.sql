"""
Database Schema Extensions for MOTHER Context Window

This file contains the SQL schema modifications needed to support the MOTHER
orchestration system in the existing SQLite database.
"""

# --- Schema Extensions ---

# Create the primary MOTHER context table to store conversational history
CREATE_MOTHER_CONTEXT_TABLE = """
CREATE TABLE IF NOT EXISTS mother_context (
    id INTEGER PRIMARY KEY,
    user_guid TEXT NOT NULL,
    llm_name TEXT NOT NULL,
    query TEXT,
    response TEXT,
    context_data TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_guid) REFERENCES users (guid)
);
"""

# Create an index for faster context retrieval
CREATE_MOTHER_CONTEXT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_mother_context_user_llm 
ON mother_context (user_guid, llm_name, timestamp);
"""

# Table to store LLM voice configurations
CREATE_MOTHER_VOICES_TABLE = """
CREATE TABLE IF NOT EXISTS mother_voices (
    llm_name TEXT PRIMARY KEY,
    voice_id TEXT NOT NULL,
    voice_params TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

# Table to store user voice preferences
CREATE_MOTHER_USER_PREFS_TABLE = """
CREATE TABLE IF NOT EXISTS mother_user_preferences (
    user_guid TEXT PRIMARY KEY,
    voice_enabled BOOLEAN DEFAULT 0,
    preferred_llm TEXT,
    session_data TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_guid) REFERENCES users (guid)
);
"""

# Add voice capabilities to existing AI workers table
ADD_VOICE_TO_WORKERS = """
ALTER TABLE ai_workers ADD COLUMN voice_id TEXT;
ALTER TABLE ai_workers ADD COLUMN voice_enabled BOOLEAN DEFAULT 0;
"""

# Table to track inter-LLM conversations
CREATE_MOTHER_CONVERSATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS mother_conversations (
    conversation_id TEXT PRIMARY KEY,
    initiator_guid TEXT,
    participants TEXT,  -- JSON array of participant LLM names
    is_private BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (initiator_guid) REFERENCES users (guid)
);
"""

# Table to store conversation messages
CREATE_MOTHER_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS mother_messages (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT,
    sender TEXT NOT NULL,  -- user_guid or llm_name
    content TEXT NOT NULL,
    message_type TEXT DEFAULT 'text',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES mother_conversations (conversation_id)
);
"""

# MOTHER state tracking for system recovery
CREATE_MOTHER_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS mother_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

# Views for easier analysis and retrieval

# View to get the latest context for each user-LLM pair
CREATE_LATEST_CONTEXT_VIEW = """
CREATE VIEW IF NOT EXISTS mother_latest_context AS
SELECT user_guid, llm_name, context_data,
       MAX(timestamp) as latest_time
FROM mother_context
GROUP BY user_guid, llm_name;
"""

# View to get active conversations
CREATE_ACTIVE_CONVERSATIONS_VIEW = """
CREATE VIEW IF NOT EXISTS mother_active_conversations AS
SELECT c.conversation_id, c.initiator_guid, c.participants, 
       u.nickname as initiator_nickname,
       c.created_at, c.last_activity,
       COUNT(m.id) as message_count
FROM mother_conversations c
JOIN users u ON c.initiator_guid = u.guid
LEFT JOIN mother_messages m ON c.conversation_id = m.conversation_id
WHERE c.is_active = 1
GROUP BY c.conversation_id;
"""

# --- Database Initialization Function ---

def init_mother_db(db_connection):
    """Initialize the MOTHER database extensions."""
    cursor = db_connection.cursor()
    
    # Create the tables
    cursor.execute(CREATE_MOTHER_CONTEXT_TABLE)
    cursor.execute(CREATE_MOTHER_CONTEXT_INDEX)
    cursor.execute(CREATE_MOTHER_VOICES_TABLE)
    cursor.execute(CREATE_MOTHER_USER_PREFS_TABLE)
    
    # Try to add columns to existing table
    try:
        cursor.execute(ADD_VOICE_TO_WORKERS)
    except Exception as e:
        print(f"Note: Voice columns may already exist in ai_workers table: {e}")
    
    cursor.execute(CREATE_MOTHER_CONVERSATIONS_TABLE)
    cursor.execute(CREATE_MOTHER_MESSAGES_TABLE)
    cursor.execute(CREATE_MOTHER_STATE_TABLE)
    
    # Create views
    cursor.execute(CREATE_LATEST_CONTEXT_VIEW)
    cursor.execute(CREATE_ACTIVE_CONVERSATIONS_VIEW)
    
    # Commit changes
    db_connection.commit()
    
    print("MOTHER database extensions initialized successfully")

# --- Helper Functions ---

def get_recent_context(db_connection, user_guid, llm_name, limit=5):
    """Get recent conversation context for a user-LLM pair."""
    cursor = db_connection.cursor()
    
    # Get the most recent context entries
    cursor.execute("""
        SELECT query, response, timestamp 
        FROM mother_context
        WHERE user_guid = ? AND llm_name = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (user_guid, llm_name, limit))
    
    results = cursor.fetchall()
    
    # Format context string
    context_string = ""
    for query, response, timestamp in results:
        context_string += f"Previous query ({timestamp}): {query}\n"
        context_string += f"Previous response: {response}\n\n"
    
    return context_string.strip()

def store_conversation_message(db_connection, conversation_id, sender, content, message_type='text'):
    """Store a conversation message."""
    cursor = db_connection.cursor()
    
    # Insert the message
    cursor.execute("""
        INSERT INTO mother_messages (conversation_id, sender, content, message_type)
        VALUES (?, ?, ?, ?)
    """, (conversation_id, sender, content, message_type))
    
    # Update last activity time for the conversation
    cursor.execute("""
        UPDATE mother_conversations
        SET last_activity = CURRENT_TIMESTAMP
        WHERE conversation_id = ?
    """, (conversation_id,))
    
    db_connection.commit()
    
    return cursor.lastrowid

def create_llm_conversation(db_connection, initiator_guid, participants, is_private=True):
    """Create a new conversation between LLMs."""
    import json
    import uuid
    
    cursor = db_connection.cursor()
    
    # Generate a unique conversation ID
    conversation_id = f"convo_{uuid.uuid4()}"
    
    # Store the participants as a JSON array
    participants_json = json.dumps(participants)
    
    # Create the conversation record
    cursor.execute("""
        INSERT INTO mother_conversations 
        (conversation_id, initiator_guid, participants, is_private)
        VALUES (?, ?, ?, ?)
    """, (conversation_id, initiator_guid, participants_json, is_private))
    
    db_connection.commit()
    
    return conversation_id

def set_llm_voice(db_connection, llm_name, voice_id, voice_params=None):
    """Set a voice for an LLM."""
    import json
    
    cursor = db_connection.cursor()
    
    # Convert params to JSON if provided
    params_json = json.dumps(voice_params) if voice_params else None
    
    # Update both the mother_voices table and the ai_workers table
    cursor.execute("""
        INSERT OR REPLACE INTO mother_voices (llm_name, voice_id, voice_params)
        VALUES (?, ?, ?)
    """, (llm_name, voice_id, params_json))
    
    cursor.execute("""
        UPDATE ai_workers
        SET voice_id = ?, voice_enabled = 1
        WHERE name = ?
    """, (voice_id, llm_name))
    
    db_connection.commit()
    
    return True

def get_llm_voice(db_connection, llm_name):
    """Get the voice configuration for an LLM."""
    import json
    
    cursor = db_connection.cursor()
    
    cursor.execute("""
        SELECT voice_id, voice_params
        FROM mother_voices
        WHERE llm_name = ?
    """, (llm_name,))
    
    result = cursor.fetchone()
    
    if not result:
        return None, None
    
    voice_id, params_json = result
    voice_params = json.loads(params_json) if params_json else {}
    
    return voice_id, voice_params

# --- Table Reset Functions (For Development Only) ---

def reset_mother_tables(db_connection):
    """Reset all MOTHER-related tables (for development use only)."""
    cursor = db_connection.cursor()
    
    # Drop all tables
    tables = [
        "mother_messages",
        "mother_conversations",
        "mother_state",
        "mother_user_preferences",
        "mother_voices",
        "mother_context"
    ]
    
    for table in tables:
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception as e:
            print(f"Error dropping {table}: {e}")
    
    # Drop all views
    views = [
        "mother_active_conversations",
        "mother_latest_context"
    ]
    
    for view in views:
        try:
            cursor.execute(f"DROP VIEW IF EXISTS {view}")
        except Exception as e:
            print(f"Error dropping {view}: {e}")
    
    db_connection.commit()
    
    print("MOTHER tables reset successfully")
    
    # Reinitialize the tables
    init_mother_db(db_connection)
