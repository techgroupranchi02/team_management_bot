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
                ORDER BY tocc.scheduled_date DESC
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
                ORDER BY tocc.scheduled_date DESC
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
