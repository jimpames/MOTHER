"""
Integration of MOTHER Orchestrator with webgui.py

This shows the key modifications needed to integrate the MOTHER orchestrator
with your existing webgui.py application.
"""
import asyncio
import json
import logging
import time
from typing import Dict, Optional, List, Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

# Import the MOTHER orchestrator
from mother_orchestrator import MOTHEROrchestrator, MotherMessage, User, LLMWorker

# Setup logging
logger = logging.getLogger(__name__)

# --- Models ---
class ContextAwareQuery(BaseModel):
    """Query model that includes context from previous interactions."""
    prompt: str
    query_type: str
    model_type: str
    model_name: str
    context: Optional[str] = None
    image: Optional[str] = None
    audio: Optional[str] = None
    voice_output: bool = False

# --- WebGUI Integration ---
class MOTHERWebGuiIntegrator:
    def __init__(self, db_path: str):
        self.mother = None
        self.db_path = db_path
        self.pending_initialization = False
        
    async def initialize(self):
        """Initialize the MOTHER orchestrator."""
        if self.mother is not None or self.pending_initialization:
            return
            
        self.pending_initialization = True
        try:
            self.mother = MOTHEROrchestrator(self.db_path)
            await self.mother.start()
            
            # Register active workers from the database
            await self._register_existing_workers()
            
            logger.info("MOTHER orchestrator initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing MOTHER: {str(e)}")
            raise
        finally:
            self.pending_initialization = False
    
    async def _register_existing_workers(self):
        """Register existing AI workers with MOTHER."""
        # Get workers from database
        db = get_db()  # Use your existing db connection function
        cursor = db.cursor()
        cursor.execute("SELECT * FROM ai_workers WHERE is_blacklisted = 0")
        workers = cursor.fetchall()
        db.close()
        
        for worker in workers:
            llm = LLMWorker(
                name=worker['name'],
                address=worker['address'],
                type=worker['type']
            )
            await self.mother.register_llm(llm)
            
        logger.info(f"Registered {len(workers)} workers with MOTHER")
    
    async def handle_websocket_connection(self, websocket: WebSocket, user_guid: str, user):
        """Handle a WebSocket connection with MOTHER integration."""
        # Ensure MOTHER is initialized
        if self.mother is None:
            await self.initialize()
        
        # Register user with MOTHER
        mother_user = User(guid=user.guid, nickname=user.nickname)
        await self.mother.register_user(mother_user, websocket)
        
        try:
            while True:
                data = await websocket.receive_json()
                message_type = data.get("type")
                
                # Handle normal WebGUI messages
                if message_type == "submit_query":
                    await self._handle_query(data, user, websocket)
                elif message_type.startswith("mother_"):
                    # Handle MOTHER-specific messages
                    await self._handle_mother_message(data, user, websocket)
                else:
                    # Pass to your existing handlers
                    pass  # Your existing message handlers
        
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user: {user_guid}")
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {str(e)}")
            await websocket.send_json({"type": "error", "message": str(e)})
        finally:
            # Unregister from MOTHER
            if self.mother:
                await self.mother.unregister_user(user_guid)
    
    async def _handle_query(self, data, user, websocket):
        """Handle a query with MOTHER integration."""
        # Extract original query data
        query_data = data.get("query", {})
        
        # Check if prompt contains a MOTHER command
        if "prompt" in query_data and query_data["prompt"].startswith("MOTHERREALM:"):
            # Create a MOTHER message
            mother_msg = MotherMessage(
                sender=user.guid,
                content=query_data["prompt"],
                voice_output="voice_output" in query_data and query_data["voice_output"]
            )
            
            # Process through MOTHER
            await self.mother.process_message(mother_msg)
            
            # Acknowledge receipt to client
            await websocket.send_json({
                "type": "mother_command_received",
                "message": "Command is being processed"
            })
            
            return
        
        # Enhance query with context
        model_name = query_data.get("model_name", "")
        
        if model_name in self.mother.active_llms:
            # Get context for this conversation
            context = self.mother.get_context(user.guid, model_name)
            
            # Create a context-aware query
            context_query = ContextAwareQuery(
                **query_data,
                context=context
            )
            
            # Replace the original query
            data["query"] = context_query.dict()
            
            # Set voice output flag based on preferences
            data["query"]["voice_output"] = self._should_use_voice_output(user.guid, model_name)
        
        # Continue with standard query processing
        await self._process_standard_query(data, user, websocket)
    
    def _should_use_voice_output(self, user_guid: str, model_name: str) -> bool:
        """Determine if voice output should be used."""
        # Check the MOTHER voice preferences
        if model_name in self.mother.active_llms:
            return self.mother.active_llms[model_name].voice_enabled
        return False
    
    async def _process_standard_query(self, data, user, websocket):
        """Process a standard query without MOTHER intervention."""
        # This would call your existing query processing logic
        # Modified to work with context-enhanced queries
        await state.query_queue.put({
            "query": data["query"],
            "user": user,
            "websocket": websocket,
            "timestamp": time.time()
        })
    
    async def _handle_mother_message(self, data, user, websocket):
        """Handle MOTHER-specific messages."""
        message_type = data.get("type", "")
        
        if message_type == "mother_set_voice":
            # Set voice for an LLM
            llm_name = data.get("llm_name")
            voice_id = data.get("voice_id")
            
            if llm_name and voice_id:
                success = await self.mother.set_llm_voice(llm_name, voice_id)
                await websocket.send_json({
                    "type": "mother_voice_set",
                    "success": success,
                    "llm_name": llm_name
                })
        
        elif message_type == "mother_enable_conversation":
            # Enable conversation between LLMs
            llms = data.get("llms", [])
            
            if llms and len(llms) > 1:
                message = MotherMessage(
                    sender=user.guid,
                    content=f"MOTHERREALM:debugwindowoutONLYLLMONLYPRIVATECHAT({','.join(llms)})",
                    message_type="system"
                )
                
                await self.mother.process_message(message)
                
                await websocket.send_json({
                    "type": "mother_conversation_enabled",
                    "llms": llms
                })

# --- Process Queue Modifications ---
async def process_queue_with_mother():
    """Enhanced queue processor that works with MOTHER."""
    global queue_processor_status
    queue_processor_status.is_running = True
    
    logger.info("Starting enhanced queue processing loop with MOTHER integration")
    
    while True:
        try:
            queue_processor_status.last_heartbeat = time.time()
            
            if state.query_queue.qsize() == 0:
                await asyncio.sleep(1)  # Sleep if queue is empty
                continue
            
            try:
                cancellable_query = await asyncio.wait_for(state.query_queue.get(), timeout=0.1)
                
                # Process the query
                result = await cancellable_query.run()
                
                # If query includes context and isn't cancelled, update MOTHER context
                if (not cancellable_query.cancelled and hasattr(mother_integrator, 'mother') 
                    and mother_integrator.mother is not None):
                    
                    query = cancellable_query.query_data.get('query', {})
                    user_guid = cancellable_query.query_data.get('user', {}).guid
                    model_name = query.get('model_name', '')
                    
                    # Update context if this is a chat with an LLM
                    if model_name in mother_integrator.mother