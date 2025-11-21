from models import User, Task
from services.whatsapp_service import WhatsAppService
from services.image_service import ImageService
import requests
import tempfile
import os

class TaskService:
    def __init__(self, db):
        self.user_model = User(db)
        self.task_model = Task(db)
        self.whatsapp_service = WhatsAppService()
        self.image_service = ImageService()

    def handle_message(self, phone_number, message, media_url=None):
        # Clean phone number (remove 'whatsapp:' prefix if present)
        clean_phone = phone_number.replace('whatsapp:', '')
        
        user = self.user_model.find_by_phone(clean_phone)
        
        if not user:
            self.whatsapp_service.send_message(
                clean_phone,
                "Sorry, you are not registered in our system. Please contact your administrator."
            )
            return

        message = message.strip().lower()

        if message in ['hi', 'hello', 'hii', 'hey']:
            self.handle_greeting(user, clean_phone)
        elif message in ['tasks', 'my tasks', 'task']:
            self.handle_list_tasks(user, clean_phone)
        elif message.startswith('status '):
            self.handle_update_status(user, clean_phone, message)
        elif media_url:
            self.handle_image_upload(user, clean_phone, media_url)
        else:
            self.handle_help(user, clean_phone)

    def handle_greeting(self, user, phone_number):
        welcome_message = (
            f"Welcome back {user['name']}! 👋\n\n"
            "I'm your team management assistant. Here's what you can do:\n\n"
            "📋 *Tasks* - View all your assigned tasks\n"
            "🔄 *Status* - Update task status (pending/in-progress/completed)\n"
            "📷 *Send Image* - Attach photo to completed task\n\n"
            "Type *tasks* to see your current assignments or type *help* for more options."
        )
        self.whatsapp_service.send_message(phone_number, welcome_message)

    def handle_list_tasks(self, user, phone_number):
        tasks = self.task_model.get_tasks_by_user(user['_id'])
        formatted_tasks = self.whatsapp_service.format_task_list(tasks)
        self.whatsapp_service.send_message(phone_number, formatted_tasks)

    def handle_update_status(self, user, phone_number, message):
        parts = message.split()
        if len(parts) < 3:
            self.whatsapp_service.send_message(
                phone_number,
                "Invalid format. Please use: *status [task-number] [status]*\n\n"
                "Example: *status 1 completed*\n"
                "Available status: pending, in-progress, completed"
            )
            return

        try:
            task_index = int(parts[1]) - 1
            new_status = parts[2].lower()
        except (ValueError, IndexError):
            self.whatsapp_service.send_message(
                phone_number,
                "Invalid format. Please use: *status [task-number] [status]*"
            )
            return

        if new_status not in ['pending', 'in-progress', 'completed']:
            self.whatsapp_service.send_message(
                phone_number,
                "Invalid status. Use: pending, in-progress, or completed"
            )
            return

        tasks = self.task_model.get_tasks_by_user(user['_id'])
        
        if task_index < 0 or task_index >= len(tasks):
            self.whatsapp_service.send_message(
                phone_number,
                "Invalid task number. Use *tasks* to see your task list."
            )
            return

        task = tasks[task_index]
        success = self.task_model.update_task_status(str(task['_id']), new_status, str(user['_id']))

        if success:
            if new_status == 'completed':
                response_message = (
                    f"✅ Task \"{task['title']}\" marked as completed!\n\n"
                    "Please send a photo of the completed work to attach to this task."
                )
            else:
                response_message = f"📝 Status updated for \"{task['title']}\" to: {new_status}"
        else:
            response_message = "Error updating task status. Please try again."

        self.whatsapp_service.send_message(phone_number, response_message)

    def handle_image_upload(self, user, phone_number, media_url):
        """Handle image upload from WhatsApp with Twilio authentication"""
        try:
            print(f"🖼️ Processing image upload from {phone_number}")
            print(f"📎 Media URL: {media_url}")
            
            # Get the most recently completed task without an image
            task = self.task_model.get_recent_completed_task(user['_id'])
            
            if not task:
                self.whatsapp_service.send_message(
                    phone_number,
                    "❌ No recently completed task found.\n\n"
                    "Please:\n"
                    "1. First mark a task as completed using: *status [number] completed*\n"  
                    "2. Then send the image immediately after"
                )
                return

            print(f"📋 Found task to attach image: {task['title']}")

            # Download the image from Twilio
            image_path = self.image_service.download_twilio_media(
                media_url, 
                str(task['_id']), 
                str(user['_id'])
            )

            if not image_path:
                self.whatsapp_service.send_message(
                    phone_number,
                    "❌ Failed to download image from WhatsApp. Please try again."
                )
                return

            # Try to upload to Cloudinary if configured
            cloudinary_url = self.image_service.upload_to_cloudinary(
                image_path, 
                str(task['_id']), 
                str(user['_id'])
            )

            # Store either Cloudinary URL or local path
            image_url_to_store = cloudinary_url or f"local:{image_path}"
            
            # Update task with image reference
            success = self.task_model.add_completion_image(
                str(task['_id']), 
                image_url_to_store, 
                str(user['_id'])
            )
            
            if success:
                if cloudinary_url:
                    response_message = (
                        f"✅ Image successfully uploaded!\n\n"
                        f"📋 Task: {task['title']}\n"
                        f"🏠 Property: {task.get('property_name', 'N/A')}\n\n"
                        f"📸 View image: {cloudinary_url}\n\n"
                        "Thank you for documenting your work! 🎉"
                    )
                else:
                    response_message = (
                        f"✅ Image received and saved!\n\n"
                        f"📋 Task: {task['title']}\n"  
                        f"🏠 Property: {task.get('property_name', 'N/A')}\n\n"
                        "The image has been stored with your task completion. 📸"
                    )
            else:
                response_message = "❌ Error saving image to task. Please try again."

            self.whatsapp_service.send_message(phone_number, response_message)

        except Exception as e:
            print(f"❌ Error in image upload: {e}")
            self.whatsapp_service.send_message(
                phone_number,
                f"❌ Error processing image: {str(e)}\n\nPlease try again or contact support."
            )

    def handle_help(self, user, phone_number):
        help_message = (
            f"Hello {user['name']}! I'm your team management assistant.\n\n"
            "Available commands:\n"
            "• *tasks* - List your assigned tasks\n"
            "• *status [task-number] [status]* - Update task status\n"
            "• Send image to attach to completed task\n\n"
            "Examples:\n"
            "*status 1 completed* - Mark task 1 as completed\n"
            "*tasks* - View all your tasks"
        )
        self.whatsapp_service.send_message(phone_number, help_message)