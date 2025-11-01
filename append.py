"""
Append system for automatically adding content to the system prompt.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import os
from pathlib import Path


try:
    from memory_reader import get_memory_content_for_prompt
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    get_memory_content_for_prompt = None

logger = logging.getLogger(__name__)


def load_personalities(
    personalities_path: str = "personalities.json",
    names_only: bool = False,
    include_description: bool = False,
) -> str:
    """
    Load personalities from JSON file and format them for display.
    
    Args:
        personalities_path: Path to the personalities configuration file
        
    Returns:
        Formatted string listing available personalities
    """
    try:
        with open(personalities_path, 'r', encoding='utf-8') as file:
            personalities_data = json.load(file)
            
        if not personalities_data:
            return "\n\nNo personalities available."

        
        if names_only and not include_description:
            names = [p.get('name', k) for k, p in personalities_data.items()]
            if not names:
                return "\n\nNo personalities available."
            lines = ["\n\nAvailable Personalities:"]
            for n in names:
                lines.append(f"• {n}")
            return "\n".join(lines)

        
        if include_description:
            lines = ["\n\nAvailable Personalities:"]
            for k, p in personalities_data.items():
                name = p.get('name', k)
                description = p.get('description', 'No description available')
                lines.append(f"• {name}: {description}")
            return "\n".join(lines)

        personality_list = ["\n\nAvailable Personalities:"]

        for key, personality in personalities_data.items():
            name = personality.get('name', key)
            description = personality.get('description', 'No description available')
            enabled = personality.get('enabled', True)
            status = 'ENABLED' if enabled else 'DISABLED'
            personality_list.append(f"• {name} [{status}]: {description}")

        return "\n".join(personality_list)
        
    except FileNotFoundError:
        logger.warning(f"Personalities file {personalities_path} not found.")
        return "\n\nPersonalities file not found."
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing personalities file {personalities_path}: {e}")
        return "\n\nError loading personalities."
    except Exception as e:
        logger.error(f"Unexpected error loading personalities file {personalities_path}: {e}")
        return "\n\nError loading personalities."


def load_appends(appends_path: str = "appends.json") -> Dict[str, Any]:
    """
    Load append configuration from JSON file.
    
    Args:
        appends_path: Path to the appends configuration file
        
    Returns:
        Dictionary containing append configuration
    """
    try:
        with open(appends_path, 'r', encoding='utf-8') as file:
            appends_config = json.load(file)
            logger.info(f"Loaded appends configuration from {appends_path}")
            return appends_config
    except FileNotFoundError:
        logger.warning(f"Appends file {appends_path} not found. No content will be appended.")
        return {"enabled": False, "append_items": []}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing appends file {appends_path}: {e}")
        return {"enabled": False, "append_items": []}
    except Exception as e:
        logger.error(f"Unexpected error loading appends file {appends_path}: {e}")
        return {"enabled": False, "append_items": []}


def process_append_content(
    content: str, 
    variables: Optional[Dict[str, str]] = None,
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Process append content by replacing variables.
    
    Args:
        content: The content string that may contain variables
        variables: Dictionary of variables to replace in the content
        config: Application configuration for memory integration
        
    Returns:
        Processed content string with variables replaced
    """
    if not variables:
        variables = {}
    
    
    default_variables = {
        'current_date': datetime.now().strftime('%Y-%m-%d'),
        'current_time': datetime.now().strftime('%H:%M:%S'),
        'current_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    
    if '{last_used_avatar}' in content:
        try:
            with open('last_avatar.json', 'r', encoding='utf-8') as f:
                last = json.load(f)
            if isinstance(last, dict) and last.get('id'):
                name = last.get('name') or '(unnamed)'
                author = last.get('authorName') or 'unknown author'
                default_variables['last_used_avatar'] = f"{name} by {author} (ID: {last.get('id')})"
            else:
                default_variables['last_used_avatar'] = "(not cached yet)"
        except FileNotFoundError:
            default_variables['last_used_avatar'] = "(not cached yet)"
        except Exception as e:
            logger.error(f"Error reading last_avatar.json: {e}")
            default_variables['last_used_avatar'] = "(not available)"
    
    
    if '{recent_memories}' in content and MEMORY_AVAILABLE and config and callable(get_memory_content_for_prompt):
        try:
            memory_content = get_memory_content_for_prompt(config)
            default_variables['recent_memories'] = memory_content
            logger.debug("Added memory content to variables")
        except Exception as e:
            logger.error(f"Error getting memory content: {e}")
            default_variables['recent_memories'] = ""
    else:
        
        default_variables['recent_memories'] = ""
    
    
    if '{available_personalities}' in content:
        try:
            
            names_only = False
            include_description = False
            if variables and isinstance(variables, dict):
                names_only = bool(variables.get('personalities_names_only', False))
                include_description = bool(variables.get('personalities_include_description', False))
            personalities_content = load_personalities(names_only=names_only, include_description=include_description)
            default_variables['available_personalities'] = personalities_content
            logger.debug("Added personalities content to variables")
        except Exception as e:
            logger.error(f"Error getting personalities content: {e}")
            default_variables['available_personalities'] = "\n\nError loading personalities."
    
    if '{music_files}' in content:
        try:
            tracks = []
            base = Path('sfx') / 'music'
            if base.exists():
                for p in sorted(base.glob('*')):
                    if p.is_file():
                        tracks.append(f"• {p.stem} -> music/{p.name}")
            default_variables['music_files'] = ("\n\nAvailable music files (play with play_sfx, e.g., 'music/filename.ext'):\n" + "\n".join(tracks)) if tracks else "\n\nNo music files found in sfx/music."
        except Exception as e:
            logger.error(f"Error building music files list: {e}")
            default_variables['music_files'] = "\n\nNo music files available."

    
    all_variables = {**default_variables, **variables}
    
    
    processed_content = content
    for key, value in all_variables.items():
        processed_content = processed_content.replace(f'{{{key}}}', str(value))
    
    return processed_content


def get_append_content(
    appends_config: Dict[str, Any], 
    variables: Optional[Dict[str, str]] = None,
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get all enabled append content concatenated together.
    
    Args:
        appends_config: The appends configuration dictionary
        variables: Dictionary of variables to replace in content
        config: Application configuration for memory integration
        
    Returns:
        Concatenated append content string
    """
    if not appends_config.get('enabled', False):
        logger.debug("Appends system is disabled")
        return ""
    
    append_items = appends_config.get('append_items', [])
    if not append_items:
        logger.debug("No append items found")
        return ""
    
    content_parts = []
    enabled_count = 0
    
    for item in append_items:
        if not isinstance(item, dict):
            logger.warning(f"Invalid append item format: {item}")
            continue
            
        if not item.get('enabled', False):
            logger.debug(f"Skipping disabled append item: {item.get('name', 'unnamed')}")
            continue
        
        item_content = item.get('content', '')
        if not item_content:
            logger.warning(f"Empty content for append item: {item.get('name', 'unnamed')}")
            continue
        
        
        processed_content = process_append_content(item_content, variables, config)
        content_parts.append(processed_content)
        enabled_count += 1
        
        logger.debug(f"Added append item: {item.get('name', 'unnamed')}")
    
    if enabled_count > 0:
        logger.info(f"Processed {enabled_count} append items")
        
        normalized_parts = [p.strip() for p in content_parts if isinstance(p, str) and p.strip()]
        
        seen = set()
        unique_parts = []
        for p in normalized_parts:
            if p in seen:
                logger.debug("Skipping duplicate append part")
                continue
            seen.add(p)
            unique_parts.append(p)

        if unique_parts:
            return '\n'.join(unique_parts)
        else:
            return ""
    else:
        logger.debug("No enabled append items found")
        return ""


def append_to_system_instruction(
    base_instruction: str, 
    appends_path: str = "appends.json",
    variables: Optional[Dict[str, str]] = None,
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Append content to a system instruction based on appends configuration.
    
    Args:
        base_instruction: The base system instruction
        appends_path: Path to the appends configuration file
        variables: Dictionary of variables to replace in append content
        config: Application configuration for memory integration
        
    Returns:
        System instruction with appended content
    """
    if not base_instruction:
        logger.warning("Base instruction is empty")
        return ""
    
    
    appends_config = load_appends(appends_path)
    
    
    append_content = get_append_content(appends_config, variables, config)
    
    
    if append_content:
        if base_instruction.endswith('\n'):
            final_instruction = base_instruction + append_content
        else:
            final_instruction = base_instruction + '\n' + append_content
        logger.info("System instruction enhanced with append content")
        return final_instruction
    else:
        logger.debug("No append content to add")
        return base_instruction


def list_append_items(appends_path: str = "appends.json") -> List[Dict[str, Any]]:
    """
    List all append items with their status.
    
    Args:
        appends_path: Path to the appends configuration file
        
    Returns:
        List of append items with their details
    """
    appends_config = load_appends(appends_path)
    items = []
    
    if not appends_config.get('enabled', False):
        logger.info("Appends system is globally disabled")
        return items
    
    for item in appends_config.get('append_items', []):
        if isinstance(item, dict):
            items.append({
                'name': item.get('name', 'unnamed'),
                'enabled': item.get('enabled', False),
                'content_preview': item.get('content', '')[:50] + '...' if len(item.get('content', '')) > 50 else item.get('content', '')
            })
    
    return items


def validate_appends_config(appends_config: Dict[str, Any]) -> List[str]:
    """
    Validate appends configuration and return list of issues found.
    
    Args:
        appends_config: The appends configuration to validate
        
    Returns:
        List of validation issues (empty if valid)
    """
    issues = []
    
    if not isinstance(appends_config, dict):
        issues.append("Configuration must be a dictionary")
        return issues
    
    if 'enabled' not in appends_config:
        issues.append("Missing 'enabled' field")
    elif not isinstance(appends_config['enabled'], bool):
        issues.append("'enabled' field must be a boolean")
    
    if 'append_items' not in appends_config:
        issues.append("Missing 'append_items' field")
    elif not isinstance(appends_config['append_items'], list):
        issues.append("'append_items' must be a list")
    else:
        for i, item in enumerate(appends_config['append_items']):
            if not isinstance(item, dict):
                issues.append(f"Append item {i} must be a dictionary")
                continue
            
            if 'name' not in item:
                issues.append(f"Append item {i} missing 'name' field")
            
            if 'enabled' not in item:
                issues.append(f"Append item {i} missing 'enabled' field")
            elif not isinstance(item['enabled'], bool):
                issues.append(f"Append item {i} 'enabled' field must be a boolean")
            
            if 'content' not in item:
                issues.append(f"Append item {i} missing 'content' field")
            elif not isinstance(item['content'], str):
                issues.append(f"Append item {i} 'content' field must be a string")
    
    return issues


if __name__ == "__main__":
    
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        
        print("Testing append system...")
        
        
        config = load_appends()
        issues = validate_appends_config(config)
        
        if issues:
            print("Configuration issues found:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("Configuration is valid")
        
        
        items = list_append_items()
        print(f"\nFound {len(items)} append items:")
        for item in items:
            status = "✓" if item['enabled'] else "✗"
            print(f"  {status} {item['name']}: {item['content_preview']}")
        
        
        base_prompt = "You are Gabriel, a helpful assistant."
        test_config = {
            'memory': {
                'enabled': True,
                'recent_memories_count': 3,
                'mongo': {}
            }
        }
        enhanced_prompt = append_to_system_instruction(base_prompt, config=test_config)
        
        print(f"\nBase prompt: {base_prompt}")
        print(f"Enhanced prompt: {enhanced_prompt}")
        
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        
        items = list_append_items()
        print(f"Append items ({len(items)} total):")
        for item in items:
            status = "ENABLED" if item['enabled'] else "DISABLED"
            print(f"  [{status}] {item['name']}")
            print(f"    Preview: {item['content_preview']}")
            print()
    else:
        print("Usage:")
        print("  python append.py test   - Test the append system")
        print("  python append.py list   - List all append items")
