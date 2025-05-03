@debug
async def process_query(query: Query) -> Union[str, bytes]:
    """
    Enhanced process_query function with MOTHER integration.
    
    This function processes incoming queries, detecting MOTHER commands
    and handling context-aware conversations.
    """
    logger.info(f"Processing query: {query.query_type} - {query.model_type}")
    
    try:
        # Check for MOTHER commands
        if query.prompt.startswith("MOTHERREALM:"):
            logger.info("Detected MOTHER command, routing to MOTHER orchestrator")
            return await process_mother_command(query)
        
        # Process speech input
        if query.query_type == 'speech':
            transcription = await process_speech_to_text(query.audio)
            query.prompt = transcription
            query.query_type = 'chat'
        
        # Get context if available
        context = None
        if hasattr(mother_integrator, 'mother') and mother_integrator.mother is not None:
            # Extract user GUID from the current context
            user_guid = get_user_guid_from_context()
            
            if user_guid and query.model_name in mother_integrator.mother.active_llms:
                context = mother_integrator.mother._get_context(user_guid, query.model_name)
                logger.info(f"Retrieved context for user {user_guid} with LLM {query.model_name}")
        
        # Process the query with context
        result = await process_query_with_context(query, context)
        
        # Handle speech output if requested
        voice_output = False
        if hasattr(query, 'voice_output'):
            voice_output = query.voice_output
        
        if query.model_type == 'speech' or voice_output:
            if query.query_type == 'imagine':
                # For imagine queries, just return the image result without text-to-speech
                return result
            else:
                # For other queries, convert text to speech
                audio_result = await process_text_to_speech_with_voice(result, query.model_name)
                return audio_result
        else:
            return result
            
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

async def process_mother_command(query: Query) -> str:
    """Process a MOTHER command."""
    try:
        if not hasattr(mother_integrator, 'mother') or mother_integrator.mother is None:
            logger.error("MOTHER not initialized, cannot process command")
            return "Error: MOTHER orchestration system is not available"
        
        # Parse the command
        command_parts = query.prompt.split(":", 1)[1].split("(", 1)
        if len(command_parts) != 2:
            return "Invalid MOTHER command format"
            
        action = command_parts[0]
        params_str = command_parts[1].rstrip(")")
        
        # Create a MOTHER message
        user_guid = get_user_guid_from_context()
        message = MotherMessage(
            sender=user_guid,
            content=query.prompt,
            message_type="system"
        )
        
        # Process through MOTHER
        await mother_integrator.mother.process_message(message)
        
        return f"MOTHER command processed: {action}({params_str})"
        
    except Exception as e:
        logger.error(f"Error processing MOTHER command: {str(e)}")
        return f"Error processing MOTHER command: {str(e)}"

async def process_query_with_context(query: Query, context: Optional[str]) -> str:
    """Process a query with conversation context."""
    try:
        # If we have context, incorporate it into the prompt
        if context:
            enhanced_prompt = f"""
The following conversation history provides context for the current query:

{context}

Current query: {query.prompt}
"""
            # Update the query with enhanced prompt
            query.prompt = enhanced_prompt
            logger.info("Enhanced query with conversation context")
        
        # Process based on model type
        if query.model_type == "huggingface":
            return await process_query_huggingface(query)
        elif query.model_type == "claude":
            return await process_query_claude(query)
        else:
            return await process_query_worker_node(query)
            
    except Exception as e:
        logger.error(f"Error processing query with context: {str(e)}")
        raise

def get_user_guid_from_context():
    """Extract user GUID from the current execution context."""
    # In a real implementation, this would access the right context variable
    # For demonstration, we'll assume it's available in some way
    return "current_user_guid"

async def process_text_to_speech_with_voice(text: str, llm_name: str) -> str:
    """Process text to speech with specific voice for an LLM."""
    try:
        voice_id = "v2/en_speaker_6"  # Default voice
        
        # Check if we have a specific voice for this LLM
        if hasattr(mother_integrator, 'mother') and mother_integrator.mother is not None:
            db = get_db()
            cursor = db.cursor()
            cursor.execute("""
                SELECT voice_id FROM mother_voices 
                WHERE llm_name = ?
            """, (llm_name,))
            result = cursor.fetchone()
            db.close()
            
            if result:
                voice_id = result[0]
                logger.info(f"Using voice {voice_id} for LLM {llm_name}")
        
        # Call the TTS function with the specified voice
        logger.info(f"Generating speech with voice {voice_id}")
        
        # Here we'd modify your existing TTS function to accept a voice parameter
        # For now, we'll call the existing function
        word_count = len(text.split())
        
        if word_count <= MAX_BARK_WORDS:
            logger.info("Using BARK for text-to-speech with custom voice")
            audio_array = generate_audio(
                text, text_temp=0.7, waveform_temp=0.7, history_prompt=voice_id
            )
            # Rest of your existing TTS code...
            # For demo purposes, we're simplifying
            return "base64_audio_data"
        else:
            # Fall back to pyttsx3
            logger.info("Query return too big for BARK - using pyttsx3 instead")
            output_audio_base64 = await asyncio.to_thread(pyttsx3_to_audio, text)
            return output_audio_base64
            
    except Exception as e:
        logger.error(f"Error in text to speech with voice: {str(e)}")
        # Fall back to regular TTS
        return await process_text_to_speech(text)