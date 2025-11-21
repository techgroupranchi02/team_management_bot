from datetime import datetime
from bson import ObjectId

class User:
    def __init__(self, db):
        self.collection = db.users

    def create_user(self, phone_number, name, role="member", team_id=None):
        # Clean phone number - store without country code for flexibility
        clean_phone = self.clean_phone_number_for_storage(phone_number)
        
        user_data = {
            "phone_number": clean_phone,
            "name": name,
            "role": role,
            "team_id": ObjectId(team_id) if team_id else None,
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        result = self.collection.insert_one(user_data)
        return str(result.inserted_id)

    def find_by_phone(self, phone_number):
        # Try multiple phone number formats
        possible_numbers = self.get_possible_phone_formats(phone_number)
        
        for possible_number in possible_numbers:
            user = self.collection.find_one({"phone_number": possible_number, "is_active": True})
            if user:
                # Convert ObjectId to string for easier handling
                user['_id'] = str(user['_id'])
                if user.get('team_id'):
                    user['team_id'] = str(user['team_id'])
                print(f"✅ User found with phone format: {possible_number}")
                return user
        
        print(f"❌ User not found. Tried formats: {possible_numbers}")
        return None

    def clean_phone_number_for_storage(self, phone_number):
        """Clean phone number for storage (prefer without country code)"""
        if not phone_number:
            return ""
        
        # Remove whatsapp: prefix if present
        clean = phone_number.replace('whatsapp:', '')
        # Remove all non-digit characters
        clean = ''.join(filter(str.isdigit, clean))
        
        # Remove country code if present (91 for India)
        if clean.startswith('91') and len(clean) == 12:
            clean = clean[2:]  # Remove '91' prefix
        
        return clean

    def get_possible_phone_formats(self, phone_number):
        """Generate all possible phone number formats to try"""
        if not phone_number:
            return []
        
        # Remove whatsapp: prefix
        clean = phone_number.replace('whatsapp:', '')
        # Remove all non-digit characters
        digits_only = ''.join(filter(str.isdigit, clean))
        
        possible_formats = []
        
        # Original format from Twilio (with + and country code)
        if phone_number:
            possible_formats.append(phone_number.replace('whatsapp:', ''))
        
        # Digits only (exactly as received)
        if digits_only:
            possible_formats.append(digits_only)
        
        # Without country code (if it has 91 prefix)
        if digits_only.startswith('91') and len(digits_only) == 12:
            possible_formats.append(digits_only[2:])  # Remove 91
        
        # With country code (if it doesn't have it)
        if len(digits_only) == 10:
            possible_formats.append('91' + digits_only)  # Add 91
        
        # Remove duplicates and return
        return list(set(possible_formats))

    def get_user_tasks(self, user_id):
        from .task import Task
        task_model = Task(self.collection.database)
        return task_model.get_tasks_by_user(user_id)