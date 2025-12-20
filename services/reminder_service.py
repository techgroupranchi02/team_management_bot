import schedule
import time
import threading
from datetime import datetime
from models.task import Task
from services.whatsapp_service import WhatsAppService
from services.language_service import LanguageService
import logging

class ReminderService:
    def __init__(self, db_config):
        self.db_config = db_config
        self.task_model = Task(db_config)
        self.whatsapp_service = WhatsAppService()
        self.language_service = LanguageService()
        self.logger = logging.getLogger(__name__)
        self.is_running = False
        self.reminder_thread = None

    def _send_individual_reminder(self, task):
        """Send reminder for an individual recurring task"""
        try:
            phone_number = task['phone']
            if not phone_number:
                self.logger.warning(f"No phone number found for team member {task['team_member_name']}")
                return False

            self.logger.info(f"Attempting to send reminder to {task['team_member_name']} at {phone_number}")

            # Detect language preference (default to English)
            language = 'en'
            
            # Format reminder message
            reminder_message = self._format_reminder_message(task, language)
            
            self.logger.info(f"Formatted reminder message: {reminder_message[:100]}...")
            
            # Send WhatsApp message
            success = self.whatsapp_service.send_message(phone_number, reminder_message, language)
            
            if success:
                self.logger.info(f"✅ Reminder sent to {task['team_member_name']} for task: {task['title']}")
                # Update reminder tracking
                self.task_model.update_task_reminder(task['id'], task['assigned_to'])
                return True
            else:
                self.logger.error(f"❌ Failed to send reminder to {task['team_member_name']}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error sending individual reminder to {task.get('team_member_name', 'unknown')}: {e}")
            return False

    def start_reminder_scheduler(self):
        """Start the reminder scheduler in a separate thread"""
        if self.is_running:
            self.logger.info("Reminder scheduler is already running")
            return

        self.is_running = True
        self.reminder_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.reminder_thread.start()
        self.logger.info("✅ Reminder scheduler started")

    def stop_reminder_scheduler(self):
        """Stop the reminder scheduler"""
        self.is_running = False
        if self.reminder_thread:
            self.reminder_thread.join(timeout=5)
        self.logger.info("❌ Reminder scheduler stopped")

    def _run_scheduler(self):
        """Run the scheduler loop"""
        # Schedule reminders to run every day at 9:00 AM
        schedule.every().day.at("09:00").do(self.send_daily_reminders)
        
        # Also run immediately on startup
        self.send_daily_reminders()
        
        while self.is_running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    def send_daily_reminders(self):
        """Send reminders for recurring tasks due today"""
        try:
            self.logger.info("🔔 Checking for recurring task reminders...")
            
            recurring_tasks = self.task_model.get_recurring_tasks_due_for_reminder()
            
            if not recurring_tasks:
                self.logger.info("No recurring tasks due for reminders today")
                return

            self.logger.info(f"Found {len(recurring_tasks)} recurring tasks due for reminders")
            
            for task in recurring_tasks:
                self._send_individual_reminder(task)
                
        except Exception as e:
            self.logger.error(f"Error sending daily reminders: {e}")

    def _send_individual_reminder(self, task):
        """Send reminder for an individual recurring task"""
        try:
            phone_number = task['phone']
            if not phone_number:
                self.logger.warning(f"No phone number found for team member {task['team_member_name']}")
                return

            # Detect language preference (default to English)
            language = 'en'  # You can enhance this by storing user language preferences
            
            # Format reminder message
            reminder_message = self._format_reminder_message(task, language)
            
            # Send WhatsApp message
            success = self.whatsapp_service.send_message(phone_number, reminder_message, language)
            
            if success:
                self.logger.info(f"✅ Reminder sent to {task['team_member_name']} for task: {task['title']}")
                # Update reminder tracking
                self.task_model.update_task_reminder(task['id'], task['assigned_to'])
            else:
                self.logger.error(f"❌ Failed to send reminder to {task['team_member_name']}")
                
        except Exception as e:
            self.logger.error(f"Error sending individual reminder: {e}")

    def _format_reminder_message(self, task, language='en'):
        """Format the reminder message based on language"""
        messages = {
            'en': {
                'reminder_header': "🔔 *Recurring Task Reminder*\n\n",
                'task_title': "Task: *{}*",
                'recurrence': "Frequency: {}",
                'property': "Property: {}",
                'description': "Description: {}",
                'action_required': "\n\nThis is a {} task. Please complete it and update the status.",
                'update_instruction': "\n\nTo update status, reply: *status [task-number] [status]*",
                'recurrence_daily': "Daily",
                'recurrence_weekly': "Weekly", 
                'recurrence_monthly': "Monthly",
                'recurrence_quarterly': "Quarterly",
                'recurrence_yearly': "Yearly"
            },
            'hi': {
                'reminder_header': "🔔 *आवर्ती कार्य अनुस्मारक*\n\n",
                'task_title': "कार्य: *{}*",
                'recurrence': "आवृत्ति: {}",
                'property': "संपत्ति: {}",
                'description': "विवरण: {}",
                'action_required': "\n\nयह एक {} कार्य है। कृपया इसे पूरा करें और स्थिति अपडेट करें।",
                'update_instruction': "\n\nस्थिति अपडेट करने के लिए, जवाब दें: *status [संख्या] [स्थिति]*",
                'recurrence_daily': "दैनिक",
                'recurrence_weekly': "साप्ताहिक",
                'recurrence_monthly': "मासिक", 
                'recurrence_quarterly': "त्रैमासिक",
                'recurrence_yearly': "वार्षिक"
            },
            'es': {
                'reminder_header': "🔔 *Recordatorio de Tarea Recurrente*\n\n",
                'task_title': "Tarea: *{}*",
                'recurrence': "Frecuencia: {}",
                'property': "Propiedad: {}",
                'description': "Descripción: {}",
                'action_required': "\n\nEsta es una tarea {}. Por favor complétala y actualiza el estado.",
                'update_instruction': "\n\nPara actualizar el estado, responde: *status [número] [estado]*",
                'recurrence_daily': "Diaria",
                'recurrence_weekly': "Semanal",
                'recurrence_monthly': "Mensual",
                'recurrence_quarterly': "Trimestral", 
                'recurrence_yearly': "Anual"
            }
        }
        
        # Get messages for the specified language, default to English
        lang_messages = messages.get(language, messages['en'])
        
        # Get recurrence text
        recurrence_key = f"recurrence_{task['recurrence']}"
        recurrence_text = lang_messages.get(recurrence_key, task['recurrence'])
        
        # Build message
        message = lang_messages['reminder_header']
        message += lang_messages['task_title'].format(task['title']) + "\n"
        message += lang_messages['recurrence'].format(recurrence_text) + "\n"
        
        if task.get('property_name'):
            message += lang_messages['property'].format(task['property_name']) + "\n"
        
        if task.get('description'):
            message += lang_messages['description'].format(task['description']) + "\n"
        
        message += lang_messages['action_required'].format(recurrence_text.lower())
        message += lang_messages['update_instruction']
        
        return message

    def send_immediate_reminder(self, task_id):
        """Send an immediate reminder for a specific task (for testing)"""
        try:
            task = self.task_model.get_task_by_id(task_id)
            if not task:
                self.logger.error(f"Task {task_id} not found")
                return False
                
            if task['schedule_type'] != 'recurring':
                self.logger.error(f"Task {task_id} is not a recurring task")
                return False
                
            self._send_individual_reminder(task)
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending immediate reminder: {e}")
            return False