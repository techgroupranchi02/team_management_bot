import os
from datetime import datetime

def validate_phone_number(phone_number):
    """Basic phone number validation"""
    # Remove whatsapp: prefix and any non-digit characters
    clean_number = ''.join(filter(str.isdigit, phone_number.replace('whatsapp:', '')))
    return len(clean_number) >= 10

def format_datetime(dt):
    """Format datetime for display"""
    if dt:
        return dt.strftime('%Y-%m-%d %H:%M')
    return "Not set"

def get_env_variable(key, default=None):
    """Get environment variable with fallback"""
    return os.getenv(key, default)