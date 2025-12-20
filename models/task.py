from datetime import datetime, timedelta
import mysql.connector

class Task:
    def __init__(self, db_config):
        self.db_config = db_config

    def get_connection(self):
        return mysql.connector.connect(**self.db_config)

    def create_task(self, client_id, title, description, assigned_to, task_type="other", 
                   property_id=None, inventory_id=None, schedule_type="one_time", 
                   recurrence=None, is_photo_required=False):
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                INSERT INTO tasks 
                (client_id, title, description, task_type, property_id, inventory_id, 
                 assigned_to, schedule_type, recurrence, is_photo_required, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """
            values = (client_id, title, description, task_type, property_id, inventory_id,
                     assigned_to, schedule_type, recurrence, is_photo_required)
            
            cursor.execute(query, values)
            conn.commit()
            return cursor.lastrowid
        finally:
            cursor.close()
            conn.close()

    def get_tasks_by_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                SELECT t.*, p.name as property_name, tm.name as assigned_to_name
                FROM tasks t
                LEFT JOIN properties p ON t.property_id = p.id
                LEFT JOIN team_members tm ON t.assigned_to = tm.id
                WHERE t.assigned_to = %s
                ORDER BY t.created_at DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()
            
            # Convert datetime objects to strings for JSON serialization
            for task in tasks:
                if task.get('created_at'):
                    task['created_at'] = task['created_at'].isoformat()
                if task.get('updated_at'):
                    task['updated_at'] = task['updated_at'].isoformat()
                if task.get('completed_at'):
                    task['completed_at'] = task['completed_at'].isoformat()
            
            return tasks
        finally:
            cursor.close()
            conn.close()

    def get_task_by_id(self, task_id, user_id=None):
        """Get specific task by ID with optional user validation"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            if user_id:
                query = "SELECT * FROM tasks WHERE id = %s AND assigned_to = %s"
                cursor.execute(query, (task_id, user_id))
            else:
                query = "SELECT * FROM tasks WHERE id = %s"
                cursor.execute(query, (task_id,))
            
            task = cursor.fetchone()
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
                # Don't clear completion image when marking as completed
                # Only update completion_image if it's being set
            
            set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
            values = list(update_data.values()) + [task_id, user_id]
            
            query = f"UPDATE tasks SET {set_clause} WHERE id = %s AND assigned_to = %s"
            cursor.execute(query, values)
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
                SELECT is_photo_required, completion_image 
                FROM tasks 
                WHERE id = %s AND assigned_to = %s
            """
            cursor.execute(query, (task_id, user_id))
            task = cursor.fetchone()
            
            if not task:
                return False, "Task not found"
            
            # If photo is required but no image is uploaded yet
            if task['is_photo_required'] == 1 and not task['completion_image']:
                return False, "photo_required"
            
            return True, "Task can be completed"
            
        finally:
            cursor.close()
            conn.close()

    def add_completion_image(self, task_id, image_url, user_id):
        """Add completion image URL to task and update status if needed"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # First, get current task status and photo requirement
            query = "SELECT status, is_photo_required FROM tasks WHERE id = %s AND assigned_to = %s"
            cursor.execute(query, (task_id, user_id))
            task = cursor.fetchone()
            
            if not task:
                return False, "Task not found"
            
            # Update the image
            update_query = """
                UPDATE tasks 
                SET completion_image = %s, image_added_at = %s 
                WHERE id = %s AND assigned_to = %s
            """
            cursor.execute(update_query, (image_url, datetime.now(), task_id, user_id))
            
            # If task was waiting for photo and now has one, auto-complete it
            if task['status'] != 'completed' and task['is_photo_required'] == 1:
                status_query = "UPDATE tasks SET status = 'completed', completed_at = %s WHERE id = %s AND assigned_to = %s"
                cursor.execute(status_query, (datetime.now(), task_id, user_id))
                conn.commit()
                return True, "completed"
            
            conn.commit()
            return True, "image_added"
            
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            cursor.close()
            conn.close()

    def get_recent_completed_task(self, user_id):
        """Get most recently completed task without completion image"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                SELECT t.*, p.name as property_name
                FROM tasks t
                LEFT JOIN properties p ON t.property_id = p.id
                WHERE t.assigned_to = %s 
                AND t.status = 'completed' 
                AND (t.completion_image IS NULL OR t.completion_image = '')
                ORDER BY t.completed_at DESC 
                LIMIT 1
            """
            cursor.execute(query, (user_id,))
            task = cursor.fetchone()
            
            if task and task.get('completed_at'):
                task['completed_at'] = task['completed_at'].isoformat()
            if task and task.get('created_at'):
                task['created_at'] = task['created_at'].isoformat()
            
            return task
        finally:
            cursor.close()
            conn.close()

    def get_pending_photo_tasks(self, user_id):
        """Get tasks that are marked as completed but waiting for photos"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                SELECT t.*, p.name as property_name
                FROM tasks t
                LEFT JOIN properties p ON t.property_id = p.id
                WHERE t.assigned_to = %s 
                AND t.status = 'completed'
                AND t.is_photo_required = 1
                AND (t.completion_image IS NULL OR t.completion_image = '')
                ORDER BY t.completed_at DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()
            
            for task in tasks:
                if task.get('completed_at'):
                    task['completed_at'] = task['completed_at'].isoformat()
                if task.get('created_at'):
                    task['created_at'] = task['created_at'].isoformat()
            
            return tasks
        finally:
            cursor.close()
            conn.close()

    def get_task_with_images(self, user_id):
        """Get tasks that have completion images"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                SELECT t.*, p.name as property_name
                FROM tasks t
                LEFT JOIN properties p ON t.property_id = p.id
                WHERE t.assigned_to = %s 
                AND t.completion_image IS NOT NULL 
                AND t.completion_image != ''
                ORDER BY t.completed_at DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()
            
            for task in tasks:
                if task.get('completed_at'):
                    task['completed_at'] = task['completed_at'].isoformat()
                if task.get('created_at'):
                    task['created_at'] = task['created_at'].isoformat()
            
            return tasks
        finally:
            cursor.close()
            conn.close()

    def get_recurring_tasks_due_for_reminder(self):
        """Get recurring tasks that are due for reminders based on their recurrence pattern"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                SELECT 
                    t.*,
                    tm.phone,
                    tm.name as team_member_name,
                    tr.reminder_sent_at,
                    tr.next_reminder_date
                FROM tasks t
                JOIN team_members tm ON t.assigned_to = tm.id
                LEFT JOIN task_reminders tr ON t.id = tr.task_id AND t.assigned_to = tr.team_member_id
                WHERE t.schedule_type = 'recurring'
                AND t.recurrence IN ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')
                AND t.status IN ('pending', 'in_progress')
                AND (
                    tr.next_reminder_date IS NULL 
                    OR tr.next_reminder_date <= CURDATE()
                    OR tr.reminder_sent_at IS NULL
                    OR DATE(tr.reminder_sent_at) < CURDATE()
                )
            """
            cursor.execute(query)
            tasks = cursor.fetchall()
            
            # Convert datetime objects to strings for JSON serialization
            for task in tasks:
                if task.get('created_at'):
                    task['created_at'] = task['created_at'].isoformat()
                if task.get('updated_at'):
                    task['updated_at'] = task['updated_at'].isoformat()
                if task.get('completed_at'):
                    task['completed_at'] = task['completed_at'].isoformat()
                if task.get('reminder_sent_at'):
                    task['reminder_sent_at'] = task['reminder_sent_at'].isoformat()
                if task.get('next_reminder_date'):
                    task['next_reminder_date'] = task['next_reminder_date'].isoformat()
            
            return tasks
        finally:
            cursor.close()
            conn.close()

    def update_task_reminder(self, task_id, team_member_id):
        """Update reminder tracking for a task"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Get task recurrence pattern
            query = "SELECT recurrence FROM tasks WHERE id = %s"
            cursor.execute(query, (task_id,))
            task = cursor.fetchone()
            
            if not task:
                return False
            
            recurrence = task['recurrence']
            next_reminder_date = self._calculate_next_reminder_date(recurrence)
            
            # Insert or update reminder record
            upsert_query = """
                INSERT INTO task_reminders (task_id, team_member_id, reminder_sent_at, next_reminder_date)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                reminder_sent_at = VALUES(reminder_sent_at),
                next_reminder_date = VALUES(next_reminder_date)
            """
            cursor.execute(upsert_query, (task_id, team_member_id, datetime.now(), next_reminder_date))
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"Error updating task reminder: {e}")
            return False
        finally:
            cursor.close()
            conn.close()

    def _calculate_next_reminder_date(self, recurrence):
        """Calculate next reminder date based on recurrence pattern"""
        today = datetime.now().date()
        
        if recurrence == 'daily':
            return today + timedelta(days=1)
        elif recurrence == 'weekly':
            return today + timedelta(weeks=1)
        elif recurrence == 'monthly':
            # Add approximately one month
            next_month = today.month + 1
            next_year = today.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            return today.replace(year=next_year, month=next_month)
        elif recurrence == 'quarterly':
            # Add 3 months
            next_month = today.month + 3
            next_year = today.year
            if next_month > 12:
                next_month -= 12
                next_year += 1
            return today.replace(year=next_year, month=next_month)
        elif recurrence == 'yearly':
            return today.replace(year=today.year + 1)
        else:
            return today + timedelta(days=1)  # Default to daily

    def get_recurring_tasks_by_user(self, user_id):
        """Get recurring tasks assigned to a specific user"""
        conn = self.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            query = """
                SELECT t.*, p.name as property_name
                FROM tasks t
                LEFT JOIN properties p ON t.property_id = p.id
                WHERE t.assigned_to = %s
                AND t.schedule_type = 'recurring'
                AND t.recurrence IN ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')
                ORDER BY t.created_at DESC
            """
            cursor.execute(query, (user_id,))
            tasks = cursor.fetchall()
            
            for task in tasks:
                if task.get('created_at'):
                    task['created_at'] = task['created_at'].isoformat()
                if task.get('updated_at'):
                    task['updated_at'] = task['updated_at'].isoformat()
                if task.get('completed_at'):
                    task['completed_at'] = task['completed_at'].isoformat()
            
            return tasks
        finally:
            cursor.close()
            conn.close()        