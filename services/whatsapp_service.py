from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

class WhatsAppService:
    def __init__(self):
        self.client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        self.whatsapp_number = os.getenv('TWILIO_WHATSAPP_NUMBER')

    def send_message(self, to, message):
        try:
            message = self.client.messages.create(
                body=message,
                from_=f"whatsapp:{self.whatsapp_number}",
                to=f"whatsapp:{to}"
            )
            print(f"Message sent to {to}: {message.sid}")
            return True
        except Exception as e:
            print(f"Error sending message: {e}")
            return False

    def format_task_list(self, tasks):
        if not tasks:
            return "You don't have any tasks assigned at the moment. 🎉"

        task_list = f"📋 *Your Tasks ({len(tasks)})*\n\n"
        
        for i, task in enumerate(tasks):
            task_list += f"*{i + 1}. {task['title']}*\n"
            
            # Add property name if available
            if task.get('property_name'):
                task_list += f"   🏠 Property: {task['property_name']}\n"
            
            task_list += f"   📝 {task.get('description', 'No description')}\n"
            task_list += f"   Status: {self.get_status_emoji(task['status'])} {task['status']}\n"
            
            if task.get('due_date'):
                task_list += f"   Due: {task['due_date'].strftime('%Y-%m-%d')}\n"
            
            task_list += "\n"

        task_list += "To update status, reply:\n*status [number] [status]*\nExample: *status 1 completed*"
        return task_list

    @staticmethod
    def get_status_emoji(status):
        emojis = {
            'pending': '⏳',
            'in-progress': '🔄',
            'completed': '✅',
            'cancelled': '❌'
        }
        return emojis.get(status, '📝')