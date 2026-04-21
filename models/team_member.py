import logging
logger = logging.getLogger(__name__)
import mysql.connector
import re

class TeamMember:
    def __init__(self, db_config):
        self.db_config = db_config
        self._ensure_phone_last_10_column()

    def get_connection(self):
        try:
            from models.db_pool import get_pooled_connection
            return get_pooled_connection()
        except Exception:
            return mysql.connector.connect(**self.db_config)

    def _ensure_phone_last_10_column(self):
        """Add phone_last_10 indexed column if it doesn't exist, and backfill it."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Check if column exists
            cursor.execute("""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'team_members'
                AND COLUMN_NAME = 'phone_last_10'
            """)
            if not cursor.fetchone():
                logger.info(" Adding phone_last_10 column to team_members...")
                cursor.execute("ALTER TABLE team_members ADD COLUMN phone_last_10 VARCHAR(10) DEFAULT NULL")
                cursor.execute("CREATE INDEX idx_team_members_phone_last_10 ON team_members(phone_last_10)")
                # Backfill existing rows
                cursor.execute("UPDATE team_members SET phone_last_10 = RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) WHERE phone IS NOT NULL")
                conn.commit()
                logger.info(" phone_last_10 column added and backfilled")
        except Exception as e:
            logger.warning(f" phone_last_10 migration skipped: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

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

    def _get_last_10(self, phone_number):
        """Extract last 10 digits from a phone number."""
        digits = self.clean_phone_number(phone_number)
        return digits[-10:] if len(digits) >= 10 else digits

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
                    return member
            
            # If exact match fails, try indexed phone_last_10 column
            last_10 = self._get_last_10(phone_number)
            if last_10:
                query = "SELECT * FROM team_members WHERE phone_last_10 = %s AND status = 'active'"
                cursor.execute(query, (last_10,))
                member = cursor.fetchone()
                if member:
                    return member
            
            return None
        finally:
            cursor.close()
            conn.close()

    def find_all_by_phone(self, phone_number):
        """Find ALL team members matching this phone number across clients.
        Returns a list of member dicts (may have multiple for different clients)."""
        possible_numbers = self.get_possible_phone_formats(phone_number)

        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            members = []
            seen_ids = set()

            # Exact match
            for possible_number in possible_numbers:
                query = "SELECT * FROM team_members WHERE phone = %s AND status = 'active'"
                cursor.execute(query, (possible_number,))
                for row in cursor.fetchall():
                    if row['id'] not in seen_ids:
                        members.append(row)
                        seen_ids.add(row['id'])

            # Indexed phone_last_10 match if no exact matches
            if not members:
                last_10 = self._get_last_10(phone_number)
                if last_10:
                    query = "SELECT * FROM team_members WHERE phone_last_10 = %s AND status = 'active'"
                    cursor.execute(query, (last_10,))
                    for row in cursor.fetchall():
                        if row['id'] not in seen_ids:
                            members.append(row)
                            seen_ids.add(row['id'])

            return members
        finally:
            cursor.close()
            conn.close()

    def find_by_phone_and_client(self, phone_number, client_id):
        """Find team member by phone number AND specific client_id."""
        possible_numbers = self.get_possible_phone_formats(phone_number)

        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Try exact match first
            for possible_number in possible_numbers:
                query = "SELECT * FROM team_members WHERE phone = %s AND client_id = %s AND status = 'active'"
                cursor.execute(query, (possible_number, client_id))
                member = cursor.fetchone()
                if member:
                    return member

            # Indexed phone_last_10 match
            last_10 = self._get_last_10(phone_number)
            if last_10:
                query = "SELECT * FROM team_members WHERE phone_last_10 = %s AND client_id = %s AND status = 'active'"
                cursor.execute(query, (last_10, client_id))
                member = cursor.fetchone()
                if member:
                    return member

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
            logger.error(" No phone number provided")
            return []
        
        # Remove whatsapp: prefix
        clean = phone_number.replace('whatsapp:', '')
        
        # Get digits only
        digits_only = self.clean_phone_number(clean)
        
        possible_formats = []
        
        # Original format from Meta (with country code, no +)
        if digits_only:
            possible_formats.append(digits_only)
        
        # Try with + prefix
        if digits_only:
            possible_formats.append(f"+{digits_only}")
        
        # Remove country code for Indian numbers (91)
        if digits_only.startswith('91') and len(digits_only) > 10:
            possible_formats.append(digits_only[2:])  # Remove country code
        
        # Add country code if missing (for 10-digit numbers)
        if len(digits_only) == 10:
            possible_formats.append('91' + digits_only)  # Add Indian country code
        
        # Last 10 digits
        if len(digits_only) >= 10:
            possible_formats.append(digits_only[-10:])  # Last 10 digits
        
        # Try with 0 prefix
        if len(digits_only) == 10:
            possible_formats.append('0' + digits_only)
        
        logger.debug(f" Phone lookup formats for '{phone_number}': {possible_formats}")
        # Remove duplicates and return
        return list(set([fmt for fmt in possible_formats if fmt]))