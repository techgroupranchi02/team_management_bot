from datetime import datetime, timedelta
import mysql.connector
import json


class Task:
    def __init__(self, db_config):
        self.db_config = db_config

    def get_connection(self):
        return mysql.connector.connect(**self.db_config)

    def create_task(
        self,
        client_id,
        title,
        description,
        assigned_to,
        task_type="other",
        property_id=None,
        inventory_id=None,
        schedule_type="one_time",
        recurrence=None,
        is_photo_required=False,
    ):
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Updated query for new task_definitions table
            query = """
                INSERT INTO task_definitions 
                (client_id, title, description, assigned_to, property_id, 
                 requires_photo, created_by_id, created_by_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'client')
            """
            values = (
                client_id,
                title,
                description,
                assigned_to,
                property_id,
                is_photo_required,
                client_id,
            )  # Using client_id as created_by_id

            cursor.execute(query, values)
            task_definition_id = cursor.lastrowid

            # If it's a scheduled task, create schedule entry
            if schedule_type != "one_time" and recurrence:
                schedule_query = """
                    INSERT INTO task_schedules 
                    (task_definition_id, schedule_type, recurrence_rule, start_date)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(
                    schedule_query,
                    (
                        task_definition_id,
                        schedule_type,
                        json.dumps(recurrence),
                        datetime.now().date(),
                    ),
                )

            conn.commit()
            return task_definition_id
        finally:
            cursor.close()
            conn.close()

    def get_tasks_by_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Updated query for new structure
            query = """
                SELECT 
                    tocc.id as task_occurrence_id,
                    td.title,
                    td.description,
                    td.requires_photo,
                    td.allows_inventory_update,
                    tocc.status,
                    tocc.scheduled_date,
                    tocc.completed_at,
                    p.name as property_name,
                    tm.name as assigned_to_name,
                    tocc.assigned_to
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                LEFT JOIN properties p ON td.property_id = p.id
                LEFT JOIN team_members tm ON tocc.assigned_to = tm.id
                WHERE tocc.assigned_to = %s
                AND tocc.status != 'deleted'
                ORDER BY 
                    CASE 
                        WHEN tocc.status IN ('pending', 'in_progress') THEN 0 
                        ELSE 1 
                    END,
                    tocc.scheduled_date DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()

            # Convert datetime objects to strings for JSON serialization
            for task in tasks:
                for key in task:
                    if isinstance(task[key], datetime):
                        task[key] = task[key].isoformat()

                # Add compatibility fields
                task["id"] = task["task_occurrence_id"]
                task["display_date"] = task["scheduled_date"]
                task["is_photo_required"] = task["requires_photo"]

            return tasks
        finally:
            cursor.close()
            conn.close()

    def get_task_by_id(self, task_id, user_id=None):
        """Get specific task occurrence by ID with optional user validation"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            if user_id:
                query = """
                    SELECT tocc.*, td.title, td.description, td.requires_photo, 
                           td.allows_inventory_update
                    FROM task_occurrences tocc
                    JOIN task_definitions td ON tocc.task_definition_id = td.id
                    WHERE tocc.id = %s AND tocc.assigned_to = %s
                """
                cursor.execute(query, (task_id, user_id))
            else:
                query = """
                    SELECT tocc.*, td.title, td.description, td.requires_photo
                    FROM task_occurrences tocc
                    JOIN task_definitions td ON tocc.task_definition_id = td.id
                    WHERE tocc.id = %s
                """
                cursor.execute(query, (task_id,))

            task = cursor.fetchone()
            if task:
                # Add compatibility fields
                task["is_photo_required"] = task["requires_photo"]
            return task
        finally:
            cursor.close()
            conn.close()

    def update_task_status(self, task_id, status, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            update_data = {"status": status}

            if status == "completed":
                update_data["completed_at"] = datetime.now()

            set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
            values = list(update_data.values()) + [task_id, user_id]

            query = f"""
                UPDATE task_occurrences 
                SET {set_clause} 
                WHERE id = %s AND assigned_to = %s
            """
            cursor.execute(query, values)

            # Log the status change
            if cursor.rowcount > 0:
                self._log_task_activity(task_id, "status_change", None, status, user_id)

            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            conn.close()

    def can_complete_task(self, task_id, user_id):
        """Check if task can be completed (photo requirement check)"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            query = """
                SELECT td.requires_photo, 
                       (SELECT COUNT(*) FROM task_proofs tp WHERE tp.task_occurrence_id = %s) as proof_count
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                WHERE tocc.id = %s AND tocc.assigned_to = %s
            """
            cursor.execute(query, (task_id, task_id, user_id))
            task = cursor.fetchone()

            if not task:
                return False, "Task not found"

            # If photo is required but no proof is uploaded yet
            if task["requires_photo"] == 1 and task["proof_count"] == 0:
                return False, "photo_required"

            return True, "Task can be completed"

        finally:
            cursor.close()
            conn.close()

    def add_completion_images(self, task_id, image_url, user_id):
        """Add completion proof to task and update status if needed"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # First, get current task status and photo requirement
            query = """
                SELECT tocc.status, td.requires_photo
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                WHERE tocc.id = %s AND tocc.assigned_to = %s
            """
            cursor.execute(query, (task_id, user_id))
            task = cursor.fetchone()

            if not task:
                return False, "Task not found"

            # Add proof to task_proofs table
            insert_query = """
                INSERT INTO task_proofs 
                (task_occurrence_id, file_name, uploaded_by_id, uploaded_by_type)
                VALUES (%s, %s, %s, 'team_member')
            """
            cursor.execute(insert_query, (task_id, image_url, user_id))

            # If task was waiting for photo and now has one, auto-complete it
            if task["status"] != "completed" and task["requires_photo"] == 1:
                status_query = """
                    UPDATE task_occurrences 
                    SET status = 'completed', completed_at = %s 
                    WHERE id = %s AND assigned_to = %s
                """
                cursor.execute(status_query, (datetime.now(), task_id, user_id))

                # Log completion
                self._log_task_activity(
                    task_id, "status_change", task["status"], "completed", user_id
                )

                conn.commit()
                return True, "completed"

            # Log photo addition
            self._log_task_activity(task_id, "photo_added", None, image_url, user_id)

            conn.commit()
            return True, "image_added"

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            cursor.close()
            conn.close()

    def get_recent_completed_task(self, user_id):
        """Get most recently completed task without proof"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            query = """
                SELECT tocc.*, td.title, td.requires_photo, p.name as property_name
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                LEFT JOIN properties p ON td.property_id = p.id
                WHERE tocc.assigned_to = %s 
                AND tocc.status = 'completed' 
                AND td.requires_photo = 1
                AND NOT EXISTS (
                    SELECT 1 FROM task_proofs tp 
                    WHERE tp.task_occurrence_id = tocc.id
                )
                ORDER BY tocc.completed_at DESC 
                LIMIT 1
            """
            cursor.execute(query, (user_id,))
            task = cursor.fetchone()

            if task:
                # Convert datetime objects
                for key in task:
                    if isinstance(task[key], datetime):
                        task[key] = task[key].isoformat()

                # Add compatibility fields
                task["is_photo_required"] = task["requires_photo"]

            return task
        finally:
            cursor.close()
            conn.close()

    def get_pending_photo_tasks(self, user_id):
        """Get tasks that require photos but don't have proof yet"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            query = """
                SELECT 
                    tocc.id as task_occurrence_id,
                    td.title,
                    td.description,
                    td.requires_photo,
                    td.allows_inventory_update,
                    tocc.status,
                    tocc.scheduled_date,
                    tocc.completed_at,
                    p.name as property_name
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                LEFT JOIN properties p ON td.property_id = p.id
                WHERE tocc.assigned_to = %s 
                AND td.requires_photo = 1
                AND NOT EXISTS (
                    SELECT 1 FROM task_proofs tp 
                    WHERE tp.task_occurrence_id = tocc.id
                )
                AND tocc.status IN ('pending', 'in_progress', 'completed')
                ORDER BY 
                    CASE 
                        WHEN tocc.status IN ('pending', 'in_progress') THEN 0 
                        ELSE 1 
                    END,
                    tocc.scheduled_date DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()

            for task in tasks:
                # Convert datetime objects
                for key in task:
                    if isinstance(task[key], datetime):
                        task[key] = task[key].isoformat()

                # Add compatibility fields
                task["id"] = task["task_occurrence_id"]
                task["is_photo_required"] = task["requires_photo"]
                task["display_date"] = task["scheduled_date"]

            return tasks
        finally:
            cursor.close()
            conn.close()

    def get_task_with_images(self, user_id):
        """Get tasks that have completion proof"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            query = """
                SELECT 
                    tocc.*,
                    td.title,
                    td.description,
                    p.name as property_name,
                    GROUP_CONCAT(tp.file_name) as proof_files
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                LEFT JOIN properties p ON td.property_id = p.id
                LEFT JOIN task_proofs tp ON tocc.id = tp.task_occurrence_id
                WHERE tocc.assigned_to = %s 
                AND tp.id IS NOT NULL
                GROUP BY tocc.id
                ORDER BY tocc.completed_at DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()

            for task in tasks:
                # Convert datetime objects
                for key in task:
                    if isinstance(task[key], datetime):
                        task[key] = task[key].isoformat()

            return tasks
        finally:
            cursor.close()
            conn.close()

    def get_inventory_by_property(self, property_id):
        """Get all inventory items for a specific property"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            query = """
                SELECT id, name, category, quantity as current_quantity, unit, located_at
                FROM inventory
                WHERE property_id = %s
                ORDER BY name
            """
            cursor.execute(query, (property_id,))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def search_inventory_by_keyword(self, client_id, search_term):
        """Search inventory items across all properties for a client by keyword matching"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Split search term into individual words for multi-word matching
            words = search_term.strip().split()
            
            # Build conditions: each word must match name, category, or located_at
            conditions = []
            params = []
            for word in words:
                like_pattern = f"%{word}%"
                conditions.append(
                    "(i.name LIKE %s OR i.category LIKE %s OR i.located_at LIKE %s OR p.name LIKE %s)"
                )
                params.extend([like_pattern, like_pattern, like_pattern, like_pattern])
            
            where_clause = " AND ".join(conditions)
            
            query = f"""
                SELECT i.id, i.name, i.category, i.quantity as current_quantity, 
                       i.unit, i.located_at, i.property_id,
                       p.name as property_name
                FROM inventory i
                JOIN properties p ON i.property_id = p.id
                WHERE p.client_id = %s AND ({where_clause})
                ORDER BY p.name, i.name
            """
            params.insert(0, client_id)
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def _log_task_activity(
        self, task_occurrence_id, activity_type, old_value, new_value, changed_by_id
    ):
        """Log task activity to task_activity_log table"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            query = """
                INSERT INTO task_activity_log 
                (task_occurrence_id, activity_type, old_value, new_value, changed_by_id, changed_by_type)
                VALUES (%s, %s, %s, %s, %s, 'team_member')
            """
            cursor.execute(
                query,
                (
                    task_occurrence_id,
                    activity_type,
                    old_value,
                    new_value,
                    changed_by_id,
                ),
            )
            conn.commit()

            cursor.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error logging task activity: {e}")
            return False

    def add_completion_images_direct(self, task_id, image_filename, user_id):
        """Add completion image directly to database (fallback method)"""
        try:
            connection = self.get_connection()
            cursor = connection.cursor(dictionary=True)

            # Add proof to task_proofs table
            cursor.execute(
                """
                INSERT INTO task_proofs 
                (task_occurrence_id, file_name, uploaded_by_id, uploaded_by_type)
                VALUES (%s, %s, %s, 'team_member')
            """,
                (task_id, image_filename, user_id),
            )

            # Update task status if it requires photo
            cursor.execute(
                """
                UPDATE task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                SET tocc.status = 'completed', 
                    tocc.completed_at = NOW()
                WHERE tocc.id = %s
                AND td.requires_photo = 1
            """,
                (task_id,),
            )

            connection.commit()
            cursor.close()
            connection.close()

            return True
        except Exception as e:
            print(f"❌ Error adding completion image directly: {e}")
            return False
        
    def get_recurring_tasks_by_user(self, user_id):
        """Get recurring tasks assigned to a specific user - NEW DATABASE STRUCTURE"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            query = """
                SELECT 
                    td.id as task_definition_id,
                    td.title,
                    td.description,
                    td.requires_photo,
                    ts.schedule_type as recurrence,
                    'active' as status,
                    p.name as property_name
                FROM task_definitions td
                LEFT JOIN task_schedules ts ON td.id = ts.task_definition_id
                LEFT JOIN properties p ON td.property_id = p.id
                WHERE td.assigned_to = %s
                AND ts.schedule_type IS NOT NULL
                AND td.is_archived = 0
                ORDER BY td.created_at DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()

            for task in tasks:
                # Convert datetime objects
                for key in task:
                    if isinstance(task[key], datetime):
                        task[key] = task[key].isoformat()
                
                # Add compatibility fields
                task['recurrence'] = task.get('schedule_type', 'one_time')

            return tasks
        finally:
            cursor.close()
            conn.close()  


    def get_recurring_tasks_due_for_reminder(self):
        """Get recurring tasks that need reminders based on their schedule"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Get all recurring tasks
            query = """
                SELECT 
                    td.id,
                    td.title,
                    td.description,
                    td.assigned_to,
                    ts.schedule_type as recurrence,
                    ts.start_date,
                    ts.recurrence_rule,
                    tm.phone,
                    tm.name as team_member_name,
                    p.name as property_name
                FROM task_definitions td
                JOIN task_schedules ts ON td.id = ts.task_definition_id
                JOIN team_members tm ON td.assigned_to = tm.id
                LEFT JOIN properties p ON td.property_id = p.id
                WHERE td.is_archived = 0
                AND ts.schedule_type IS NOT NULL
            """
            cursor.execute(query)
            tasks = cursor.fetchall()
            
            # Filter tasks that need reminders today
            today = datetime.now().date()
            tasks_due = []
            
            for task in tasks:
                start_date = task['start_date']
                if isinstance(start_date, datetime):
                    start_date = start_date.date()
                
                recurrence = task['recurrence']
                
                # Simple logic to determine if task needs reminder today
                # You can enhance this based on your recurrence rules
                needs_reminder = False
                
                if recurrence == 'daily':
                    # Daily tasks always need reminder
                    needs_reminder = True
                elif recurrence == 'weekly':
                    # Check if it's the same day of week as start_date
                    if today.weekday() == start_date.weekday():
                        needs_reminder = True
                elif recurrence == 'monthly':
                    # Check if it's the same day of month as start_date
                    if today.day == start_date.day:
                        needs_reminder = True
                
                if needs_reminder:
                    tasks_due.append(task)
            
            cursor.close()
            conn.close()
            return tasks_due
            
        except Exception as e:
            print(f"Error getting recurring tasks for reminder: {e}")
            import traceback
            traceback.print_exc()
            return []     


    def update_task_reminder(self, task_id, user_id):
        """Update task reminder tracking after sending reminder"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Check if there's a task_reminders table, if not, create one or just log
            # For now, we'll just log and return success
            query = """
                INSERT INTO task_reminder_logs 
                (task_definition_id, team_member_id, sent_at, reminder_type)
                VALUES (%s, %s, NOW(), 'recurring')
            """
            cursor.execute(query, (task_id, user_id))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating task reminder: {e}")
            # If table doesn't exist, just log and return True to avoid breaking
            return True       

    def search_tasks_by_keyword(self, user_id, search_term):
        """Search task occurrences by keyword in title/description/property name."""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            words = search_term.strip().split()
            conditions = []
            params = [user_id]

            for word in words:
                like_pattern = f"%{word}%"
                conditions.append(
                    "(td.title LIKE %s OR td.description LIKE %s OR p.name LIKE %s)"
                )
                params.extend([like_pattern, like_pattern, like_pattern])

            where_clause = " AND ".join(conditions)

            query = f"""
                SELECT 
                    tocc.id as task_occurrence_id,
                    td.title, td.description, td.requires_photo,
                    td.allows_inventory_update,
                    tocc.status, tocc.scheduled_date, tocc.completed_at,
                    p.name as property_name,
                    tm.name as assigned_to_name,
                    tocc.assigned_to
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                LEFT JOIN properties p ON td.property_id = p.id
                LEFT JOIN team_members tm ON tocc.assigned_to = tm.id
                WHERE tocc.assigned_to = %s
                  AND tocc.status != 'deleted'
                  AND ({where_clause})
                ORDER BY 
                    CASE 
                        WHEN tocc.status IN ('pending', 'in_progress') THEN 0 
                        ELSE 1 
                    END,
                    tocc.scheduled_date DESC
                LIMIT 10
            """
            cursor.execute(query, params)
            tasks = cursor.fetchall()

            for task in tasks:
                for key in task:
                    if isinstance(task[key], datetime):
                        task[key] = task[key].isoformat()
                task['id'] = task['task_occurrence_id']
                task['display_date'] = task.get('scheduled_date')
                task['is_photo_required'] = task['requires_photo']

            return tasks
        finally:
            cursor.close()
            conn.close()

    def search_properties_by_keyword(self, client_id, search_term):
        """Search properties by keyword in name/address."""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            words = search_term.strip().split()
            conditions = []
            params = [client_id]

            for word in words:
                like_pattern = f"%{word}%"
                conditions.append("(p.name LIKE %s OR p.address LIKE %s)")
                params.extend([like_pattern, like_pattern])

            where_clause = " AND ".join(conditions)

            query = f"""
                SELECT p.id, p.name, p.address, p.google_map_link,
                       (SELECT COUNT(*) FROM task_definitions td 
                        WHERE td.property_id = p.id) as total_tasks,
                       (SELECT COUNT(*) FROM inventory i 
                        WHERE i.property_id = p.id) as total_inventory
                FROM properties p
                WHERE p.client_id = %s AND ({where_clause})
                ORDER BY p.name
                LIMIT 10
            """
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def get_clients_for_phone(self, phone_number):
        """Get all clients that have a team member with this phone number."""
        import re
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            digits = re.sub(r'\D', '', phone_number.replace('whatsapp:', ''))
            last_10 = digits[-10:] if len(digits) >= 10 else digits

            query = """
                SELECT DISTINCT c.id, c.name
                FROM clients c
                JOIN team_members tm ON tm.client_id = c.id
                WHERE tm.phone LIKE %s AND tm.status = 'active'
                ORDER BY c.name
            """
            cursor.execute(query, (f'%{last_10}',))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def search_clients_by_keyword(self, search_term, phone_number=None):
        """Search clients by name (fuzzy match), filtered to team member's clients if phone provided."""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            like_term = f"%{search_term}%"

            if phone_number:
                import re
                digits = re.sub(r'\D', '', phone_number.replace('whatsapp:', ''))
                last_10 = digits[-10:] if len(digits) >= 10 else digits

                query = """
                    SELECT DISTINCT c.id, c.name
                    FROM clients c
                    JOIN team_members tm ON tm.client_id = c.id
                    WHERE c.name LIKE %s
                      AND tm.phone LIKE %s
                      AND tm.status = 'active'
                    ORDER BY c.name
                    LIMIT 5
                """
                cursor.execute(query, (like_term, f'%{last_10}'))
            else:
                query = """
                    SELECT id, name
                    FROM clients 
                    WHERE name LIKE %s
                    ORDER BY name
                    LIMIT 5
                """
                cursor.execute(query, (like_term,))

            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def get_client_by_id(self, client_id):
        """Get a single client by ID."""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id, name FROM clients WHERE id = %s", (client_id,))
            return cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

    def ensure_search_history_table(self):
        """Create search_history table if it doesn't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    team_member_id INT NOT NULL,
                    search_term VARCHAR(255) NOT NULL,
                    search_scope VARCHAR(20) DEFAULT 'all',
                    result_count INT DEFAULT 0,
                    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_member_search (team_member_id, searched_at DESC)
                )
            """)
            conn.commit()
            print("✅ search_history table ensured")
        except Exception as e:
            print(f"⚠️ Error creating search_history table: {e}")
        finally:
            cursor.close()
            conn.close()

    def save_search_history(self, team_member_id, search_term, scope='all', result_count=0):
        """Save a search to history."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO search_history 
                (team_member_id, search_term, search_scope, result_count)
                VALUES (%s, %s, %s, %s)
            """, (team_member_id, search_term, scope, result_count))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Error saving search history: {e}")
        finally:
            cursor.close()
            conn.close()

    def get_recent_searches(self, team_member_id, limit=5):
        """Get recent unique searches for a user."""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            query = """
                SELECT search_term, search_scope, result_count,
                       MAX(searched_at) as last_searched
                FROM search_history
                WHERE team_member_id = %s
                GROUP BY search_term, search_scope, result_count
                ORDER BY last_searched DESC
                LIMIT %s
            """
            cursor.execute(query, (team_member_id, limit))
            return cursor.fetchall()
        except Exception as e:
            print(f"⚠️ Error getting search history: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
