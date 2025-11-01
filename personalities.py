"""
Personalities module for dynamic personality switching
Allows switching between different personality modes using function calling.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime


logger = logging.getLogger(__name__)

class PersonalityManager:
    """Manages personality modes and personality switching."""
    
    def __init__(self, personalities_file: str = "personalities.json"):
        self.personalities_file = personalities_file
        self.personalities = {}
        self.current_personality = None  
        self.personality_history = []
        self.load_personalities()
    
    def load_personalities(self):
        """Load personalities from JSON file."""
        try:
            if os.path.exists(self.personalities_file):
                with open(self.personalities_file, 'r', encoding='utf-8') as f:
                    self.personalities = json.load(f)
                logger.info(f"Loaded {len(self.personalities)} personalities from {self.personalities_file}")
            else:
                logger.warning(f"Personalities file {self.personalities_file} not found. Using empty personality set.")
                self.personalities = {}
        except Exception as e:
            logger.error(f"Error loading personalities: {e}")
            self.personalities = {}
    
    def save_personalities(self):
        """Save personalities to JSON file."""
        try:
            with open(self.personalities_file, 'w', encoding='utf-8') as f:
                json.dump(self.personalities, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved personalities to {self.personalities_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving personalities: {e}")
            return False
    
    def switch_personality(self, personality_id: str) -> Dict[str, Any]:
        """Switch to a specific personality."""
        try:
            if personality_id not in self.personalities:
                return {
                    "success": False,
                    "message": f"Personality '{personality_id}' not found",
                    "available_personalities": list(self.personalities.keys())
                }
            
            
            personality = self.personalities[personality_id]
            if not personality.get("enabled", True):
                
                return {
                    "success": False,
                    "message": "This Personallity is disabled, Dont act as it",
                    "personality_id": personality_id,
                }

            
            self.personality_history.append({
                "from": self.current_personality,
                "to": personality_id,
                "timestamp": datetime.now().isoformat()
            })
            
            
            self.current_personality = personality_id
            
            logger.info(f"Switched to personality: {personality_id}")
            
            
            prompt_text = personality.get("prompt", personality.get("system_prompt", ""))
            
            return {
                "success": True,
                "message": f"Personality mode switched to '{personality['name']}'",
                "personality_id": personality_id,
                "personality": personality,
                "system_prompt": prompt_text,
                "prompt": prompt_text,
                "instruction": f"Now in {personality['name']} mode. {prompt_text}"
            }
            
        except Exception as e:
            logger.error(f"Error switching personality: {e}")
            return {
                "success": False,
                "message": f"Failed to switch personality mode: {str(e)}"
            }
    
    def get_current_personality(self) -> Dict[str, Any]:
        """Get the current active personality mode."""
        try:
            if self.current_personality is not None and self.current_personality in self.personalities:
                personality = self.personalities[self.current_personality]
                
                prompt_text = personality.get("prompt", personality.get("system_prompt", ""))
                
                return {
                    "success": True,
                    "personality_id": self.current_personality,
                    "personality": personality,
                    "system_prompt": prompt_text,
                    "prompt": prompt_text
                }
            else:
                return {
                    "success": False,
                    "message": "No personality mode is currently active"
                }
        except Exception as e:
            logger.error(f"Error getting current personality: {e}")
            return {
                "success": False,
                "message": f"Failed to get current personality mode: {str(e)}"
            }
    
    def list_personalities(self) -> Dict[str, Any]:
        """List all available personality modes."""
        try:
            personality_list = []
            for pid, personality in self.personalities.items():
                personality_list.append({
                    "id": pid,
                    "name": personality["name"],
                    "description": personality["description"],
                    "active": pid == self.current_personality,  
                    "enabled": personality.get("enabled", True)
                })
            
            return {
                "success": True,
                "personalities": personality_list,
                "count": len(personality_list),
                "current": self.current_personality
            }
            
        except Exception as e:
            logger.error(f"Error listing personalities: {e}")
            return {
                "success": False,
                "message": f"Failed to list personalities: {str(e)}"
            }
    
    def add_personality(self, personality_id: str, name: str, description: str, 
                       prompt: str, enabled: bool | None = True) -> Dict[str, Any]:
        """Add a new personality mode."""
        try:
            if personality_id in self.personalities:
                return {
                    "success": False,
                    "message": f"Personality mode '{personality_id}' already exists"
                }
            
            new_personality = {
                "name": name,
                "description": description,
                "prompt": prompt,
                "enabled": bool(enabled) if enabled is not None else True
            }
            
            self.personalities[personality_id] = new_personality
            self.save_personalities()
            
            logger.info(f"Added new personality: {personality_id}")
            
            return {
                "success": True,
                "message": f"Added personality mode '{name}'",
                "personality_id": personality_id,
                "personality": new_personality
            }
            
        except Exception as e:
            logger.error(f"Error adding personality: {e}")
            return {
                "success": False,
                "message": f"Failed to add personality: {str(e)}"
            }
    
    def update_personality(self, personality_id: str, name: str = None, 
                          description: str = None, prompt: str = None,
                          enabled: bool | None = None) -> Dict[str, Any]:
        """Update an existing personality."""
        try:
            if personality_id not in self.personalities:
                return {
                    "success": False,
                    "message": f"Personality '{personality_id}' not found"
                }
            
            personality = self.personalities[personality_id]
            
            if name is not None:
                personality["name"] = name
            if description is not None:
                personality["description"] = description
            if prompt is not None:
                personality["prompt"] = prompt
            if enabled is not None:
                personality["enabled"] = bool(enabled)
            
            self.save_personalities()
            
            logger.info(f"Updated personality: {personality_id}")
            
            return {
                "success": True,
                "message": f"Successfully updated personality '{personality['name']}'",
                "personality_id": personality_id,
                "personality": personality
            }
            
        except Exception as e:
            logger.error(f"Error updating personality: {e}")
            return {
                "success": False,
                "message": f"Failed to update personality: {str(e)}"
            }
    
    def delete_personality(self, personality_id: str) -> Dict[str, Any]:
        """Delete a personality."""
        try:
            if personality_id not in self.personalities:
                return {
                    "success": False,
                    "message": f"Personality '{personality_id}' not found"
                }
            
            if personality_id == self.current_personality:
                
                self.current_personality = None
            
            deleted_personality = self.personalities.pop(personality_id)
            self.save_personalities()
            
            logger.info(f"Deleted personality: {personality_id}")
            
            return {
                "success": True,
                "message": f"Successfully deleted personality '{deleted_personality['name']}'"
            }
            
        except Exception as e:
            logger.error(f"Error deleting personality: {e}")
            return {
                "success": False,
                "message": f"Failed to delete personality: {str(e)}"
            }
    
    def get_personality_history(self, limit: int = 10) -> Dict[str, Any]:
        """Get personality switch history."""
        try:
            recent_history = self.personality_history[-limit:] if limit > 0 else self.personality_history
            
            return {
                "success": True,
                "history": recent_history,
                "count": len(recent_history),
                "total_switches": len(self.personality_history)
            }
            
        except Exception as e:
            logger.error(f"Error getting personality history: {e}")
            return {
                "success": False,
                "message": f"Failed to get personality history: {str(e)}"
            }



personality_manager = PersonalityManager()


PERSONALITY_FUNCTION_DECLARATIONS = [
    {
        "name": "switch_personality",
        "description": "Switch to a different personality mode. This changes behavior and response style.",
        "parameters": {
            "type": "object",
            "properties": {
                "personality_id": {
                    "type": "string",
                    "description": "The ID of the personality mode to switch to (e.g., 'creative', 'technical', 'casual')"
                }
            },
            "required": ["personality_id"]
        }
    },
    {
        "name": "get_current_personality",
        "description": "Get information about the currently active personality mode.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_personalities",
        "description": "List all available personality modes that can be switched to.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "add_personality",
        "description": "Add a new custom personality mode.",
        "parameters": {
            "type": "object",
            "properties": {
                "personality_id": {
                    "type": "string",
                    "description": "Unique identifier for the new personality mode"
                },
                "name": {
                    "type": "string",
                    "description": "Display name for the personality mode"
                },
                "description": {
                    "type": "string",
                    "description": "Description of the personality mode"
                },
                "prompt": {
                    "type": "string",
                    "description": "The prompt that defines how this personality mode behaves"
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether this personality is enabled (default: true)",
                    "default": True
                }
            },
            "required": ["personality_id", "name", "description", "prompt"]
        }
    },
    {
        "name": "update_personality",
        "description": "Update an existing personality (name, description, prompt, or enabled flag).",
        "parameters": {
            "type": "object",
            "properties": {
                "personality_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "prompt": {"type": "string"},
                "enabled": {"type": "boolean"}
            },
            "required": ["personality_id"]
        }
    },
    {
        "name": "get_personality_history",
        "description": "Get the history of personality mode switches.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of history entries to return",
                    "default": 10
                }
            }
        }
    }
]

async def handle_personality_function_calls(function_call):
    """Handle personality-related function calls."""
    from google.genai import types
    
    function_name = function_call.name
    args = function_call.args
    
    try:
        if function_name == "switch_personality":
            result = personality_manager.switch_personality(args["personality_id"])
        
        elif function_name == "get_current_personality":
            result = personality_manager.get_current_personality()
        
        elif function_name == "list_personalities":
            result = personality_manager.list_personalities()
        
        elif function_name == "add_personality":
            result = personality_manager.add_personality(
                personality_id=args["personality_id"],
                name=args["name"],
                description=args["description"],
                prompt=args["prompt"],
                enabled=args.get("enabled", True)
            )
        
        elif function_name == "update_personality":
            result = personality_manager.update_personality(
                personality_id=args["personality_id"],
                name=args.get("name"),
                description=args.get("description"),
                prompt=args.get("prompt"),
                enabled=args.get("enabled")
            )

        elif function_name == "get_personality_history":
            result = personality_manager.get_personality_history(
                limit=args.get("limit", 10)
            )
        
        else:
            result = {
                "success": False,
                "message": f"Unknown personality function: {function_name}"
            }
        
        return types.FunctionResponse(
            id=function_call.id,
            name=function_name,
            response=result
        )
        
    except Exception as e:
        logger.error(f"Error handling personality function call {function_name}: {e}")
        return types.FunctionResponse(
            id=function_call.id,
            name=function_name,
            response={
                "success": False,
                "message": f"Error executing {function_name}: {str(e)}"
            }
        )

def get_personality_tools():
    """Get personality tools configuration for Gemini Live API."""
    return [{"function_declarations": PERSONALITY_FUNCTION_DECLARATIONS}]
