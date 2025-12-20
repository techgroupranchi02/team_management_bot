from models.team_member import TeamMember
from models.task import Task
from services.whatsapp_service import WhatsAppService
from services.image_service import ImageService
from services.language_service import LanguageService

class TaskService:
    def __init__(self, db_config):
        self.db_config = db_config
        self.team_member_model = TeamMember(db_config)
        self.task_model = Task(db_config)
        self.whatsapp_service = WhatsAppService()
        self.image_service = ImageService()
        self.language_service = LanguageService()
        self.user_languages = {}  # Store user language preferences

    def handle_message(self, phone_number, message, media_url=None):
        # Clean phone number (remove 'whatsapp:' prefix if present)
        clean_phone = phone_number.replace('whatsapp:', '')
        
        print(f"🔍 Looking up team member with phone: {clean_phone}")
        member = self.team_member_model.find_by_phone(clean_phone)
        
        if not member:
            # Detect language for unknown user
            if message:
                detected_lang = self.language_service.detect_language(message)
            else:
                detected_lang = 'en'
                
            no_access_msg = self.whatsapp_service._get_translated_message(
                'no_access', detected_lang
            ) or "❌ Sorry, you are not registered in our system as an active team member.\n\nPlease contact your administrator to get added to the team."
            
            self.whatsapp_service.send_message(clean_phone, no_access_msg, detected_lang)
            return

        print(f"✅ Found team member: {member['name']} (ID: {member['id']})")
        
        # Detect or get user's language preference
        user_language = self._get_user_language(clean_phone, message)
        message = message.strip().lower()

        if message in ['hi', 'hello', 'hii', 'hey', 'नमस्ते', 'hola', 'bonjour']:
            self.handle_greeting(member, clean_phone, user_language)
        elif message in ['tasks', 'my tasks', 'task', 'कार्य', 'tareas', 'tâches']:
            self.handle_list_tasks(member, clean_phone, user_language)
        elif message.startswith('status ') or any(message.startswith(prefix) for prefix in ['स्थिति', 'estado', 'statut']):
            self.handle_update_status(member, clean_phone, message, user_language)
        elif message in ['pending photos', 'लंबित फोटो', 'fotos pendientes', 'photos en attente']:
            self.handle_pending_photos(member, clean_phone, user_language)
        elif message in ['help', 'सहायता', 'ayuda', 'aide']:
            self.handle_help(member, clean_phone, user_language)
        elif message in ['recurring', 'recurring tasks', 'आवर्ती', 'recurrente']:
            self.handle_recurring_tasks(member, clean_phone, user_language)
        elif media_url:
            self.handle_image_upload(member, clean_phone, media_url, user_language)
        else:
            self.handle_unknown_command(member, clean_phone, user_language)

    def _get_user_language(self, phone_number, message):
        """Get user's language preference, detect from message if not set"""
        if phone_number in self.user_languages:
            return self.user_languages[phone_number]
        
        # Detect language from message
        detected_lang = self.language_service.detect_language(message)
        self.user_languages[phone_number] = detected_lang
        return detected_lang

    def handle_greeting(self, member, phone_number, language):
        welcome_msg = self.whatsapp_service._get_translated_message('welcome', language)
        help_msg = self.whatsapp_service._get_translated_message('help', language)
        
        welcome_message = (
            f"{welcome_msg.format(member['name'])}\n\n"
            "I'm your team management assistant. Here's what you can do:\n\n"
            "📋 *Tasks* - View all your assigned tasks\n"
            "🔄 *Status* - Update task status (pending/in_progress/completed)\n"
            "📷 *Send Image* - Attach photo to completed task\n"
            "🖼️ *Pending Photos* - View tasks waiting for photos\n"
            "🔄 *Recurring* - View your recurring tasks\n\n"
            f"{help_msg}"
        )
        self.whatsapp_service.send_message(phone_number, welcome_message, language)

    def handle_list_tasks(self, member, phone_number, language):
        tasks = self.task_model.get_tasks_by_user(member['id'])
        formatted_tasks = self.whatsapp_service.format_task_list(tasks, language)
        self.whatsapp_service.send_message(phone_number, formatted_tasks, language)

    def handle_update_status(self, member, phone_number, message, language):
        # Extract task number and status regardless of language
        parts = message.split()
        if len(parts) < 3:
            invalid_format_msg = self.whatsapp_service._get_translated_message('invalid_format', language)
            self.whatsapp_service.send_message(phone_number, invalid_format_msg, language)
            return

        try:
            task_index = int(parts[1]) - 1
            new_status = parts[2].lower()
        except (ValueError, IndexError):
            invalid_format_msg = self.whatsapp_service._get_translated_message('invalid_format', language)
            self.whatsapp_service.send_message(phone_number, invalid_format_msg, language)
            return

        if new_status not in ['pending', 'in_progress', 'completed']:
            status_error_msg = self.whatsapp_service._get_translated_message('invalid_status', language) or "❌ Invalid status. Use: pending, in_progress, or completed"
            self.whatsapp_service.send_message(phone_number, status_error_msg, language)
            return

        tasks = self.task_model.get_tasks_by_user(member['id'])
        
        if task_index < 0 or task_index >= len(tasks):
            task_error_msg = self.whatsapp_service._get_translated_message('invalid_task', language) or "❌ Invalid task number. Use *tasks* to see your task list."
            self.whatsapp_service.send_message(phone_number, task_error_msg, language)
            return

        task = tasks[task_index]
        
        # Check if task requires photo when trying to complete
        if new_status == 'completed':
            can_complete, reason = self.task_model.can_complete_task(task['id'], member['id'])
            
            if not can_complete:
                if reason == "photo_required":
                    photo_required_msg = self.whatsapp_service._get_translated_message('photo_required', language)
                    response_message = (
                        f"{photo_required_msg}\n\n"
                        f"Task \"{task['title']}\" requires a completion photo.\n\n"
                        f"Please send a photo of the completed work first, then I'll automatically mark it as completed.\n\n"
                        f"Just take a photo and send it now! 📷"
                    )
                    self.whatsapp_service.send_message(phone_number, response_message, language)
                    return
                else:
                    response_message = f"❌ Cannot complete task: {reason}"
                    self.whatsapp_service.send_message(phone_number, response_message, language)
                    return

        # Update status for non-completed or tasks that don't require photos
        success = self.task_model.update_task_status(task['id'], new_status, member['id'])

        if success:
            if new_status == 'completed':
                task_completed_msg = self.whatsapp_service._get_translated_message('task_completed', language)
                response_message = (
                    f"{task_completed_msg}\n\n"
                    f"Task: \"{task['title']}\"\n"
                )
                # Only ask for photo if it's required but not provided yet
                if task.get('is_photo_required') == 1 and not task.get('completion_image'):
                    photo_required_msg = self.whatsapp_service._get_translated_message('photo_required', language)
                    response_message += f"\n{photo_required_msg}"
            else:
                status_updated_msg = self.whatsapp_service._get_translated_message('status_updated', language) or "📝 Status updated for"
                response_message = f"{status_updated_msg} \"{task['title']}\" to: {new_status}"
        else:
            response_message = "❌ Error updating task status. Please try again."

        self.whatsapp_service.send_message(phone_number, response_message, language)

    def handle_image_upload(self, member, phone_number, media_url, language):
        """Handle image upload from WhatsApp with language support"""
        try:
            print(f"🖼️ Processing image upload from {phone_number}")
            print(f"📎 Media URL: {media_url}")
            
            # Get tasks that need photos
            pending_photo_tasks = self.task_model.get_pending_photo_tasks(member['id'])
            
            if not pending_photo_tasks:
                no_tasks_msg = self.whatsapp_service._get_translated_message('no_tasks_photos', language) or "❌ No tasks found that require photos."
                self.whatsapp_service.send_message(phone_number, no_tasks_msg, language)
                return

            # Use the most recent task that needs a photo
            task = pending_photo_tasks[0]
            
            print(f"📋 Found task to attach image: {task['title']}")

            # Download the image from Twilio
            image_path = self.image_service.download_twilio_media(
                media_url, 
                task['id'], 
                member['id']
            )

            if not image_path:
                download_error_msg = self.whatsapp_service._get_translated_message('download_error', language) or "❌ Failed to download image from WhatsApp. Please try again."
                self.whatsapp_service.send_message(phone_number, download_error_msg, language)
                return

            # Try to upload to Cloudinary if configured
            cloudinary_url = self.image_service.upload_to_cloudinary(
                image_path, 
                task['id'], 
                member['id']
            )

            # Store either Cloudinary URL or local path
            image_url_to_store = cloudinary_url or f"local:{image_path}"
            
            # Update task with image reference and auto-complete if needed
            success, result_type = self.task_model.add_completion_image(
                task['id'], 
                image_url_to_store, 
                member['id']
            )
            
            if success:
                image_uploaded_msg = self.whatsapp_service._get_translated_message('image_uploaded', language)
                
                if result_type == "completed":
                    task_completed_msg = self.whatsapp_service._get_translated_message('task_completed', language)
                    response_message = (
                        f"{task_completed_msg} 🎉\n\n"
                        f"📋 Task: {task['title']}\n"
                        f"🏠 Property: {task.get('property_name', 'N/A')}\n\n"
                        f"{image_uploaded_msg}\n"
                    )
                else:
                    response_message = (
                        f"{image_uploaded_msg}\n\n"
                        f"📋 Task: {task['title']}\n"  
                        f"🏠 Property: {task.get('property_name', 'N/A')}\n\n"
                        f"Status: {task.get('status', 'N/A')}\n"
                    )
                
                if cloudinary_url:
                    response_message += f"\n📸 View image: {cloudinary_url}"
                
                response_message += f"\n\n{self.whatsapp_service._get_translated_message('thank_you', language) or 'Thank you for documenting your work!'} 📸"
                
            else:
                response_message = "❌ Error saving image to task. Please try again."

            self.whatsapp_service.send_message(phone_number, response_message, language)

        except Exception as e:
            print(f"❌ Error in image upload: {e}")
            error_msg = self.whatsapp_service._get_translated_message('upload_error', language) or f"❌ Error processing image: {str(e)}\n\nPlease try again or contact support."
            self.whatsapp_service.send_message(phone_number, error_msg, language)

    def handle_pending_photos(self, member, phone_number, language):
        """Show tasks that are waiting for photos"""
        tasks = self.task_model.get_pending_photo_tasks(member['id'])
        
        if not tasks:
            no_pending_msg = self.whatsapp_service._get_translated_message('no_pending_photos', language) or "✅ No tasks waiting for photos!\n\nAll your completed tasks have their required photos."
            self.whatsapp_service.send_message(phone_number, no_pending_msg, language)
            return
        
        pending_header = self.whatsapp_service._get_translated_message('pending_photos_header', language) or "📸 *Tasks Waiting for Photos:*\n\n"
        message = pending_header
        
        for i, task in enumerate(tasks, 1):
            message += f"{i}. {task['title']}\n"
            message += f"   🏠 {task.get('property_name', 'N/A')}\n"
            message += f"   📅 Completed: {task.get('completed_at', 'N/A')}\n\n"
        
        send_photo_msg = self.whatsapp_service._get_translated_message('send_photo_instruction', language) or "Simply send a photo now to attach it to the most recent task!"
        message += send_photo_msg
        
        self.whatsapp_service.send_message(phone_number, message, language)

    def handle_help(self, member, phone_number, language):
        help_message = self.whatsapp_service._get_translated_message('help_full', language) or (
            f"Hello {member['name']}! I'm your team management assistant.\n\n"
            "Available commands:\n"
            "• *tasks* - List your assigned tasks\n"
            "• *status [task-number] [status]* - Update task status\n"
            "• *pending photos* - View tasks waiting for photos\n"
            "• *recurring* - View your recurring tasks\n"
            "• Send image to attach to completed task\n\n"
            "Examples:\n"
            "*status 1 completed* - Mark task 1 as completed\n"
            "*tasks* - View all your tasks\n"
            "*pending photos* - See tasks needing photos\n"
            "*recurring* - View recurring tasks\n\n"
            "📸 *Note:* Some tasks require photos before completion. "
            "Just send the photo and I'll handle the rest!"
        )
        self.whatsapp_service.send_message(phone_number, help_message, language)

    def handle_unknown_command(self, member, phone_number, language):
        unknown_msg = self.whatsapp_service._get_translated_message('unknown_command', language) or "I didn't understand that command. Type *help* to see available options."
        self.whatsapp_service.send_message(phone_number, unknown_msg, language)

    def handle_recurring_tasks(self, member, phone_number, language):
        """Show recurring tasks assigned to the user"""
        tasks = self.task_model.get_recurring_tasks_by_user(member['id'])
        
        if not tasks:
            no_recurring_msg = self._get_recurring_translated_message('no_recurring_tasks', language)
            self.whatsapp_service.send_message(phone_number, no_recurring_msg, language)
            return
        
        message = self._get_recurring_translated_message('recurring_tasks_header', language) + "\n\n"
        
        for i, task in enumerate(tasks, 1):
            message += f"*{i}. {task['title']}*\n"
            message += f"   🔄 {task['recurrence'].title()}\n"
            
            if task.get('property_name'):
                property_text = self.whatsapp_service._get_translated_message('property', language)
                message += f"   🏠 {property_text}: {task['property_name']}\n"
            
            if task.get('description'):
                message += f"   📝 {task['description']}\n"
            
            status_text = self.whatsapp_service._get_translated_message('status', language)
            status_emoji = self.whatsapp_service.get_status_emoji(task['status'])
            message += f"   {status_text}: {status_emoji} {task['status']}\n\n"
        
        self.whatsapp_service.send_message(phone_number, message, language)

    def _get_recurring_translated_message(self, message_key, language='en'):
        """Get translated messages for recurring tasks"""
        messages = {
            'en': {
                'no_recurring_tasks': "You don't have any recurring tasks assigned. 🔄",
                'recurring_tasks_header': "🔄 *Your Recurring Tasks*",
                'recurring_reminder': "🔔 Recurring task reminder"
            },
            'hi': {
                'no_recurring_tasks': "आपके पास कोई आवर्ती कार्य नहीं हैं। 🔄",
                'recurring_tasks_header': "🔄 *आपके आवर्ती कार्य*",
                'recurring_reminder': "🔔 आवर्ती कार्य अनुस्मारक"
            },
            'es': {
                'no_recurring_tasks': "No tienes tareas recurrentes asignadas. 🔄",
                'recurring_tasks_header': "🔄 *Tus Tareas Recurrentes*",
                'recurring_reminder': "🔔 Recordatorio de tarea recurrente"
            }
        }
        
        if language not in messages:
            language = 'en'
            
        return messages[language].get(message_key, messages['en'].get(message_key, ""))