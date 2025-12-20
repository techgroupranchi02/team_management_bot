import mysql.connector
import re

class TeamMember:
    def __init__(self, db_config):
        self.db_config = db_config

    def get_connection(self):
        return mysql.connector.connect(**self.db_config)

    def create_team_member(self, client_id, name, role, phone, status="active"):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                INSERT INTO team_members (client_id, name, role, phone, status)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(query, (client_id, name, role, phone, status))
            conn.commit()
            return cursor.lastrowid
        finally:
            cursor.close()
            conn.close()

    def find_by_phone(self, phone_number):
        # Try multiple phone number formats
        possible_numbers = self.get_possible_phone_formats(phone_number)
        
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Try exact match first
            for possible_number in possible_numbers:
                query = "SELECT * FROM team_members WHERE phone = %s AND status = 'active'"
                cursor.execute(query, (possible_number,))
                member = cursor.fetchone()
                
                if member:
                    print(f"✅ Team member found with phone: {possible_number}")
                    return member
            
            # If exact match fails, try partial match (last 10 digits)
            for possible_number in possible_numbers:
                clean_number = self.clean_phone_number(possible_number)
                if len(clean_number) >= 10:
                    last_10_digits = clean_number[-10:]
                    
                    query = "SELECT * FROM team_members WHERE phone LIKE %s AND status = 'active'"
                    cursor.execute(query, (f'%{last_10_digits}',))
                    member = cursor.fetchone()
                    
                    if member:
                        print(f"✅ Team member found with partial phone match: {last_10_digits}")
                        return member
            
            print(f"❌ Team member not found. Tried formats: {possible_numbers}")
            return None
        finally:
            cursor.close()
            conn.close()

    def clean_phone_number(self, phone_number):
        """Clean phone number - remove all non-digit characters"""
        if not phone_number:
            return ""
        return re.sub(r'\D', '', phone_number)

    def get_possible_phone_formats(self, phone_number):
        """Generate all possible phone number formats to try"""
        if not phone_number:
            return []
        
        # Remove whatsapp: prefix
        clean = phone_number.replace('whatsapp:', '')
        
        # Get digits only
        digits_only = self.clean_phone_number(clean)
        
        possible_formats = []
        
        # Original format from Twilio (with + and country code)
        if phone_number:
            possible_formats.append(phone_number.replace('whatsapp:', ''))
        
        # Digits only (exactly as received)
        if digits_only:
            possible_formats.append(digits_only)
        
        # Without country code (if it has country code)
        if digits_only.startswith('91') and len(digits_only) > 10:
            possible_formats.append(digits_only[2:])  # Remove country code
        
        # With country code (if it doesn't have it)
        if len(digits_only) == 10:
            possible_formats.append('91' + digits_only)  # Add country code
        
        # Also try without any country code (just the local number)
        if len(digits_only) >= 10:
            possible_formats.append(digits_only[-10:])  # Last 10 digits
        
        # Remove duplicates and return
        return list(set([fmt for fmt in possible_formats if fmt]))