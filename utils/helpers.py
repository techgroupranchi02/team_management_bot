import os
import re
from datetime import datetime

def normalize_phone(phone):
    """Normalize phone number to plain digits (e.g. '917667130178').
    All in-memory state should use this as the canonical key."""
    if not phone:
        return ''
    return re.sub(r'\D', '', phone.replace('whatsapp:', ''))

def validate_phone_number(phone_number):
    """Basic phone number validation"""
    clean_number = normalize_phone(phone_number)
    return len(clean_number) >= 10

def format_datetime(dt):
    """Format datetime for display"""
    if dt:
        return dt.strftime('%Y-%m-%d %H:%M')
    return "Not set"

def get_env_variable(key, default=None):
    """Get environment variable with fallback"""
    return os.getenv(key, default)