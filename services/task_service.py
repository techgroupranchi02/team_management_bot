from email.mime import message
from models.team_member import TeamMember
from models.task import Task
from services.whatsapp_service import WhatsAppService
from services.image_service import ImageService
from services.language_service import LanguageService
import os
import json


class TaskService:
    def __init__(self, db_config):
        self.db_config = db_config
        self.team_member_model = TeamMember(db_config)
        self.task_model = Task(db_config)
        self.whatsapp_service = WhatsAppService()
        self.image_service = ImageService()
        self.language_service = LanguageService()
        self.user_languages = {}  # Store user language preferences
        self.user_property_selections = {}  # Store user property selections
        self.user_active_client = {}  # Store active client_id per phone (for client switching)


        # Check database structure on initialization
        print("🔍 Checking database structure...")
        self.check_database_structure()
        self.task_model.ensure_search_history_table()

    def get_connection(self):
        """Get database connection"""
        return self.task_model.get_connection()    

    def handle_message(self, phone_number, message, media_url=None, button_id=None):
        # Clean phone number (remove 'whatsapp:' prefix if present)
        clean_phone = phone_number.replace('whatsapp:', '')
        
        print(f"🔍 Looking up team member with phone: {clean_phone}")
        print(f"🔍 Received message: '{message}'")
        
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

        # Check if user has an active client preference (from client switching)
        active_client_id = self.user_active_client.get(clean_phone)
        if active_client_id and member.get('client_id') != active_client_id:
            # Re-find the member record for the preferred client
            switched_member = self.team_member_model.find_by_phone_and_client(clean_phone, active_client_id)
            if switched_member:
                member = switched_member
                print(f"🔄 Using switched client context: client_id={active_client_id}")

        print(f"✅ Found team member: {member['name']} (ID: {member['id']}, client_id: {member.get('client_id')})")
        
        # Get user language
        user_language = self._get_user_language(clean_phone, message)

        # FIRST: Check if this is an inventory update text message
        if message and not media_url:
            if self.handle_text_message(member, clean_phone, message, user_language):
                return  # Handled as inventory update
        
        # Handle inventory button clicks early (before task selection check)
        # These use button_id, not message title
        if button_id:
            if button_id.startswith('inv_item_'):
                item_id = button_id.replace('inv_item_', '')
                print(f"📦 Inventory item selected via button: ID={item_id}")
                self.handle_inventory_item_selected(member, clean_phone, item_id, user_language)
                return
            if button_id.startswith('inv_search_next_'):
                offset_str = button_id.replace('inv_search_next_', '')
                inv_ctx = self._get_user_context(clean_phone)
                if inv_ctx and inv_ctx.get('inventory_search_results'):
                    try:
                        offset = int(offset_str)
                        results = inv_ctx.get('search_results', [])
                        search_term = inv_ctx.get('search_term', '')
                        self._show_inventory_search_results(clean_phone, results, user_language, offset=offset, search_term=search_term)
                    except ValueError:
                        self.handle_property_inventory_menu(member, clean_phone, user_language)
                else:
                    self.handle_property_inventory_menu(member, clean_phone, user_language)
                return

        # ─── Direct Search & Slash Command Router ───
        # Intercept # and / prefixed messages BEFORE button/command matching.
        # Exclude '#N: ...' style button clicks (e.g., '#1: Clean Room') which have '#' + digit + ':'
        raw_msg = message.strip() if message else ''
        if raw_msg.startswith('#') and not (len(raw_msg) > 1 and raw_msg[1:].lstrip('0123456789').startswith(':')):
            self._handle_search_command(member, clean_phone, raw_msg, user_language)
            return
        if raw_msg.startswith('/'):
            self._handle_slash_command(member, clean_phone, raw_msg, user_language)
            return
        # ─── End: Direct Search & Slash Commands ───

        # Handle button clicks by exact title match FIRST
        print(f"🔘 Processing button click: '{message}'")
        
        # Check for task selection buttons like "#1: Clean Room 101"
        if message.startswith('#') and ':' in message:
            tasks = self.task_model.get_tasks_by_user(member['id'])
            self.handle_task_selection_button(member, clean_phone, message, tasks, user_language)
            return
        
        # Check for special commands
        if message == "⚙️ Settings":
            self.show_settings_menu(member, clean_phone, user_language)
            return
        elif message == "⬅️ Back to Main Menu":
            self.show_main_menu(member, clean_phone, user_language)
            return
        
        # Check for common action buttons (BY TITLE)
        button_mappings = {
            # Welcome buttons
            '📋 Tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            '📦 Inventory': lambda: self.handle_property_inventory_menu(member, clean_phone, user_language),
            '⚙️ Settings': lambda: self.show_settings_menu(member, clean_phone, user_language),
            '❓ Help': lambda: self.handle_help(member, clean_phone, user_language),
            
            # Task list buttons
            'Main Menu': lambda: self.show_main_menu(member, clean_phone, user_language),
            '🏠 Main Menu': lambda: self.show_main_menu(member, clean_phone, user_language),
            
            # Property buttons (ADD THESE)
            'Select Property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            '🏠 Select Property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            '🔄 Change Property': lambda: self.handle_property_inventory_menu(member, clean_phone, user_language, force_selection=True),
            '⬅️ Back': lambda: self.show_settings_menu(member, clean_phone, user_language),
            '📋 View Tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            
            # Task action buttons
            '✅ Mark Complete': lambda: self.handle_mark_complete_button(member, clean_phone, user_language),
            '📝 Update Status': lambda: self.handle_update_status_button(member, clean_phone, user_language),
            '📋 Back to Tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            '⬅️ Back to Task': lambda: self.handle_back_to_task_button(member, clean_phone, user_language),
            '📋 View All': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            
            # Status selection buttons
            '⏳ Pending': lambda: self.handle_status_selection(member, clean_phone, 'pending', user_language),
            '🔄 In Progress': lambda: self.handle_status_selection(member, clean_phone, 'in_progress', user_language),
            '✅ Complete': lambda: self.handle_status_selection(member, clean_phone, 'completed', user_language),
            '⏭️ Skipped': lambda: self.handle_status_selection(member, clean_phone, 'skipped', user_language), 
        }
        

        
        # Check for button IDs (from interactive buttons)
        button_id_mappings = {
            # Main menu button IDs
            'btn_tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            'btn_inventory': lambda: self.handle_property_inventory_menu(member, clean_phone, user_language),
            'btn_inv_change_prop': lambda: self.handle_property_inventory_menu(member, clean_phone, user_language, force_selection=True),
            'btn_settings': lambda: self.show_settings_menu(member, clean_phone, user_language),
            'main_menu': lambda: self.show_main_menu(member, clean_phone, user_language),
            
            # Settings button IDs
            'back_main': lambda: self.show_main_menu(member, clean_phone, user_language),
            'back_settings': lambda: self.show_settings_menu(member, clean_phone, user_language),
            'settings_back': lambda: self.show_settings_menu(member, clean_phone, user_language),
            
            # Task button IDs
            'help_main_menu': lambda: self.show_main_menu(member, clean_phone, user_language),

            # Task action button IDs
            'back_to_tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            
            # Property button IDs
            'property_continue': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            'property_change': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            'view_tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            'change_property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            'select_property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            
            # Language button IDs
            'continue_settings': lambda: self.show_settings_menu(member, clean_phone, user_language),
        }
        
        target_id = button_id if button_id else message
        
        # Check if message is a button ID
        if target_id in button_id_mappings:
            print(f"✅ Button matched by ID: {target_id}")
            button_id_mappings[target_id]()
            return
        
        # Check for task button IDs (like "task_123")
        if target_id.startswith('task_'):
            task_id = target_id.replace('task_', '')
            self.show_task_options(member, clean_phone, task_id, user_language)
            return
        
        # Check for status button IDs (like "status_pending_123")
        if target_id.startswith('status_'):
            parts = target_id.split('_')
            if len(parts) >= 3:
                status_type = parts[1]  # pending, inprogress, complete, skipped
                task_id = parts[2]
                
                status_map = {
                    'pending': 'pending',
                    'inprogress': 'in_progress',
                    'complete': 'completed',
                    'skipped': 'skipped'
                }
                
                status = status_map.get(status_type, status_type)
                self.update_task_from_button(member, clean_phone, task_id, status, user_language)
                return
        
        # Check for back to task button IDs (like "back_task_123")
        if target_id.startswith('back_task_'):
            task_id = target_id.replace('back_task_', '')
            self.show_task_options(member, clean_phone, task_id, user_language)
            return
        
        # Check for mark_complete button IDs (like "mark_complete_123")
        if target_id.startswith('mark_complete_'):
            print(f"🔍 DEBUG: Received mark_complete button ID: {target_id}")
            self.handle_mark_complete_from_button_id(member, clean_phone, target_id, user_language)
            return

        # Check for update_status button IDs (like "update_status_123") 
        if target_id.startswith('update_status_'):
            task_id = target_id.replace('update_status_', '')
            print(f"🔍 DEBUG: Received update_status button ID for task: {task_id}")
            # Store the task_id in user context
            self._store_user_context(clean_phone, {'current_task_id': task_id})
            self.show_status_options(member, clean_phone, task_id, user_language)
            return
        
        # Check for inv_prop_ button IDs (inventory property selection)
        if target_id.startswith('inv_prop_'):
            property_id = target_id.replace('inv_prop_', '')
            print(f"📦 Inventory property selected via button: ID={property_id}")
            self.handle_property_inventory_selection(member, clean_phone, property_id, user_language)
            return

        # Check for inv_item_ button IDs (inventory item selection from search)
        if target_id.startswith('inv_item_'):
            item_id = target_id.replace('inv_item_', '')
            print(f"📦 Inventory item selected via button: ID={item_id}")
            self.handle_inventory_item_selected(member, clean_phone, item_id, user_language)
            return

        # Check for inv_search_next_ button IDs (inventory search pagination)
        if target_id.startswith('inv_search_next_'):
            offset_str = target_id.replace('inv_search_next_', '')
            user_context = self._get_user_context(clean_phone)
            if user_context and user_context.get('inventory_search_results'):
                try:
                    offset = int(offset_str)
                    results = user_context.get('search_results', [])
                    search_term = user_context.get('search_term', '')
                    self._show_inventory_search_results(clean_phone, results, user_language, offset=offset, search_term=search_term)
                except ValueError:
                    self.handle_property_inventory_menu(member, clean_phone, user_language)
            else:
                self.handle_property_inventory_menu(member, clean_phone, user_language)
            return

        # Check for switch_client_ button IDs (client switching from /client or Settings)
        if target_id.startswith('switch_client_'):
            client_id_str = target_id.replace('switch_client_', '')
            print(f"🏢 Client switch button: ID={client_id_str}")
            try:
                client_id = int(client_id_str)
                # Look up client name
                conn = self.get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT id, name FROM clients WHERE id = %s", (client_id,))
                client = cursor.fetchone()
                cursor.close()
                conn.close()
                if client:
                    self._do_client_switch(member, clean_phone, client, user_language)
                else:
                    self.whatsapp_service.send_message(clean_phone, "❌ Client not found.", user_language)
            except Exception as e:
                print(f"❌ Error switching client from button: {e}")
                self.whatsapp_service.send_message(clean_phone, "❌ Error switching client.", user_language)
            return

        # Check for skip_inventory button IDs (like "skip_inventory_123")
        if target_id.startswith('skip_inventory_'):
            task_id = target_id.replace('skip_inventory_', '')
            print(f"🔍 DEBUG: Received skip_inventory button ID for task: {task_id}")
            self.handle_skip_inventory(member, clean_phone, task_id, user_language)
            return
            
        # Check for next_tasks button IDs (like "next_tasks_2")
        if target_id.startswith('next_tasks_'):
            parts = target_id.split('_')
            if len(parts) >= 3:
                try:
                    offset = int(parts[2])
                    self.handle_list_tasks(member, clean_phone, user_language, offset=offset)
                except ValueError:
                    self.handle_list_tasks(member, clean_phone, user_language)
            return
        
        # Check for back_to_tasks button
        if target_id == 'back_to_tasks':
            self.handle_list_tasks(member, clean_phone, user_language)
            return
            
        # Fallback: Check if message matches any button title
        if message in button_mappings:
            print(f"✅ Fallback button matched by title: {message}")
            button_mappings[message]()
            return
        
        # For text commands (lowercase processing)
        message_text = message.strip().lower()
        
        # Explicit dynamic inbound translation if the user's language is not English
        # We don't want to translate system buttons (which start with known prefixes)
        if user_language != 'en' and not message.startswith(('task_', 'status_', 'back_', 'mark_complete_', 'update_status_', 'skip_inventory_', 'property_', 'btn_', 'lang_')):
            try:
                # Ask LanguageService to translate the inbound message from `user_language` -> English
                translated_msg = self.language_service.translate_text(message_text, "en")
                if translated_msg:
                    print(f"🔄 Translated inbound message: '{message_text}' -> '{translated_msg}'")
                    message_text = translated_msg.strip().lower()
            except Exception as e:
                print(f"Error translating inbound message to English: {e}")
        
        if message_text in ['hi', 'hello', 'hii', 'hey', 'नमस्ते', 'hola', 'bonjour', 'greetings', 'welcome']:
            self.show_main_menu(member, clean_phone, user_language)
        elif message_text in ['tasks', '1', 'my tasks', 'task', '📋 tasks', 'work', 'my work', 'jobs', 'list tasks']:
            self.handle_list_tasks(member, clean_phone, user_language)
        elif message_text.startswith('status ') or message_text.startswith('update status '):
            self.handle_update_status(member, clean_phone, message_text, user_language)
        elif message_text in ['inventory', '2', '📦 inventory', 'items', 'stock']:
            self.handle_property_inventory_menu(member, clean_phone, user_language)
        elif message_text in ['settings', '3', 'setting', '⚙️ settings', 'options', 'preferences']:
            self.show_settings_menu(member, clean_phone, user_language)
        elif message_text in ['help', '4', '❓ help', 'assist', 'assistance']:
            self.handle_help(member, clean_phone, user_language)
        elif message_text in ['recurring', '5', 'recurring tasks', '🔄 recurring']:
            self.handle_recurring_tasks(member, clean_phone, user_language)
        elif message_text in ['main menu', 'menu', 'home', 'back to menu']:  
            self.show_main_menu(member, clean_phone, user_language)
        elif message_text in ['select property', 'change property', 'property']:  
            self.show_property_selection_menu(member, clean_phone, user_language)
        elif media_url:
            self.handle_image_upload(member, clean_phone, media_url, user_language)
        else:
            self.handle_unknown_command(member, clean_phone, user_language)

    def handle_voice_message(self, phone_number, media_id):
        """Handle voice messages - download audio, transcribe, and process as text"""
        import tempfile
        import requests as req
        
        clean_phone = phone_number.replace('whatsapp:', '')
        print(f"🎙️ Processing voice message from {clean_phone}, media_id: {media_id}")
        
        member = self.team_member_model.find_by_phone(clean_phone)
        if not member:
            self.whatsapp_service.send_message(clean_phone, "❌ Sorry, you are not registered in our system.", 'en')
            return
        
        audio_file_path = None
        try:
            # Step 1: Download audio from Meta Graph API
            meta_token = os.getenv('META_ACCESS_TOKEN')
            api_version = os.getenv('META_API_VERSION', 'v19.0')
            
            # Get media URL
            media_info_url = f"https://graph.facebook.com/{api_version}/{media_id}"
            headers = {"Authorization": f"Bearer {meta_token}"}
            
            media_response = req.get(media_info_url, headers=headers)
            if media_response.status_code != 200:
                print(f"❌ Failed to get media info: {media_response.status_code}")
                self.whatsapp_service.send_message(clean_phone, "❌ Failed to process voice message.", 'en')
                return
            
            media_info = media_response.json()
            download_url = media_info.get('url')
            mime_type = media_info.get('mime_type', 'audio/ogg')
            
            if not download_url:
                print(f"❌ No download URL in media response")
                return
            
            # Download the actual audio file
            audio_response = req.get(download_url, headers=headers)
            if audio_response.status_code != 200:
                print(f"❌ Failed to download audio: {audio_response.status_code}")
                return
            
            # Determine extension from mime type
            ext_map = {
                'audio/ogg': '.ogg',
                'audio/mpeg': '.mp3',
                'audio/mp4': '.m4a',
                'audio/wav': '.wav',
                'audio/webm': '.webm',
                'audio/aac': '.aac',
                'audio/ogg; codecs=opus': '.ogg'
            }
            extension = ext_map.get(mime_type, '.ogg')
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp_file:
                tmp_file.write(audio_response.content)
                audio_file_path = tmp_file.name
            
            print(f"🎙️ Audio saved to: {audio_file_path} ({len(audio_response.content)} bytes)")
            
            # Step 2: Transcribe using Groq Whisper
            result = self.language_service.translation_service.transcribe_audio(audio_file_path)
            transcribed_text = result.get('text', '').strip()
            detected_language = result.get('language', 'en')
            
            print(f"🎙️ Transcription result: '{transcribed_text}' (language: {detected_language})")
            
            if not transcribed_text:
                # Could not transcribe - notify user
                user_lang = self._get_user_language(clean_phone, '')
                error_msg = self.whatsapp_service._get_translated_message('unknown_command', user_lang)
                self.whatsapp_service.send_message(clean_phone, f"🎙️ {error_msg}", user_lang)
                return
            
            # Step 3: Update user's language preference based on voice
            self.user_languages[clean_phone] = detected_language
            self.save_user_preferences(clean_phone, {'preferred_language': detected_language})
            
            # Step 4: Process as a regular text message
            print(f"🎙️ Routing transcribed text to handle_message: '{transcribed_text}'")
            self.handle_message(clean_phone, transcribed_text)
            
        except Exception as e:
            print(f"❌ Error processing voice message: {e}")
            import traceback
            traceback.print_exc()
            self.whatsapp_service.send_message(clean_phone, "❌ Failed to process voice message.", 'en')
        finally:
            # Clean up temp file
            if audio_file_path and os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                    print(f"🗑️ Cleaned up temp audio file: {audio_file_path}")
                except Exception:
                    pass

    def show_main_menu(self, member, phone_number, language):
        """Show the main menu with interactive buttons"""
        welcome_msg = self.whatsapp_service._get_translated_message('welcome', language)
        
        # Translate the instruction if not in English
        instruction = "Please select an option:"
        if language != 'en':
            instruction = self.language_service.translate_text(instruction, language)
            
        welcome_message = f"{welcome_msg.format(member['name'])}\n\n{instruction}"
        
        # Create properly formatted interactive buttons
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        
        # Send with buttons
        success = self.whatsapp_service.send_message(phone_number, welcome_message, language, buttons)
        
        if not success:
            # If buttons fail, show simple text menu
            text_menu = f"{welcome_message}\n\nReply with:\n1. Tasks\n2. Inventory\n3. Settings\n4. Help\n5. Recurring"
            self.whatsapp_service.send_message(phone_number, text_menu, language)

    def show_settings_menu(self, member, phone_number, language):
        """Show settings menu with interactive list"""
        settings_message = "⚙️ *Settings*\n\nPlease select an option from the list below:"
        
        # Create interactive list message for settings
        sections = [
            {
                "title": "Property Settings",
                "rows": [
                    {
                        "id": "property_change",
                        "title": "🏠 Change Property",
                        "description": "Select which property you're working on"
                    },
                    {
                        "id": "property_info",
                        "title": "📋 View Property Info",
                        "description": "See details of your current property"
                    }
                ]
            },
            {
                "title": "Account Settings",
                "rows": [
                    {
                        "id": "client_change",
                        "title": "🏢 Change Client",
                        "description": "Switch to a different client"
                    },
                    {
                        "id": "language_change",
                        "title": "🌐 Change Language",
                        "description": "Set your preferred language"
                    }
                ]
            },
            {
                "title": "Other",
                "rows": [
                    {
                        "id": "back_main",
                        "title": "⬅️ Main Menu",
                        "description": "Return to the main menu"
                    }
                ]
            }
        ]
        
        # Send interactive list message
        success = self.whatsapp_service.send_interactive_list(
            phone_number, 
            settings_message, 
            "Select an option", 
            sections,
            language
        )
        
        # Fallback to buttons if list fails
        if not success:
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "settings_property",
                        "title": "🏠 Properties"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "settings_back",
                        "title": "⬅️ Back"
                    }
                }
            ]
            self.whatsapp_service.send_message(phone_number, settings_message, language, buttons)

    def handle_property_selection(self, member, phone_number, selection_id, language):
        """Handle property-related selections from settings menu"""
        if selection_id == "property_change":
            # Show property selection list
            self.show_property_selection_menu(member, phone_number, language)
        elif selection_id == "property_info":
            # Show current property info
            self.show_current_property_info(member, phone_number, language)
        elif selection_id.startswith("property_"):
            # Handle actual property selection
            property_id = selection_id.replace("property_", "")
            # Find the property name
            properties = self.get_user_properties(member['id'])
            property_name = next((prop['name'] for prop in properties if str(prop['id']) == property_id), "Unknown Property")
            self.handle_property_selection_result(phone_number, property_id, property_name)

    def show_current_property_info(self, member, phone_number, language):
        """Show current property information for the user"""
        # First check database for saved property
        preferences = self.get_user_preferences(phone_number)
        current_property_id = None
        
        if preferences and preferences.get('last_selected_property_id'):
            current_property_id = preferences['last_selected_property_id']
        
        # Then check in-memory cache
        if not current_property_id and phone_number in self.user_property_selections:
            current_property = self.user_property_selections[phone_number]
            current_property_id = current_property['property_id']
            property_name = current_property['property_name']
        elif current_property_id:
            # Get property name from database
            properties = self.get_user_properties(member['id'])
            property_name = next((prop['name'] for prop in properties if prop['id'] == current_property_id), "Unknown Property")
        else:
            property_name = None
        
        if not current_property_id:
            # If no property selected, show message
            no_property_msg = "You haven't selected a property yet. Please select a property first."
            
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "select_property",
                        "title": "🏠 Select Property"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "back_settings",
                        "title": "⬅️ Back"
                    }
                }
            ]
            
            self.whatsapp_service.send_message(phone_number, no_property_msg, language, buttons)
            return
        
        # Get property details from database
        try:
            conn = self.task_model.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            query = """
                SELECT p.id, p.name, p.address, p.google_map_link, p.image,
                       p.created_at, p.updated_at,
                       (SELECT COUNT(*) FROM task_definitions td WHERE td.property_id = p.id) as total_tasks,
                       (SELECT COUNT(*) FROM task_definitions td 
                        JOIN task_occurrences tocc ON td.id = tocc.task_definition_id 
                        WHERE td.property_id = p.id AND tocc.status = 'pending') as pending_tasks
                FROM properties p
                WHERE p.id = %s
            """
            cursor.execute(query, (current_property_id,))
            property_details = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if property_details:
                # Format property information
                info_message = (
                    f"🏠 *Property Information*\n\n"
                    f"*Name:* {property_details['name']}\n"
                    f"*Address:* {property_details['address']}\n"
                    f"*Total Tasks:* {property_details['total_tasks']}\n"
                    f"*Pending Tasks:* {property_details['pending_tasks']}\n"
                )
                
                if property_details.get('google_map_link'):
                    info_message += f"*Map:* {property_details['google_map_link']}\n"
                
                info_message += f"\nLast updated: {property_details.get('updated_at', 'N/A')}"
            else:
                info_message = f"Property information not found for ID: {current_property_id}"
            
        except Exception as e:
            print(f"Error getting property info: {e}")
            info_message = f"🏠 *Current Property*\n\n{property_name}"
        
        # Add action buttons
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": "change_property",
                    "title": "🔄 Change Property"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "view_tasks",
                    "title": "📋 View Tasks"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "back_settings",
                    "title": "⬅️ Back"
                }
            }
        ]
        
        self.whatsapp_service.send_message(phone_number, info_message, language, buttons)        

    def handle_property_selection_result(self, phone_number, property_id, property_name):
        """Handle property selection from interactive list and save to DB"""
        print(f"🎯 Property selection: phone={phone_number}, property_id={property_id}, property_name={property_name}")
        
        # Get member to verify property exists
        member = self.team_member_model.find_by_phone(phone_number.replace('whatsapp:', ''))
        if member:
            # Get actual property from database to ensure it exists
            properties = self.get_user_properties(member['id'])
            actual_property = None
            for prop in properties:
                if str(prop['id']) == property_id:
                    actual_property = prop
                    break
            
            if not actual_property:
                print(f"❌ Property ID {property_id} not found for user {member['id']}")
                error_msg = f"Property not found. Please select a valid property."
                self.whatsapp_service.send_message(phone_number, error_msg, 'en')
                return
            
            # Use the actual property name from database
            property_name = actual_property['name']
            
            # Store the user's property selection in memory
            self.user_property_selections[phone_number] = {
                'property_id': property_id,
                'property_name': property_name,
                'selected_at': 'now'
            }
            
            # Save to database
            success = self.save_user_preferences(phone_number, {
                'last_selected_property_id': property_id
            })
            
            if success:
                print(f"✅ Property '{property_name}' (ID: {property_id}) saved to database for {phone_number}")
            else:
                print(f"❌ Failed to save property to database for {phone_number}")
            
            # Get user language
            user_language = self.user_languages.get(phone_number, 'en')
            
            # Send confirmation message
            confirmation_message = f"✅ *Property Selected*\n\nYou've selected: *{property_name}*\n\nAll your tasks and activities will now be associated with this property."
            
            # Add options buttons
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "property_continue",
                        "title": "📋 View Tasks"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "property_change",
                        "title": "🔄 Change Property"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "main_menu",
                        "title": "🏠 Main Menu"
                    }
                }
            ]
            
            self.whatsapp_service.send_message(phone_number, confirmation_message, user_language, buttons)
        else:
            print(f"❌ Member not found for phone: {phone_number}")

    def show_property_selection_menu(self, member, phone_number, language):
        """Show property selection menu (called from Settings)"""
        # Get available properties for this user FROM ACTUAL DATABASE
        properties = self.get_user_properties(member['id'])
        
        if not properties:
            no_properties_msg = "You don't have any properties assigned to you yet. Please contact your administrator."
            self.whatsapp_service.send_message(phone_number, no_properties_msg, language)
            return
        
        property_message = "🏠 *Select a Property*\n\nPlease choose which property you want to work on:"
        
        # Create interactive list for properties
        sections = []
        current_section = {
            "title": "Available Properties",
            "rows": []
        }
        
        for prop in properties:
            # Format address (truncate if too long)
            address = prop.get('address', '')
            if address and len(address) > 50:
                address = address[:47] + "..."
            
            # Sanitize name: remove quotes and special chars that break WhatsApp API
            clean_name = prop['name'].replace('"', '').replace("'", '').strip()[:24]
            
            current_section['rows'].append({
                "id": f"property_{prop['id']}",
                "title": clean_name,
                "description": address or "No address"
            })
            # WhatsApp allows max 10 rows per section
            if len(current_section['rows']) == 10:
                sections.append(current_section)
                current_section = {
                    "title": "More Properties",
                    "rows": []
                }
        
        if current_section['rows']:
            sections.append(current_section)
        
        # Add back button
        sections.append({
            "title": "Navigation",
            "rows": [
                {
                    "id": "back_settings",
                    "title": "⬅️ Back to Settings",
                    "description": "Return to settings menu"
                }
            ]
        })
        
        # Send interactive list
        success = self.whatsapp_service.send_interactive_list(
            phone_number,
            property_message,
            "Select a property",
            sections,
            language
        )
        
        if not success:
            # Fallback to buttons (max 3 for WhatsApp)
            buttons = []
            for i, prop in enumerate(properties[:2], 1):
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"property_{prop['id']}",
                        "title": f"🏠 {prop['name'][:15]}"
                    }
                })
            
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": "back_settings",
                    "title": "⬅️ Back"
                }
            })
            
            self.whatsapp_service.send_message(phone_number, property_message, language, buttons)

    def get_user_properties(self, user_id):
        """Get properties assigned to the user from the actual database"""
        try:
            conn = self.task_model.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # First, get the user's client_id
            cursor.execute("SELECT client_id FROM team_members WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                cursor.close()
                conn.close()
                return []
            
            client_id = user['client_id']
            
            # Get properties for this client
            # Since there's no property_assignments table, get all properties for the client
            # If you have a different way to assign properties to users, update this query
            query = """
                SELECT p.id, p.name, p.address, p.google_map_link, p.image,
                       p.created_at, p.updated_at
                FROM properties p
                WHERE p.client_id = %s
                ORDER BY p.name
            """
            cursor.execute(query, (client_id,))
            properties = cursor.fetchall()
            
            print(f"📊 Found {len(properties)} properties for client_id {client_id}:")
            for prop in properties:
                print(f"  - ID: {prop['id']}, Name: {prop['name']}")
            
            cursor.close()
            conn.close()
            
            return properties
            
        except Exception as e:
            print(f"❌ Error getting user properties: {e}")
            import traceback
            traceback.print_exc()
            return []

    def handle_mark_complete_button(self, member, phone_number, language):
        """Handle 'Mark Complete' button click when button title is sent instead of ID"""
        print(f"🔍 DEBUG: handle_mark_complete_button called for {phone_number}")
        print(f"🔍 DEBUG: Message received: Could be button title or ID")
        
        # Try multiple ways to get the task ID:
        
        # 1. Check user context first (most reliable)
        user_context = self._get_user_context(phone_number)
        if user_context and 'current_task_id' in user_context:
            task_id = user_context['current_task_id']
            print(f"🔍 DEBUG: Found current_task_id in context: {task_id}")
            self.mark_task_complete(member, phone_number, task_id, language)
            return
        
        # 2. Check if we have a recently viewed task in the session
        # Try to get from the user's recent activity
        if hasattr(self, '_recent_task_views'):
            recent_task = self._recent_task_views.get(phone_number)
            if recent_task:
                print(f"🔍 DEBUG: Found recent task view: {recent_task}")
                self.mark_task_complete(member, phone_number, recent_task, language)
                return
        
        # 3. Get the user's tasks and check if there's an obvious pending task
        tasks = self.task_model.get_tasks_by_user(member['id'])
        
        if not tasks:
            print(f"🔍 DEBUG: No tasks found at all")
            error_msg = "No tasks found. Please ask your administrator to assign tasks to you."
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return
        
        # 4. Check if there's only one pending task
        pending_tasks = [task for task in tasks if task['status'] in ['pending', 'in_progress']]
        
        if len(pending_tasks) == 1:
            task_id = pending_tasks[0]['id']
            print(f"🔍 DEBUG: Only one pending task found, using task_id: {task_id}")
            self.mark_task_complete(member, phone_number, task_id, language)
            return
        
        # 5. Multiple pending tasks - ask user to select
        if pending_tasks:
            print(f"🔍 DEBUG: {len(pending_tasks)} pending tasks found, showing selection")
            
            # Format task list with selection buttons
            task_list = self.whatsapp_service.format_task_list(pending_tasks, language)
            message = task_list + "\n\n*Select a task to mark complete:*"
            
            # Create task selection buttons
            buttons = []
            for i, task in enumerate(pending_tasks[:3], 1):  # Show max 3 pending tasks
                task_title_short = task['title'][:12] + "..." if len(task['title']) > 12 else task['title']
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"mark_complete_{task['id']}",
                        "title": f"#{i}: {task_title_short}"
                    }
                })
            
            # Add back button
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": "back_to_tasks",
                    "title": "⬅️ Back"
                }
            })
            
            self.whatsapp_service.send_message(phone_number, message, language, buttons)
            return
        
        # 6. No pending tasks
        print(f"🔍 DEBUG: No pending tasks found")
        no_pending_msg = "You don't have any pending tasks to mark as complete."
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        self.whatsapp_service.send_message(phone_number, no_pending_msg, language, buttons)

    def handle_update_status_button(self, member, phone_number, language):
        """Handle 'Update Status' button click"""
        print(f"🔍 DEBUG: handle_update_status_button called for {phone_number}")
        print(f"🔍 DEBUG: Checking user context...")
        
        # Try multiple phone number formats to get context
        user_context = None
        clean_phone = phone_number.replace('whatsapp:', '')
        
        # Check all possible formats
        for phone_format in [phone_number, clean_phone, f"whatsapp:{clean_phone}"]:
            user_context = self._get_user_context(phone_format)
            if user_context:
                print(f"🔍 DEBUG: Found context with format: {phone_format}")
                break
        
        print(f"🔍 DEBUG: User context: {user_context}")
        
        if user_context and 'current_task_id' in user_context:
            task_id = user_context['current_task_id']
            print(f"🔍 DEBUG: Found current_task_id: {task_id}")
            
            # Ensure context is stored for all formats
            self._store_user_context(clean_phone, {'current_task_id': task_id})
            self._store_user_context(phone_number, {'current_task_id': task_id})
            self._store_user_context(f"whatsapp:{clean_phone}", {'current_task_id': task_id})
            
            print(f"🔍 DEBUG: Calling show_status_options with task_id: {task_id}")
            self.show_status_options(member, phone_number, task_id, language)
        else:
            print(f"🔍 DEBUG: No current_task_id in context, checking for most recent task")
            # Try to find the most recent task
            tasks = self.task_model.get_tasks_by_user(member['id'])
            if tasks:
                task = tasks[0]
                task_id = task['id']
                print(f"🔍 DEBUG: Using most recent task ID: {task_id}")
                
                # Store task_id in context for all formats
                self._store_user_context(clean_phone, {'current_task_id': task_id})
                self._store_user_context(phone_number, {'current_task_id': task_id})
                self._store_user_context(f"whatsapp:{clean_phone}", {'current_task_id': task_id})
                
                self.show_status_options(member, phone_number, task_id, language)
            else:
                print(f"🔍 DEBUG: No tasks found, showing task list")
                # Show task list to select from
                self.handle_list_tasks(member, phone_number, language)

    def handle_back_to_task_button(self, member, phone_number, language):
        """Handle 'Back to Task' button click"""
        user_context = self._get_user_context(phone_number)
        
        if user_context and 'current_task_id' in user_context:
            task_id = user_context['current_task_id']
            self.show_task_options(member, phone_number, task_id, language)
        else:
            self.handle_list_tasks(member, phone_number, language)

    def handle_status_selection(self, member, phone_number, status, language):
        """Handle status selection button click"""
        user_context = self._get_user_context(phone_number)
        
        if user_context and 'current_task_id' in user_context:
            task_id = user_context['current_task_id']
            self.update_task_from_button(member, phone_number, task_id, status, language)
        else:
            error_msg = "Please select a task first."
            self.whatsapp_service.send_message(phone_number, error_msg, language)


    def handle_task_selection_button(self, member, phone_number, button_title, tasks, language):
        """Handle task selection from button title like '#1: Clean Room 101'"""
        try:
            # Extract task number from button title
            # Format: "#1: Clean Room 101" or "#1: Clean Room..."
            task_match = button_title.split(':')[0]  # Get "#1"
            task_number_str = task_match.replace('#', '').strip()  # Get "1"
            task_index = int(task_number_str) - 1  # Convert to 0-based index
            
            if 0 <= task_index < len(tasks):
                task = tasks[task_index]
                # Store current task in context
                self._store_user_context(phone_number, {'current_task_id': task['id']})
                self.show_task_options(member, phone_number, task['id'], language)
            else:
                self.handle_unknown_command(member, phone_number, language)
        except (ValueError, IndexError):
            self.handle_unknown_command(member, phone_number, language)

    def show_status_options(self, member, phone_number, task_id, language):
        """Show status selection options for a task using interactive list"""
        # Store the task ID in context
        self._store_user_context(phone_number, {'current_task_id': task_id})
    
        # Also store in recent task views
        if not hasattr(self, '_recent_task_views'):
            self._recent_task_views = {}
        self._recent_task_views[phone_number] = task_id

        task = self.task_model.get_task_by_id(task_id, member['id'])
        
        if not task:
            error_msg = self.whatsapp_service._get_translated_message('invalid_task', language)
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return
        
        message = f"*Select status for:*\n{task['title']}\n\nCurrent: {self.whatsapp_service.get_status_emoji(task['status'])} {task['status']}"
        
        # Create interactive list sections for status selection
        sections = [
            {
                "title": "Change Status",
                "rows": [
                    {
                        "id": f"status_pending_{task_id}",
                        "title": "⏳ Pending",
                        "description": "Mark as pending"
                    },
                    {
                        "id": f"status_inprogress_{task_id}",
                        "title": "🔄 In Progress",
                        "description": "Mark as in progress"
                    },
                    {
                        "id": f"status_complete_{task_id}",
                        "title": "✅ Complete",
                        "description": "Mark as completed"
                    },
                    {
                        "id": f"status_skipped_{task_id}",
                        "title": "⏭️ Skipped",
                        "description": "Mark as skipped"
                    }
                ]
            },
            {
                "title": "Navigation",
                "rows": [
                    {
                        "id": f"back_task_{task_id}",
                        "title": "⬅️ Back to Task",
                        "description": "Return to task options"
                    }
                ]
            }
        ]
        
        # Send interactive list (can have more than 3 options)
        success = self.whatsapp_service.send_interactive_list(
            phone_number,
            message,
            "Select Status",
            sections,
            language
        )
        
        if not success:
            # Fallback to buttons with only 3 options
            self._show_status_fallback(member, phone_number, task_id, task, language)

    def handle_mark_complete_from_button_id(self, member, phone_number, button_id, language):
        """Handle mark complete from button ID like 'mark_complete_123'"""
        try:
            # Extract task ID from button ID
            task_id = button_id.replace('mark_complete_', '')
            print(f"🔍 DEBUG: Extracted task_id {task_id} from button_id {button_id}")
            
            # Verify the task exists and belongs to the user
            task = self.task_model.get_task_by_id(task_id, member['id'])
            if not task:
                print(f"🔍 DEBUG: Task {task_id} not found or doesn't belong to user")
                error_msg = "Task not found or you don't have permission to update it."
                self.whatsapp_service.send_message(phone_number, error_msg, language)
                return
            
            # Store in context for future reference
            self._store_user_context(phone_number, {'current_task_id': task_id})
            
            # Mark the task as complete
            self.mark_task_complete(member, phone_number, task_id, language)
            
        except Exception as e:
            print(f"❌ Error handling mark complete from button ID: {e}")
            error_msg = "Unable to mark task as complete. Please try again."
            self.whatsapp_service.send_message(phone_number, error_msg, language)

    def _show_status_fallback(self, member, phone_number, task_id, task, language):
        """Fallback method with only 3 buttons"""
        message = f"*Select status for:*\n{task['title']}\n\nCurrent: {self.whatsapp_service.get_status_emoji(task['status'])} {task['status']}"
        
        # Show only 3 buttons: 2 status options + back button
        current_status = task['status']
        
        # Define priority statuses to show
        priority_statuses = ['completed', 'in_progress', 'pending', 'skipped']
        
        # Remove current status from options
        available_statuses = [s for s in priority_statuses if s != current_status]
        
        buttons = []
        # Add up to 2 status buttons
        for i, status in enumerate(available_statuses[:2]):
            status_title = {
                'pending': '⏳ Pending',
                'in_progress': '🔄 In Progress',
                'completed': '✅ Complete',
                'skipped': '⏭️ Skipped'
            }.get(status, status)
            
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"status_{status.replace('_', '')}_{task_id}",
                    "title": status_title
                }
            })
        
        # Add back button as the 3rd button
        buttons.append({
            "type": "reply",
            "reply": {
                "id": f"back_task_{task_id}",
                "title": "⬅️ Back to Task"
            }
        })
        
        self.whatsapp_service.send_message(phone_number, message, language, buttons)

    def save_user_preferences(self, phone_number, preferences):
        """Save user preferences to database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get team member ID
            member = self.team_member_model.find_by_phone(phone_number.replace('whatsapp:', ''))
            if not member:
                return False
            
            # Build update query based on provided preferences
            updates = []
            values = []
            
            if 'preferred_language' in preferences:
                updates.append("preferred_language = %s")
                values.append(preferences['preferred_language'])
            
            if 'last_selected_property_id' in preferences:
                # Convert property_id to integer and ensure it's valid
                try:
                    property_id = int(preferences['last_selected_property_id'])
                    updates.append("last_selected_property_id = %s")
                    values.append(property_id)
                    print(f"💾 Saving property_id: {property_id} for user: {member['id']}")
                except (ValueError, TypeError) as e:
                    print(f"❌ Invalid property_id: {preferences['last_selected_property_id']}, Error: {e}")
                    # Don't save invalid property_id
            
            # if 'notification_preferences' in preferences:
            #     updates.append("notification_preferences = %s")
            #     values.append(json.dumps(preferences['notification_preferences']))
            
            updates.append("settings_updated_at = CURRENT_TIMESTAMP")
            
            if updates:
                query = f"""
                    UPDATE team_members 
                    SET {', '.join(updates)} 
                    WHERE id = %s
                """
                values.append(member['id'])
                
                print(f"📝 Executing query: {query}")
                print(f"📝 With values: {values}")
                
                cursor.execute(query, values)
                conn.commit()
                
                print(f"✅ Preferences saved successfully for user ID: {member['id']}")
                
                cursor.close()
                conn.close()
                return True
            
            cursor.close()
            conn.close()
            return False
            
        except Exception as e:
            print(f"❌ Error saving user preferences: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    def check_database_structure(self):
        """Check if the required columns exist in the database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Check team_members table structure
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'team_members'
                AND COLUMN_NAME IN ('preferred_language', 'last_selected_property_id', 'settings_updated_at')
            """)
            
            columns = cursor.fetchall()
            print("📊 Database columns found:")
            for col in columns:
                print(f"  - {col['COLUMN_NAME']}: {col['DATA_TYPE']} (Nullable: {col['IS_NULLABLE']})")
            
            cursor.close()
            conn.close()
            
            return columns
            
        except Exception as e:
            print(f"❌ Error checking database structure: {e}")
            return None    
    
    def get_user_preferences(self, phone_number):
        """Get user preferences from database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Get team member ID
            member = self.team_member_model.find_by_phone(phone_number.replace('whatsapp:', ''))
            if not member:
                return None
            
            query = """
                SELECT 
                    preferred_language,
                    last_selected_property_id,
                    settings_updated_at
                FROM team_members 
                WHERE id = %s
            """
            cursor.execute(query, (member['id'],))
            preferences = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            # # Parse JSON if exists
            # if preferences and preferences.get('notification_preferences'):
            #     try:
            #         preferences['notification_preferences'] = json.loads(preferences['notification_preferences'])
            #     except:
            #         preferences['notification_preferences'] = {}
            
            return preferences
            
        except Exception as e:
            print(f"Error getting user preferences: {e}")
            return None
    
    def _get_user_language(self, phone_number, message):
        """Get user's language preference from DB/cache. Language only changes via Settings menu."""
        # Check in-memory cache first
        if phone_number in self.user_languages:
            return self.user_languages[phone_number]
            
        # Fallback to database
        preferences = self.get_user_preferences(phone_number)
        if preferences and preferences.get('preferred_language'):
            db_language = preferences['preferred_language']
            self.user_languages[phone_number] = db_language
            return db_language
            
        return 'en'
    
    def save_language_preference(self, phone_number, language_code, language_name):
        """Save language preference to database"""
        # Update in-memory language preference
        self.user_languages[phone_number] = language_code
        
        # Save to database
        success = self.save_user_preferences(phone_number, {
            'preferred_language': language_code
        })
        
        if success:
            confirmation_message = f"✅ *Language Updated*\n\nYour preferred language has been set to: *{language_name}*"
            
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "continue_settings",
                        "title": "⚙️ Continue Settings"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "main_menu",
                        "title": "🏠 Main Menu"
                    }
                }
            ]
            
            self.whatsapp_service.send_message(phone_number, confirmation_message, language_code, buttons)
        else:
            error_message = "❌ Failed to save language preference. Please try again."
            self.whatsapp_service.send_message(phone_number, error_message, language_code)

    def handle_greeting(self, member, phone_number, language):
        """Show main menu instead of old greeting"""
        self.show_main_menu(member, phone_number, language)

    def handle_list_tasks(self, member, phone_number, language, offset=0):
        tasks = self.task_model.get_tasks_by_user(member['id'])
        if not tasks:
            no_tasks_msg = self.whatsapp_service._get_translated_message('no_tasks', language)
            buttons = self.whatsapp_service._create_welcome_buttons(language)
            self.whatsapp_service.send_message(phone_number, no_tasks_msg, language, buttons)
            return
        
        total_tasks = len(tasks)
        
        # Ensure offset is valid
        if offset >= total_tasks:
            offset = 0
            
        current_tasks = tasks[offset:offset+2]
        
        # Format task list
        task_list = self.whatsapp_service.format_task_list(
            current_tasks, 
            language, 
            total_count=total_tasks, 
            start_index=offset + 1
        )
        
        # Add selection instruction
        message = task_list + "\n\n*Select a task to update:*"
        
        # Create SIMPLER task selection buttons
        # WhatsApp allows max 3 buttons, so show max 2 tasks + Next/Main Menu
        buttons = []
        for i, task in enumerate(current_tasks):
            actual_num = offset + i + 1
            task_title_short = task['title'][:12] + "..." if len(task['title']) > 12 else task['title']
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"task_{task['id']}",
                    "title": f"#{actual_num}: {task_title_short}"
                }
            })
            
        # Third button: "Next Tasks" or "Main Menu"
        if offset + 2 < total_tasks:
            # There are more tasks available
            next_offset = offset + 2
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"next_tasks_{next_offset}",
                    "title": "⏭️ Next Tasks"
                }
            })
        else:
            # Add main menu button
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": "main_menu",
                    "title": "🏠 Main Menu"
                }
            })
        
        # Send with buttons
        success = self.whatsapp_service.send_message(phone_number, message, language, buttons)
        
        if not success:
            # Fallback to text message
            self.whatsapp_service.send_message(phone_number, task_list, language)

    def handle_button_action(self, member, phone_number, button_id, language):
        """Handle button click actions"""
        print(f"🔘 Button clicked: {button_id}")
        
        if button_id.startswith('task_'):
            # Task selection button
            task_id = button_id.replace('task_', '')
            self.show_task_options(member, phone_number, task_id, language)
        elif button_id.startswith('complete_'):
            # Mark complete button
            parts = button_id.split('_')
            if len(parts) >= 2:
                task_id = parts[1]
                self.mark_task_complete(member, phone_number, task_id, language)
        elif button_id.startswith('status_'):
            # Status selection button
            parts = button_id.split('_')
            if len(parts) >= 3:
                task_id = parts[1]
                status = parts[2].replace('_', ' ')
                self.update_task_from_button(member, phone_number, task_id, status, language)
        elif button_id.startswith('back_tasks_'):
            # Back to tasks button
            self.handle_list_tasks(member, phone_number, language)
        elif button_id.startswith('inv_prop_'):
            # Property selection for inventory
            property_id = button_id.replace('inv_prop_', '')
            self.handle_property_inventory_selection(member, phone_number, property_id, language)

    def show_task_options(self, member, phone_number, task_id, language):
        """Show options for a specific task"""
        # Store the current task ID in user context
        self._store_user_context(phone_number, {'current_task_id': task_id})
        
        # Also store in recent task views for backup
        if not hasattr(self, '_recent_task_views'):
            self._recent_task_views = {}
        self._recent_task_views[phone_number] = task_id
        
        task = self.task_model.get_task_by_id(task_id, member['id'])
        
        if not task:
            error_msg = self.whatsapp_service._get_translated_message('invalid_task', language)
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return
        
        # Create task details message
        message = (
            f"*Task Details:*\n\n"
            f"📋 *{task['title']}*\n"
            f"📝 {task.get('description', 'No description')}\n"
            f"🏠 Property: {task.get('property_name', 'N/A')}\n"
            f"📊 Status: {self.whatsapp_service.get_status_emoji(task['status'])} {task['status']}\n\n"
            f"*What would you like to do?*"
        )
        
        # Create action buttons
        buttons = self.whatsapp_service._create_task_completion_buttons(task_id, language)
        
        self.whatsapp_service.send_message(phone_number, message, language, buttons)

    def handle_mark_complete_from_selection(self, member, phone_number, message, language):
        """Handle mark complete from task selection menu"""
        try:
            # Message format: "mark_complete_123"
            task_id = message.replace('mark_complete_', '')
            self.mark_task_complete(member, phone_number, task_id, language)
        except Exception as e:
            print(f"❌ Error handling mark complete from selection: {e}")
            error_msg = "Unable to mark task as complete. Please try again."
            self.whatsapp_service.send_message(phone_number, error_msg, language)

    def mark_task_complete(self, member, phone_number, task_id, language):
        """Mark a task as complete via button"""
        task = self.task_model.get_task_by_id(task_id, member['id'])
        
        if not task:
            error_msg = self.whatsapp_service._get_translated_message('invalid_task', language)
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return
        
        # Check if task requires photo and allows inventory update
        requires_photo = task.get('requires_photo', 0) == 1
        allows_inventory_update = task.get('allows_inventory_update', 0) == 1

        print(f"🔍 Task check - requires_photo: {requires_photo}, allows_inventory_update: {allows_inventory_update}")
        
        # Get clean phone number
        clean_phone = phone_number.replace('whatsapp:', '')
        
        # If both photo required AND inventory update allowed, show combined options
        if requires_photo and allows_inventory_update:
            # Store task info for completion flow with BOTH phone formats
            context_data = {
                'pending_completion_task': task_id,
                'completion_flow': 'photo_and_inventory'
            }
            self._store_user_context(clean_phone, context_data)
            self._store_user_context(phone_number, context_data)
            
            # Ask for photo first (photo is usually required before inventory)
            photo_inventory_msg = (
                f"📸 *Photo & Inventory Update Required*\n\n"
                f"Task \"{task['title']}\" requires:\n"
                f"1. Completion photo\n"
                f"2. Inventory quantity update\n\n"
                f"📸 Please send a photo of the completed work first, then I'll ask for inventory updates."
            )
            
            buttons = [{
                "type": "reply",
                "reply": {
                    "id": f"back_task_{task_id}",
                    "title": "⬅️ Back to Task"
                }
            }]
            
            self.whatsapp_service.send_message(phone_number, photo_inventory_msg, language, buttons)
            return
        
        # If only photo is required
        if requires_photo:
            # Task needs photo, ask for it
            photo_required_msg = self.whatsapp_service._get_translated_message('photo_required', language)
            message = (
                f"{photo_required_msg}\n\n"
                f"Task \"{task['title']}\" requires a completion photo.\n\n"
                f"📸 Please send a photo of the completed work now, and I'll automatically mark it as completed!"
            )
            
            # Store task_id in user context for photo attachment
            self._store_user_context(phone_number, {'pending_photo_task': task_id})
            
            buttons = [{
                "type": "reply",
                "reply": {
                    "id": f"back_task_{task_id}",
                    "title": "⬅️ Back to Task"
                }
            }]
            
            self.whatsapp_service.send_message(phone_number, message, language, buttons)
            return
        
        # If only inventory update is allowed (no photo required)
        if allows_inventory_update:
            # Store task info for inventory update flow
            self._store_user_context(phone_number, {
                'pending_completion_task': task_id,
                'completion_flow': 'inventory_only'
            })
            
            # Get inventory items linked to this task
            inventory_items = self.get_inventory_for_task(task_id)
            
            if inventory_items:
                inventory_msg = (
                    f"📦 *Inventory Update Required*\n\n"
                    f"Task \"{task['title']}\" requires inventory updates:\n\n"
                )
                
                for i, item in enumerate(inventory_items, 1):
                    inventory_msg += f"{i}. {item['name']} ({item['current_quantity']} {item['unit']})\n"
                
                inventory_msg += f"\nPlease send the new quantity for the first item:\n"
                inventory_msg += f"Example: `10`\n"
                inventory_msg += f"(Or specify item: `2 5`)"
                
                # Store inventory items for reference
                self._store_user_context(phone_number, {
                    'pending_completion_task': task_id,
                    'completion_flow': 'inventory_only',
                    'inventory_items': inventory_items
                })
                
            else:
                inventory_msg = (
                    f"📦 *Inventory Update*\n\n"
                    f"Task \"{task['title']}\" allows inventory updates but no items are linked.\n"
                    f"Proceeding with completion..."
                )
                # If no inventory items, complete directly
                success = self.task_model.update_task_status(task_id, 'completed', member['id'])
                if success:
                    inventory_msg += f"\n\n✅ Task marked as completed!"
            
            buttons = [{
                "type": "reply",
                "reply": {
                    "id": f"back_task_{task_id}",
                    "title": "⬅️ Back to Task"
                }
            }]
            
            self.whatsapp_service.send_message(phone_number, inventory_msg, language, buttons)
            return
        
        # Task can be completed without photo or inventory
        success = self.task_model.update_task_status(task_id, 'completed', member['id'])
        
        if success:
            task_completed_msg = self.whatsapp_service._get_translated_message('task_completed', language)
            message = f"{task_completed_msg} 🎉\n\nTask \"{task['title']}\" is now marked as completed!"
        else:
            message = "❌ Failed to update task status."
        
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        self.whatsapp_service.send_message(phone_number, message, language, buttons)

    def update_task_from_button(self, member, phone_number, task_id, status, language):
        """Update task status from button selection"""
        # Map button status to database status
        status_map = {
            'pending': 'pending',
            'in_progress': 'in_progress',
            'complete': 'completed',
            'skipped': 'skipped'
        }
        
        db_status = status_map.get(status.lower(), status.lower())
        
        if db_status == 'completed':
            # Check photo requirement for completion
            self.mark_task_complete(member, phone_number, task_id, language)
            return
        
        # Update to other statuses
        success = self.task_model.update_task_status(task_id, db_status, member['id'])
        
        if success:
            task = self.task_model.get_task_by_id(task_id, member['id'])
            status_updated_msg = self.whatsapp_service._get_translated_message('status_updated', language)
            message = f"{status_updated_msg}: {task['title']} → {db_status}"
        else:
            message = "❌ Failed to update task status."
        
        # Show task options again
        self.show_task_options(member, phone_number, task_id, language)

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

        if new_status not in ['pending', 'in_progress', 'completed', 'skipped']:
            status_error_msg = self.whatsapp_service._get_translated_message('invalid_status', language) or "❌ Invalid status. Use: pending, in_progress, completed, or skipped"
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
            status_updated_msg = self.whatsapp_service._get_translated_message('status_updated', language) or "✅ Status updated"
            response_message = f"{status_updated_msg}: {task['title']} → {new_status}"
            # After status update, show action buttons
            buttons = self.whatsapp_service._create_task_action_buttons(language)
            self.whatsapp_service.send_message(phone_number, response_message, language, buttons)
        else:
            response_message = "❌ Failed to update task status."
            self.whatsapp_service.send_message(phone_number, response_message, language)

    def handle_image_upload(self, member, phone_number, media_id, language):
        """Handle image upload from WhatsApp with language support"""
        try:
            # # Send immediate acknowledgment
            # self.whatsapp_service.send_message(
            #     phone_number, 
            #     "📸 Photo received! Processing...", 
            #     language
            # )
            print(f"🖼️ Processing image upload from {phone_number}")
            print(f"📎 Media ID: {media_id}")
            
            # Check user context to understand the flow
            clean_phone = phone_number.replace('whatsapp:', '')
            user_context = self._get_user_context(clean_phone)
            
            if not user_context:
                # Try with original format
                user_context = self._get_user_context(phone_number)
            
            print(f"🔍 Current user context: {user_context}")
            
            # FIRST: Check if this is a photo+inventory flow
            if user_context and 'completion_flow' in user_context:
                task_id = user_context.get('pending_completion_task')
                flow_type = user_context['completion_flow']
                
                print(f"🔍 Flow type: {flow_type}, Task ID: {task_id}")
                
                if flow_type == 'photo_and_inventory':
                    # Process the photo first
                    print(f"📸 Processing photo for photo+inventory flow")
                    image_path = self.image_service.download_meta_media(
                        media_id, 
                        task_id, 
                        member['id']
                    )
                    
                    if not image_path:
                        download_error_msg = self.whatsapp_service._get_translated_message('download_error', language)
                        self.whatsapp_service.send_message(phone_number, download_error_msg, language)
                        return
                    
                    # Upload to backend
                    client_id = member.get('client_id')
                    uploaded_filename = self.image_service.upload_to_backend(
                        image_path, 
                        task_id, 
                        client_id
                    ) if client_id else None
                    
                    # Store the uploaded filename even if API fails
                    if not uploaded_filename:
                        uploaded_filename = os.path.basename(image_path)
                    
                    print(f"✅ Photo uploaded: {uploaded_filename}")
                    
                    # Get inventory items for this task BEFORE asking for updates
                    inventory_items = self.get_inventory_for_task(task_id)
                    
                    if inventory_items and len(inventory_items) > 0:
                        # Store updated context with inventory items
                        new_context = {
                            'pending_completion_task': task_id,
                            'completion_flow': 'inventory_only',
                            'photo_uploaded': True,
                            'photo_filename': uploaded_filename,
                            'inventory_items': inventory_items,  # CRITICAL: Store the inventory items
                            'task_needs_completion': True  # Mark that task still needs completion
                        }
                        
                        # Store with both phone number formats
                        self._store_user_context(clean_phone, new_context)
                        self._store_user_context(phone_number, new_context)
                        
                        # Ask for inventory updates
                        inventory_msg = (
                            f"✅ *Photo uploaded successfully!*\n\n"
                            f"📦 *Now, update inventory quantities:*\n\n"
                        )
                        
                        for i, item in enumerate(inventory_items, 1):
                            inventory_msg += f"{i}. {item['name']} (Current: {item['current_quantity']} {item.get('unit', 'piece')})\n"
                        
                        inventory_msg += f"\nPlease send the new quantity for the first item:\n"
                        inventory_msg += f"Example: `10`\n"
                        inventory_msg += f"(Or specify item: `2 5`)\n\n"
                        inventory_msg += f"Or send 'skip' to complete without inventory updates."
                        
                        print(f"📦 Asking for inventory updates for {len(inventory_items)} items")
                        
                        # Send the inventory update message
                        self.whatsapp_service.send_message(phone_number, inventory_msg, language)
                        return
                        
                    else:
                        # Task has allows_inventory_update but no items linked yet
                        # Ask user if they want to skip inventory or the task needs inventory items to be linked
                        print(f"📦 No inventory items linked to task {task_id}, but task allows inventory update")
                        
                        # Store context so user can skip or we can handle their response
                        new_context = {
                            'pending_completion_task': task_id,
                            'completion_flow': 'inventory_only',
                            'photo_uploaded': True,
                            'photo_filename': uploaded_filename,
                            'inventory_items': [],  # Empty but flow is set
                            'task_needs_completion': True,
                            'no_inventory_items_linked': True  # Flag to indicate no items were found
                        }
                        
                        self._store_user_context(clean_phone, new_context)
                        self._store_user_context(phone_number, new_context)
                        
                        inventory_msg = (
                            f"✅ *Photo uploaded successfully!*\n\n"
                            f"📦 *Inventory Update*\n\n"
                            f"This task allows inventory updates but no specific items are linked.\n\n"
                            f"Please reply with:\n"
                            f"• 'skip' - to complete without inventory updates\n"
                            f"• Or contact your administrator to link inventory items to this task"
                        )
                        
                        buttons = [{
                            "type": "reply",
                            "reply": {
                                "id": f"skip_inventory_{task_id}",
                                "title": "⏭️ Skip & Complete"
                            }
                        }]
                        
                        self.whatsapp_service.send_message(phone_number, inventory_msg, language, buttons)
                        return
                    
                elif flow_type == 'inventory_only':
                    # This shouldn't happen for image uploads
                    print(f"⚠️ Unexpected: Image upload in inventory_only flow")
                    # Fall through to default handling
            
            # SECOND: Check if this is a simple photo task
            if user_context and 'pending_photo_task' in user_context:
                task_id = user_context['pending_photo_task']
                print(f"📸 Processing simple photo task {task_id}")
                
                # Check if this task also needs inventory
                task = self.task_model.get_task_by_id(task_id, member['id'])
                if task and task.get('allows_inventory_update', 0) == 1:
                    print(f"📦 Task {task_id} needs both photo and inventory, switching flow")
                    # This task needs both photo AND inventory, switch to photo+inventory flow
                    clean_phone = phone_number.replace('whatsapp:', '')
                    context_data = {
                        'pending_completion_task': task_id,
                        'completion_flow': 'photo_and_inventory'
                    }
                    self._store_user_context(clean_phone, context_data)
                    self._store_user_context(phone_number, context_data)
                    # Recursively call with updated context
                    self.handle_image_upload(member, phone_number, media_id, language)
                    return
                else:
                    print(f"📸 Task {task_id} is photo-only, processing directly")
                    # Simple photo-only task
                    self._clear_user_context(phone_number)
                    self._process_task_photo(member, phone_number, task_id, media_id, language)
                    return
            
            # THIRD: Default fallback - process as simple photo
            print(f"📸 No specific context, using default photo processing")
            self._process_task_photo_direct(member, phone_number, media_id, language)
                
        except Exception as e:
            print(f"❌ Error in image upload: {e}")
            import traceback
            traceback.print_exc()
            error_msg = self.whatsapp_service._get_translated_message('upload_error', language)
            self.whatsapp_service.send_message(phone_number, error_msg, language)


    def _process_task_photo(self, member, phone_number, task_id, media_id, language):
        """Helper method to process photo for a PHOTO-ONLY task (no inventory)"""
        # Download the image from WhatsApp Meta API
        image_path = self.image_service.download_meta_media(
            media_id, 
            task_id, 
            member['id']
        )

        if not image_path:
            download_error_msg = self.whatsapp_service._get_translated_message('download_error', language)
            self.whatsapp_service.send_message(phone_number, download_error_msg, language)
            return

        print(f"✅ Image downloaded: {image_path}")
        
        # Upload to backend API
        client_id = member.get('client_id')
        uploaded_filename = self.image_service.upload_to_backend(
            image_path, 
            task_id, 
            client_id
        ) if client_id else None
        
        # Mark task as completed
        success = self.task_model.update_task_status(task_id, 'completed', member['id'])
        
        if uploaded_filename or success:
            task_completed_msg = self.whatsapp_service._get_translated_message('task_completed', language)
            
            message = (
                f"{task_completed_msg} 🎉\n\n"
                f"✅ Photo attached successfully!\n"
                f"✅ Task marked as completed!\n\n"
                f"{self.whatsapp_service._get_translated_message('thank_you', language)} 📸"
            )
        else:
            # Fallback to direct database update
            filename = os.path.basename(image_path)
            success = self.task_model.add_completion_images_direct(task_id, filename, member['id'])
            
            if success:
                message = f"✅ Photo attached and task marked as completed!"
            else:
                message = "❌ Error saving image to task."

        # Send success message with welcome buttons
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        self.whatsapp_service.send_message(phone_number, message, language, buttons)

    def _process_task_photo_direct(self, member, phone_number, media_id, language):
        """Process photo when no context is available"""
        # Get pending photo tasks
        pending_photo_tasks = self.task_model.get_pending_photo_tasks(member['id'])
        if not pending_photo_tasks:
            no_tasks_msg = self.whatsapp_service._get_translated_message('no_tasks_photos', language)
            self.whatsapp_service.send_message(phone_number, no_tasks_msg, language)
            return
        
        # Use the first pending task
        task = pending_photo_tasks[0]
        task_id = task['id']
        
        # IMPORTANT: Also fetch full task details to ensure we have allows_inventory_update
        full_task = self.task_model.get_task_by_id(task_id, member['id'])
        allows_inventory = full_task.get('allows_inventory_update', 0) == 1 if full_task else task.get('allows_inventory_update', 0) == 1
        
        print(f"📸 _process_task_photo_direct: task_id={task_id}, allows_inventory={allows_inventory}")
        
        # Check if this task needs inventory
        if allows_inventory:
            # This task needs inventory too, start the combined flow
            clean_phone = phone_number.replace('whatsapp:', '')
            context_data = {
                'pending_completion_task': task_id,
                'completion_flow': 'photo_and_inventory'
            }
            self._store_user_context(clean_phone, context_data)
            self._store_user_context(phone_number, context_data)
            print(f"📦 Task {task_id} needs both photo and inventory, switching to combined flow")
            # Recursively process with the context now set
            self.handle_image_upload(member, phone_number, media_id, language)
        else:
            # Simple photo-only task
            self._process_task_photo(member, phone_number, task_id, media_id, language)

    def handle_text_message(self, member, phone_number, message, language):
        """Handle text messages that might be inventory updates"""
        print(f"🔍 Checking text message for inventory update from {phone_number}: '{message}'")
        
        # Get the cleaned phone number (without whatsapp: prefix)
        clean_phone = phone_number.replace('whatsapp:', '')
        
        # Try to get context with multiple formats
        user_context = self._get_user_context(clean_phone)
        
        if not user_context:
            print(f"🔍 No user context found for {clean_phone}")
            # Also try with whatsapp: prefix
            user_context = self._get_user_context(f"whatsapp:{clean_phone}")
            if not user_context:
                print(f"🔍 No user context found for whatsapp:{clean_phone} either")
                
                # FALLBACK: Check if message looks like inventory update format (e.g., "6" or "1 6")
                # and user has pending inventory tasks
                parts = message.strip().split()
                if len(parts) in [1, 2]:
                    try:
                        qty = parts[-1]  # Could be int or float
                        float(qty)  # Validate it's a number
                        
                        # Message looks like inventory update - try to recover context
                        print(f"🔍 Message '{message}' looks like inventory update, attempting recovery")
                        return self._handle_inventory_recovery(member, phone_number, message, language)
                    except (ValueError, TypeError):
                        pass
                
                return False
            else:
                print(f"🔍 Found context with whatsapp: prefix format")
        
        # DEBUG: Show what context was found
        print(f"🔍 DEBUG: user_context found = {user_context}")
        
        # Check if user is searching for inventory (typed a keyword)
        if user_context.get('inventory_search'):
            # User typed a search term for inventory
            search_term = message.strip()
            if search_term.lower() in ['exit', 'quit', 'cancel', 'main menu', 'menu']:
                self._clear_user_context(phone_number)
                self._clear_user_context(clean_phone)
                self.show_main_menu(member, phone_number, language)
                return True
            self._clear_user_context(phone_number)
            self._clear_user_context(clean_phone)
            self.handle_inventory_search(member, phone_number, search_term, language)
            return True

        # Check if user is updating a specific inventory item's quantity
        if user_context.get('inventory_update_item'):
            selected_item = user_context.get('selected_item')
            if selected_item:
                message_lower = message.strip().lower()
                if message_lower in ['exit', 'quit', 'cancel', 'main menu', 'menu']:
                    self._clear_user_context(phone_number)
                    self._clear_user_context(clean_phone)
                    self.show_main_menu(member, phone_number, language)
                    return True
                # Try to update quantity
                new_qty = message.strip()
                try:
                    float(new_qty)  # Validate it's a number
                except (ValueError, TypeError):
                    err_msg = "❌ Please enter a valid quantity number."
                    self.whatsapp_service.send_message(phone_number, err_msg, language)
                    return True
                
                old_qty = selected_item.get('current_quantity', '0')
                success = self.update_inventory_quantity(selected_item['id'], new_qty)
                if success:
                    self.task_model._log_task_activity(
                        None,
                        'standalone_inventory_updated',
                        f"Item: {selected_item['name']}, Qty: {old_qty}",
                        f"Item: {selected_item['name']}, Qty: {new_qty}",
                        member['id']
                    )
                    success_msg = (
                        f"✅ Updated *{selected_item['name']}* to {new_qty} {selected_item.get('unit', '')}\n\n"
                        "What would you like to do next?"
                    )
                    buttons = [
                        {"type": "reply", "reply": {"id": "btn_inventory", "title": "🔍 Search Again"}},
                        {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
                    ]
                    self._clear_user_context(phone_number)
                    self._clear_user_context(clean_phone)
                    self.whatsapp_service.send_message(phone_number, success_msg, language, buttons)
                else:
                    self.whatsapp_service.send_message(phone_number, "❌ Failed to update inventory. Please enter a valid quantity.", language)
                return True

        # Check if user is selecting a property for inventory (fallback number-based selection)
        if user_context.get('inventory_property_selection'):
            try:
                selection = int(message.strip())
                props = user_context.get('properties', [])
                if 1 <= selection <= len(props):
                    selected_prop = props[selection - 1]
                    print(f"📦 User selected property #{selection}: {selected_prop['name']} (ID: {selected_prop['id']})")
                    self._clear_user_context(phone_number)
                    self.handle_property_inventory_selection(member, phone_number, str(selected_prop['id']), language)
                    return True
            except (ValueError, TypeError):
                pass
        
        # Check if we are in standalone inventory mode
        if user_context.get('standalone_inventory'):
            return self.handle_standalone_inventory_update(member, phone_number, message, language, user_context)
            
        # Check if we're in inventory update flow
        # Also handle 'photo_and_inventory' flow if photo was already uploaded
        completion_flow = user_context.get('completion_flow', '')
        
        # Check if this looks like an inventory update even if completion_flow doesn't match
        # This handles cases where context was overwritten
        if completion_flow not in ['inventory_only', 'photo_and_inventory']:
            # Context found but doesn't have the right flow - check if message looks like inventory update
            parts = message.strip().split()
            if len(parts) in [1, 2]:
                try:
                    qty = parts[-1]
                    float(qty)
                    print(f"🔍 Context has wrong flow ({completion_flow}), but message looks like inventory update. Attempting recovery.")
                    return self._handle_inventory_recovery(member, phone_number, message, language)
                except (ValueError, TypeError):
                    pass
            print(f"🔍 Context has completion_flow='{completion_flow}', not an inventory flow")
            return False
        
        if completion_flow == 'photo_and_inventory' and not user_context.get('photo_uploaded'):
            print(f"🔍 Photo not yet uploaded for photo_and_inventory flow")
            return False
        
        task_id = user_context.get('pending_completion_task')
        inventory_items = user_context.get('inventory_items', [])
        
        print(f"🔍 Inventory flow: task_id={task_id}, items={len(inventory_items) if inventory_items else 0}")
        
        if not task_id:
            print(f"🔍 No task_id in context")
            return False
            
        if not inventory_items:
            print(f"🔍 No inventory items in context, attempting to recover from database")
            # Try to recover inventory items from database
            inventory_items = self.get_inventory_for_task(task_id)
            if inventory_items:
                print(f"🔍 Recovered {len(inventory_items)} inventory items from database")
                # Update context with recovered items
                user_context['inventory_items'] = inventory_items
                self._store_user_context(clean_phone, user_context)
                self._store_user_context(f"whatsapp:{clean_phone}", user_context)
            else:
                print(f"🔍 No inventory items found in database either")
                # Still handle 'skip' even if no items
                message_lower = message.strip().lower()
                if message_lower == 'skip':
                    print(f"🔍 User wants to skip (no items)")
                    success = self.task_model.update_task_status(task_id, 'completed', member['id'])
                    if success and user_context.get('photo_filename'):
                        # Also add photo if we have one
                        self.task_model.add_completion_images_direct(task_id, user_context['photo_filename'], member['id'])
                    
                    if success:
                        skip_msg = "✅ Task completed!"
                        buttons = self.whatsapp_service._create_welcome_buttons(language)
                        self.whatsapp_service.send_message(phone_number, skip_msg, language, buttons)
                    else:
                        skip_msg = "❌ Failed to complete task."
                        self.whatsapp_service.send_message(phone_number, skip_msg, language)
                    
                    self._clear_user_context(clean_phone)
                    self._clear_user_context(phone_number)
                    return True
                return False
        
        # Now we have inventory_items (either from context or recovered)
        message_lower = message.strip().lower()
        
        # Check if user wants to skip
        if message_lower == 'skip':
            print(f"🔍 User wants to skip inventory update")
            # Complete the task without inventory updates
            success = self.task_model.update_task_status(task_id, 'completed', member['id'])
            if success and user_context.get('photo_filename'):
                # Also add photo if we have one
                self.task_model.add_completion_images_direct(task_id, user_context['photo_filename'], member['id'])
            
            if success:
                skip_msg = "✅ Task completed without inventory updates!"
                buttons = self.whatsapp_service._create_welcome_buttons(language)
                self.whatsapp_service.send_message(phone_number, skip_msg, language, buttons)
            else:
                skip_msg = "❌ Failed to complete task."
                self.whatsapp_service.send_message(phone_number, skip_msg, language)
            
            self._clear_user_context(clean_phone)
            self._clear_user_context(phone_number)
            return True
        
        # Try to parse as inventory update
        try:
            # Remove any extra whitespace and split
            parts = message.strip().split()
            print(f"🔍 Parsing message parts: {parts}")
            
            if len(parts) == 1:
                item_index = 0
                new_quantity = parts[0]
            elif len(parts) == 2:
                item_index = int(parts[0]) - 1
                new_quantity = parts[1]
            else:
                print(f"🔍 Invalid format: expected 1 or 2 parts, got {len(parts)}")
                # Show error with format reminder
                error_msg = f"Invalid format. Please use: `new_quantity` (or specify item: `1 10`)\nExample: `10`\n\nCurrent items:\n"
                for i, item in enumerate(inventory_items, 1):
                    error_msg += f"{i}. {item['name']} (Current: {item['current_quantity']} {item.get('unit', 'piece')})\n"
                self.whatsapp_service.send_message(phone_number, error_msg, language)
                return True
                
            # Validate item index
            if item_index < 0 or item_index >= len(inventory_items):
                print(f"🔍 Invalid item index: {item_index + 1}, valid range: 1-{len(inventory_items)}")
                error_msg = f"Invalid item number. Please choose between 1 and {len(inventory_items)}"
                self.whatsapp_service.send_message(phone_number, error_msg, language)
                return True
                
            item = inventory_items[item_index]
            print(f"🔍 Updating item: {item['name']} from {item['current_quantity']} to {new_quantity}")
            
            # Update inventory quantity in database
            success = self.update_inventory_quantity(item['id'], new_quantity)
            
            if success:
                # Update the current quantity in the item for display
                item['current_quantity'] = new_quantity
                
                # Remove this item from the list
                inventory_items.pop(item_index)
                user_context['inventory_items'] = inventory_items
                # Update context with BOTH phone number formats
                self._store_user_context(clean_phone, user_context)
                self._store_user_context(phone_number, user_context)
                
                success_msg = f"✅ {item['name']} updated to {new_quantity} {item.get('unit', 'piece')}!"
                self.whatsapp_service.send_message(phone_number, success_msg, language)
                
                # Check if all items updated
                if not inventory_items:
                    print(f"✅ All inventory items updated")
                    # All inventory updated, complete the task
                    task_success = self.task_model.update_task_status(task_id, 'completed', member['id'])
                    if task_success and user_context.get('photo_filename'):
                        # Also add photo if we have one
                        self.task_model.add_completion_images_direct(task_id, user_context['photo_filename'], member['id'])
                    
                    if task_success:
                        completion_msg = "✅ All inventory updated and task marked as completed!"
                        buttons = self.whatsapp_service._create_welcome_buttons(language)
                        self.whatsapp_service.send_message(phone_number, completion_msg, language, buttons)
                    else:
                        completion_msg = "✅ Inventory updated but failed to complete task. Please contact administrator."
                        self.whatsapp_service.send_message(phone_number, completion_msg, language)
                    
                    self._clear_user_context(clean_phone)
                    self._clear_user_context(phone_number)
                else:
                    # Show remaining items
                    remaining_msg = f"✅ Item updated successfully!\n\n*Remaining items to update:*\n"
                    for i, item in enumerate(inventory_items, 1):
                        remaining_msg += f"{i}. {item['name']} (Current: {item['current_quantity']} {item.get('unit', 'piece')})\n"
                    
                    remaining_msg += f"\nSend next update: `new_quantity` (for first item)\nExample: `10`\n\nOr type 'skip' to complete without updating remaining items."
                    
                    self.whatsapp_service.send_message(phone_number, remaining_msg, language)
                
                return True
            else:
                error_msg = f"❌ Failed to update {item['name']}. Please try again."
                self.whatsapp_service.send_message(phone_number, error_msg, language)
                return True
                    
        except ValueError as e:
            print(f"❌ Error parsing inventory update (ValueError): {e}")
            error_msg = "Invalid format. Please use: `new_quantity`\nExample: `10`"
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return True
        except Exception as e:
            print(f"❌ Error parsing inventory update: {e}")
            import traceback
            traceback.print_exc()
            error_msg = "Invalid format. Please use: `new_quantity`\nExample: `10`"
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return True
        
        print(f"🔍 Not an inventory update message")
        return False

    def _handle_inventory_recovery(self, member, phone_number, message, language):
        """Handle inventory update when context was lost - try to recover from database state"""
        try:
            print(f"🔄 Attempting inventory recovery for {phone_number}")
            
            # Look for tasks that are awaiting completion with inventory update
            # Get tasks that require photo and have a photo uploaded but not completed
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Find recent task occurrences for this user that:
            # 1. Have allows_inventory_update = 1
            # 2. Are in 'pending' or 'in_progress' status  
            # 3. Have a photo proof uploaded recently
            query = """
                SELECT tocc.id as task_id, td.title, MAX(tp.created_at) as latest_proof
                FROM task_occurrences tocc
                JOIN task_definitions td ON tocc.task_definition_id = td.id
                LEFT JOIN task_proofs tp ON tp.task_occurrence_id = tocc.id
                WHERE tocc.assigned_to = %s
                AND td.allows_inventory_update = 1
                AND tocc.status IN ('pending', 'in_progress')
                AND tp.id IS NOT NULL
                GROUP BY tocc.id, td.title
                ORDER BY latest_proof DESC
                LIMIT 1
            """
            cursor.execute(query, (member['id'],))
            result = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if not result:
                print(f"🔍 No pending inventory task found for recovery")
                return False
            
            task_id = result['task_id']
            print(f"🔄 Found pending inventory task: {task_id} - {result['title']}")
            
            # Get inventory items for this task
            inventory_items = self.get_inventory_for_task(task_id)
            
            if not inventory_items:
                print(f"🔍 No inventory items for task {task_id}")
                return False
            
            # Parse the message
            parts = message.strip().split()
            if len(parts) == 1:
                item_index = 0
                new_quantity = parts[0]
            elif len(parts) == 2:
                item_index = int(parts[0]) - 1
                new_quantity = parts[1]
            else:
                return False
            
            if item_index < 0 or item_index >= len(inventory_items):
                error_msg = f"Invalid item number. Please choose between 1 and {len(inventory_items)}"
                self.whatsapp_service.send_message(phone_number, error_msg, language)
                return True
            
            item = inventory_items[item_index]
            
            # Update inventory
            success = self.update_inventory_quantity(item['id'], new_quantity)
            
            if success:
                # Store context for subsequent updates
                clean_phone = phone_number.replace('whatsapp:', '')
                inventory_items.pop(item_index)
                
                if inventory_items:
                    # More items to update
                    new_context = {
                        'pending_completion_task': task_id,
                        'completion_flow': 'inventory_only',
                        'inventory_items': inventory_items,
                        'task_needs_completion': True
                    }
                    self._store_user_context(clean_phone, new_context)
                    self._store_user_context(f"whatsapp:{clean_phone}", new_context)
                    
                    remaining_msg = f"✅ {item['name']} updated to {new_quantity} {item.get('unit', 'piece')}!\n\n*Remaining items to update:*\n"
                    for i, itm in enumerate(inventory_items, 1):
                        remaining_msg += f"{i}. {itm['name']} (Current: {itm['current_quantity']} {itm.get('unit', 'piece')})\n"
                    remaining_msg += f"\nOr type 'skip' to complete."
                    
                    self.whatsapp_service.send_message(phone_number, remaining_msg, language)
                else:
                    # All items done, complete the task
                    task_success = self.task_model.update_task_status(task_id, 'completed', member['id'])
                    
                    if task_success:
                        completion_msg = f"✅ {item['name']} updated to {new_quantity}!\n\n✅ All inventory updated and task completed!"
                        buttons = self.whatsapp_service._create_welcome_buttons(language)
                        self.whatsapp_service.send_message(phone_number, completion_msg, language, buttons)
                    else:
                        self.whatsapp_service.send_message(phone_number, f"✅ Inventory updated but failed to complete task.", language)
                    
                    self._clear_user_context(clean_phone)
                    self._clear_user_context(f"whatsapp:{clean_phone}")
                
                return True
            else:
                self.whatsapp_service.send_message(phone_number, f"❌ Failed to update inventory. Please try again.", language)
                return True
                
        except Exception as e:
            print(f"❌ Error in inventory recovery: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _store_user_context(self, phone_number, context_data):
        """Store temporary user context for button interactions"""
        # Simple in-memory storage - consider using database for production
        if not hasattr(self, '_user_contexts'):
            self._user_contexts = {}
        
        # Clean the phone number (remove whatsapp: prefix)
        clean_phone = phone_number.replace('whatsapp:', '')
        whatsapp_phone = f"whatsapp:{clean_phone}"
        
        # Store with ALL formats to ensure we can retrieve it
        self._user_contexts[clean_phone] = context_data
        self._user_contexts[whatsapp_phone] = context_data
        self._user_contexts[phone_number] = context_data  # Also store original in case it differs
        
        print(f"💾 Stored context for {clean_phone}, {whatsapp_phone}, and {phone_number}")

    def _get_user_context(self, phone_number):
        """Get user context for button interactions"""
        if hasattr(self, '_user_contexts'):
            # Try with the exact phone number first
            if phone_number in self._user_contexts:
                return self._user_contexts[phone_number]
            
            # Try with cleaned version
            clean_phone = phone_number.replace('whatsapp:', '')
            if clean_phone in self._user_contexts:
                return self._user_contexts[clean_phone]
            
            # Try with whatsapp: prefix
            whatsapp_phone = f"whatsapp:{clean_phone}"
            if whatsapp_phone in self._user_contexts:
                return self._user_contexts[whatsapp_phone]
        
        return None

    def _clear_user_context(self, phone_number):
        """Clear user context"""
        if hasattr(self, '_user_contexts'):
            # Clean the phone number
            clean_phone = phone_number.replace('whatsapp:', '')
            whatsapp_phone = f"whatsapp:{clean_phone}"
            
            # Remove ALL formats
            self._user_contexts.pop(clean_phone, None)
            self._user_contexts.pop(whatsapp_phone, None)
            self._user_contexts.pop(phone_number, None)
            
            print(f"🗑️ Cleared context for {clean_phone}")

    def handle_property_inventory_menu(self, member, phone_number, language, force_selection=False):
        """Ask user to type inventory name/details to search"""
        properties = self.get_user_properties(member['id'])
        
        if not properties:
            no_properties_msg = "You don't have any properties assigned to you yet."
            self.whatsapp_service.send_message(phone_number, no_properties_msg, language)
            return

        # Set context so next text message is treated as inventory search
        context = {
            'inventory_search': True,
            'member_client_id': member.get('client_id')
        }
        self._store_user_context(phone_number, context)

        search_msg = (
            "📦 *Inventory Management*\n\n"
            "🔍 Please type the inventory name or any details to search.\n\n"
            "For example: *Mountain* or *Towel* or *Kitchen*"
        )

        buttons = [{
            "type": "reply",
            "reply": {
                "id": "main_menu",
                "title": "🏠 Main Menu"
            }
        }]
        self.whatsapp_service.send_message(phone_number, search_msg, language, buttons)

    def handle_inventory_search(self, member, phone_number, search_term, language):
        """Search inventory by keyword and display results like tasks"""
        # Get the client_id from the member
        client_id = member.get('client_id')
        if not client_id:
            # Fetch from DB
            try:
                conn = self.get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT client_id FROM team_members WHERE id = %s", (member['id'],))
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                client_id = row['client_id'] if row else None
            except Exception as e:
                print(f"❌ Error getting client_id: {e}")
                client_id = None

        if not client_id:
            self.whatsapp_service.send_message(phone_number, "❌ Unable to search inventory.", language)
            return

        results = self.task_model.search_inventory_by_keyword(client_id, search_term)

        if not results:
            no_results_msg = (
                f"📦 No inventory items found matching *\"{search_term}\"*.\n\n"
                "🔍 Try a different keyword or check the spelling."
            )
            buttons = [
                {"type": "reply", "reply": {"id": "btn_inventory", "title": "🔍 Search Again"}},
                {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
            ]
            self.whatsapp_service.send_message(phone_number, no_results_msg, language, buttons)
            return

        total_count = len(results)

        # Show results in a task-like format, paginated (2 at a time for buttons)
        self._show_inventory_search_results(phone_number, results, language, offset=0, search_term=search_term)

    def _show_inventory_search_results(self, phone_number, results, language, offset=0, search_term=""):
        """Display inventory search results in task-like format with pagination"""
        total_count = len(results)
        current_items = results[offset:offset + 2]

        inv_msg = f"📦 *Inventory Results ({total_count})*\n"
        inv_msg += f"🔍 Search: \"{search_term}\"\n\n"

        for i, item in enumerate(current_items):
            actual_num = offset + i + 1
            inv_msg += f"*{actual_num}. {item['name']}*\n"
            inv_msg += f"   🏠 Property: {item.get('property_name', 'N/A')}\n"
            if item.get('category'):
                inv_msg += f"   📂 Category: {item['category']}\n"
            inv_msg += f"   📊 Quantity: {item['current_quantity']} {item.get('unit', '')}\n"
            if item.get('located_at'):
                inv_msg += f"   📍 Location: {item['located_at']}\n"
            inv_msg += "\n"

        inv_msg += "*Select an item to update quantity:*"

        # Build buttons (max 3 in WhatsApp)
        buttons = []
        for i, item in enumerate(current_items):
            actual_num = offset + i + 1
            item_title_short = item['name'][:12] + "..." if len(item['name']) > 12 else item['name']
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"inv_item_{item['id']}",
                    "title": f"#{actual_num}: {item_title_short}"
                }
            })

        # Third button: next page or main menu
        if offset + 2 < total_count:
            next_offset = offset + 2
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"inv_search_next_{next_offset}",
                    "title": "⏭️ Next Items"
                }
            })
        else:
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": "main_menu",
                    "title": "🏠 Main Menu"
                }
            })

        # Store results in context for pagination and item selection
        context = {
            'inventory_search_results': True,
            'search_results': results,
            'search_term': search_term,
            'current_offset': offset
        }
        self._store_user_context(phone_number, context)

        self.whatsapp_service.send_message(phone_number, inv_msg, language, buttons)

    def handle_inventory_item_selected(self, member, phone_number, item_id, language):
        """Show details of a selected inventory item and allow quantity update"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT i.id, i.name, i.category, i.quantity as current_quantity, 
                       i.unit, i.located_at, i.property_id,
                       p.name as property_name
                FROM inventory i
                JOIN properties p ON i.property_id = p.id
                WHERE i.id = %s
            """
            cursor.execute(query, (item_id,))
            item = cursor.fetchone()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"❌ Error fetching inventory item: {e}")
            self.whatsapp_service.send_message(phone_number, "❌ Error loading inventory item.", language)
            return

        if not item:
            self.whatsapp_service.send_message(phone_number, "❌ Inventory item not found.", language)
            return

        detail_msg = (
            f"📦 *Inventory Detail:*\n\n"
            f"📋 *{item['name']}*\n"
            f"🏠 Property: {item.get('property_name', 'N/A')}\n"
        )
        if item.get('category'):
            detail_msg += f"📂 Category: {item['category']}\n"
        detail_msg += f"📊 Current Quantity: {item['current_quantity']} {item.get('unit', '')}\n"
        if item.get('located_at'):
            detail_msg += f"📍 Location: {item['located_at']}\n"
        detail_msg += "\n✏️ *Type the new quantity to update:*"

        # Store context for quantity update
        context = {
            'inventory_update_item': True,
            'selected_item': {
                'id': item['id'],
                'name': item['name'],
                'current_quantity': item['current_quantity'],
                'unit': item.get('unit', ''),
                'property_id': item['property_id']
            }
        }
        self._store_user_context(phone_number, context)

        buttons = [
            {"type": "reply", "reply": {"id": "btn_inventory", "title": "🔍 Back to Search"}},
            {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
        ]
        self.whatsapp_service.send_message(phone_number, detail_msg, language, buttons)

    def handle_property_inventory_selection(self, member, phone_number, property_id, language):
        """Fetch and show inventory for a property, setting up active update context"""
        inventory_items = self.task_model.get_inventory_by_property(property_id)
        
        if not inventory_items:
            no_inv_msg = "This property has no inventory items registered."
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "btn_inv_change_prop",
                        "title": "🔄 Change Property"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "main_menu",
                        "title": "🏠 Main Menu"
                    }
                }
            ]
            self.whatsapp_service.send_message(phone_number, no_inv_msg, language, buttons)
            return
            
        # Set standalone inventory context
        context = {
            'standalone_inventory': True,
            'property_id': property_id,
            'inventory_items': inventory_items
        }
        self._store_user_context(phone_number, context)
        
        inv_msg = "📦 *Property Inventory*\n\n"
        for i, item in enumerate(inventory_items, 1):
            inv_msg += f"{i}. {item['name']} - Current: {item['current_quantity']} {item.get('unit', '')}\n"
            
        inv_msg += "\nTo update an item's quantity, reply:\n*set [number] [quantity]*\nExample: *set 1 50*"
        
        # Add a menu button to go back
        buttons = [{
            "type": "reply",
            "reply": {
                "id": "btn_inv_change_prop",
                "title": "🔄 Change Property"
            }
        }, {
            "type": "reply",
            "reply": {
                "id": "main_menu",
                "title": "🏠 Main Menu"
            }
        }]
        
        self.whatsapp_service.send_message(phone_number, inv_msg, language, buttons)

    def handle_pending_photos(self, member, phone_number, language):
        """Show tasks that are waiting for photos"""
        tasks = self.task_model.get_pending_photo_tasks(member['id'])
        
        if not tasks:
            no_pending_msg = self.whatsapp_service._get_translated_message('no_pending_photos', language) or "✅ No tasks waiting for photos!\n\nAll your completed tasks have their required photos."
            buttons = self.whatsapp_service._create_welcome_buttons(language)
            self.whatsapp_service.send_message(phone_number, no_pending_msg, language, buttons)
            return
        
        pending_header = self.whatsapp_service._get_translated_message('pending_photos_header', language) or "📸 *Tasks Waiting for Photos:*\n\n"
        message = pending_header
        
        for i, task in enumerate(tasks, 1):
            message += f"{i}. {task['title']}\n"
            message += f"   🏠 {task.get('property_name', 'N/A')}\n"
            message += f"   📅 Completed: {task.get('completed_at', 'N/A')}\n\n"
        
        send_photo_msg = self.whatsapp_service._get_translated_message('send_photo_instruction', language) or "Simply send a photo now to attach it to the most recent task!"
        message += send_photo_msg
        
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        self.whatsapp_service.send_message(phone_number, message, language, buttons)

    def handle_help(self, member, phone_number, language):
        """Show help with main menu option"""
        help_message = self.whatsapp_service._get_translated_message('help_full', language) or (
            f"Hello {member['name']}! I'm your team management assistant.\n\n"
            "Available commands:\n"
            "• *tasks* - List your assigned tasks\n"
            "• *status [task-number] [status]* - Update task status\n"
            "• *pending photos* - View tasks waiting for photos\n"
            "• *recurring* - View your recurring tasks\n"
            "• *settings* - Configure your preferences\n"
            "• Send image to attach to completed task\n\n"
            "Examples:\n"
            "*status 1 completed* - Mark task 1 as completed\n"
            "*tasks* - View all your tasks\n"
            "*pending photos* - See tasks needing photos\n"
            "*recurring* - View recurring tasks\n\n"
            "📸 *Note:* Some tasks require photos before completion. "
            "Just send the photo and I'll handle the rest!"
        )
        
        # Add main menu button
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": "main_menu",  # Changed from "help_main_menu" to "main_menu"
                    "title": "🏠 Main Menu"
                }
            }
        ]
        
        self.whatsapp_service.send_message(phone_number, help_message, language, buttons)

    def handle_unknown_command(self, member, phone_number, language):
        unknown_msg = self.whatsapp_service._get_translated_message('unknown_command', language) or "I didn't understand that command."
        
        # Provide helpful buttons
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        self.whatsapp_service.send_message(phone_number, unknown_msg, language, buttons)

    # ═══════════════════════════════════════════════════════════════
    # Direct Search (#hashtag) & Slash Commands (/commands)
    # ═══════════════════════════════════════════════════════════════

    def _handle_search_command(self, member, phone_number, raw_msg, language):
        """
        Parse and route # search commands.
        
        Supported formats:
          # keyword        → search all
          #task keyword    → search tasks
          #inv keyword     → search inventory  
          #property keyword→ search properties
        """
        # Remove the leading '#'
        content = raw_msg[1:].strip()

        if not content:
            # Just "#" with nothing else — show search help
            self._show_search_help(member, phone_number, language)
            return

        # Determine search scope
        scope = 'all'
        search_term = content

        scope_prefixes = {
            'task ':     'task',
            't ':        'task',
            'inv ':      'inventory',
            'i ':        'inventory',
            'property ': 'property',
            'p ':        'property',
        }

        content_lower = content.lower()
        for prefix, scope_name in scope_prefixes.items():
            if content_lower.startswith(prefix):
                scope = scope_name
                search_term = content[len(prefix):].strip()
                break

        if not search_term:
            self._show_search_help(member, phone_number, language)
            return

        # Multilingual support: translate search term to English if user language is not English
        if language != 'en':
            try:
                translated = self.language_service.translate_text(search_term, 'en')
                if translated:
                    print(f"🌐 Translated search term: '{search_term}' → '{translated}'")
                    search_term = translated.strip()
            except Exception as e:
                print(f"⚠️ Search term translation failed: {e}")

        print(f"🔍 Direct search: scope={scope}, term='{search_term}'")

        if scope == 'task':
            self._search_tasks(member, phone_number, search_term, language)
        elif scope == 'inventory':
            # Reuse existing inventory search — skip the menu prompt
            self.handle_inventory_search(member, phone_number, search_term, language)
            # Save search history
            client_id = member.get('client_id')
            results = self.task_model.search_inventory_by_keyword(client_id, search_term) if client_id else []
            self.task_model.save_search_history(member['id'], search_term, 'inventory', len(results))
        elif scope == 'property':
            self._search_properties(member, phone_number, search_term, language)
        elif scope == 'all':
            self._search_all(member, phone_number, search_term, language)

    def _search_tasks(self, member, phone_number, search_term, language):
        """Search tasks and display results."""
        results = self.task_model.search_tasks_by_keyword(member['id'], search_term)

        # Save search history
        self.task_model.save_search_history(member['id'], search_term, 'task', len(results))

        if not results:
            no_results = (
                f"📋 No tasks found matching *\"{search_term}\"*.\n\n"
                "🔍 Try a different keyword."
            )
            buttons = [
                {"type": "reply", "reply": {"id": "btn_tasks", "title": "📋 All Tasks"}},
                {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
            ]
            self.whatsapp_service.send_message(phone_number, no_results, language, buttons)
            return

        # Reuse existing task list formatting (paginated, 2 at a time)
        total = len(results)
        current = results[:2]

        task_list = self.whatsapp_service.format_task_list(
            current, language, total_count=total, start_index=1
        )
        message = f"🔍 *Search: \"{search_term}\"*\n\n{task_list}\n*Select a task to update:*"

        buttons = []
        for i, task in enumerate(current):
            title_short = task['title'][:12] + "..." if len(task['title']) > 12 else task['title']
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"task_{task['id']}",
                    "title": f"#{i+1}: {title_short}"
                }
            })

        # Third button: next or main menu
        if total > 2:
            buttons.append({
                "type": "reply",
                "reply": {"id": "btn_tasks", "title": "📋 View All Tasks"}
            })
        else:
            buttons.append({
                "type": "reply",
                "reply": {"id": "main_menu", "title": "🏠 Main Menu"}
            })

        self.whatsapp_service.send_message(phone_number, message, language, buttons[:3])

    def _search_properties(self, member, phone_number, search_term, language):
        """Search properties and display results."""
        client_id = member.get('client_id')
        if not client_id:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT client_id FROM team_members WHERE id = %s", (member['id'],))
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                client_id = row['client_id'] if row else None
            except Exception:
                client_id = None

        if not client_id:
            self.whatsapp_service.send_message(phone_number, "❌ Unable to search properties.", language)
            return

        results = self.task_model.search_properties_by_keyword(client_id, search_term)

        # Save search history
        self.task_model.save_search_history(member['id'], search_term, 'property', len(results))

        if not results:
            no_results = (
                f"🏠 No properties found matching *\"{search_term}\"*.\n\n"
                "🔍 Try a different keyword."
            )
            buttons = [
                {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
            ]
            self.whatsapp_service.send_message(phone_number, no_results, language, buttons)
            return

        msg = f"🔍 *Properties matching \"{search_term}\"* ({len(results)}):\n\n"
        for i, prop in enumerate(results, 1):
            msg += f"*{i}. {prop['name']}*\n"
            if prop.get('address'):
                msg += f"   📍 {prop['address'][:50]}\n"
            msg += f"   📋 Tasks: {prop['total_tasks']}  |  📦 Inventory: {prop['total_inventory']}\n\n"

        msg += "*Select a property to switch to:*"

        # Show up to 2 properties as buttons + Main Menu
        buttons = []
        for i, prop in enumerate(results[:2]):
            name_short = prop['name'][:15] + "..." if len(prop['name']) > 15 else prop['name']
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"property_{prop['id']}",
                    "title": f"🏠 {name_short}"
                }
            })
        buttons.append({
            "type": "reply",
            "reply": {"id": "main_menu", "title": "🏠 Main Menu"}
        })

        self.whatsapp_service.send_message(phone_number, msg, language, buttons[:3])

    def _search_all(self, member, phone_number, search_term, language):
        """Search across tasks, inventory, and properties. Show combined results."""
        client_id = member.get('client_id')
        if not client_id:
            try:
                conn = self.get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT client_id FROM team_members WHERE id = %s", (member['id'],))
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                client_id = row['client_id'] if row else None
            except Exception:
                client_id = None

        # Run all three searches
        tasks = self.task_model.search_tasks_by_keyword(member['id'], search_term) or []
        inventory = self.task_model.search_inventory_by_keyword(client_id, search_term) if client_id else []
        properties = self.task_model.search_properties_by_keyword(client_id, search_term) if client_id else []

        total = len(tasks) + len(inventory) + len(properties)

        # Save search history
        self.task_model.save_search_history(member['id'], search_term, 'all', total)

        if total == 0:
            no_results = (
                f"🔍 No results found for *\"{search_term}\"*\n\n"
                "Try refining your search:\n"
                "• `#task keyword` — search tasks\n"
                "• `#inv keyword` — search inventory\n"
                "• `#property keyword` — search properties"
            )
            buttons = [
                {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
            ]
            self.whatsapp_service.send_message(phone_number, no_results, language, buttons)
            return

        msg = f"🔍 *Search Results for \"{search_term}\"*\n"
        msg += f"Found {total} result(s)\n\n"

        # Tasks section (show top 3)
        if tasks:
            msg += f"📋 *Tasks ({len(tasks)})*\n"
            for i, task in enumerate(tasks[:3], 1):
                status_emoji = self.whatsapp_service.get_status_emoji(task['status'])
                msg += f"  {i}. {task['title']} {status_emoji}\n"
                if task.get('property_name'):
                    msg += f"     🏠 {task['property_name']}\n"
            if len(tasks) > 3:
                msg += f"  _...and {len(tasks) - 3} more_\n"
            msg += "\n"

        # Inventory section (show top 3)
        if inventory:
            msg += f"📦 *Inventory ({len(inventory)})*\n"
            for i, item in enumerate(inventory[:3], 1):
                msg += f"  {i}. {item['name']} — {item['current_quantity']} {item.get('unit', '')}\n"
                msg += f"     🏠 {item.get('property_name', 'N/A')}\n"
            if len(inventory) > 3:
                msg += f"  _...and {len(inventory) - 3} more_\n"
            msg += "\n"

        # Properties section (show top 3)
        if properties:
            msg += f"🏠 *Properties ({len(properties)})*\n"
            for i, prop in enumerate(properties[:3], 1):
                msg += f"  {i}. {prop['name']}\n"
                if prop.get('address'):
                    addr = prop['address'][:40] + "..." if len(prop['address']) > 40 else prop['address']
                    msg += f"     📍 {addr}\n"
            if len(properties) > 3:
                msg += f"  _...and {len(properties) - 3} more_\n"
            msg += "\n"

        msg += "_Refine with: `#task`, `#inv`, or `#property`_"

        # Buttons: prioritize by which module has results
        buttons = []
        if tasks:
            buttons.append({"type": "reply", "reply": {"id": "btn_tasks", "title": "📋 View Tasks"}})
        if inventory:
            buttons.append({"type": "reply", "reply": {"id": "btn_inventory", "title": "📦 Inventory"}})
        if not buttons:
            buttons.append({"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}})
        # Always add Main Menu as last button (max 3)
        if len(buttons) < 3:
            buttons.append({"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}})

        self.whatsapp_service.send_message(phone_number, msg, language, buttons[:3])

    def _handle_slash_command(self, member, phone_number, raw_msg, language):
        """
        Parse and route / slash commands.
        
        Supported:
          /client <name>    → switch client
          /property <id>    → switch property
          /help             → show command help
        """
        content = raw_msg[1:].strip()

        if not content or content.lower() == 'help':
            self._show_search_help(member, phone_number, language)
            return

        content_lower = content.lower()

        if content_lower.startswith('client '):
            client_search = content[7:].strip()
            if client_search:
                self._switch_client(member, phone_number, client_search, language)
            else:
                self.show_client_selection_menu(member, phone_number, language)
        elif content_lower.startswith('property '):
            property_search = content[9:].strip()
            if property_search:
                self._switch_property(member, phone_number, property_search, language)
            else:
                self.show_property_selection_menu(member, phone_number, language)
        else:
            self._show_search_help(member, phone_number, language)

    def _switch_client(self, member, phone_number, search_term, language):
        """Find and switch to a client by name (only team member's clients)."""
        try:
            clients = self.task_model.search_clients_by_keyword(search_term, phone_number)

            if not clients:
                msg = f"❌ No client found matching *\"{search_term}\"*"
                buttons = [
                    {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
                ]
                self.whatsapp_service.send_message(phone_number, msg, language, buttons)
                return

            if len(clients) == 1:
                # Exact match — switch immediately
                self._do_client_switch(member, phone_number, clients[0], language)
            else:
                # Multiple matches — show selection list
                msg = f"🔍 *Clients matching \"{search_term}\"*:\n\nPlease select a client:"

                sections = [{
                    "title": "Select Client",
                    "rows": []
                }]
                for client in clients:
                    sections[0]["rows"].append({
                        "id": f"switch_client_{client['id']}",
                        "title": client['name'][:24],
                        "description": f"Client ID: {client['id']}"
                    })

                # Add back option
                sections.append({
                    "title": "Navigation",
                    "rows": [{
                        "id": "back_main",
                        "title": "⬅️ Main Menu",
                        "description": "Return to the main menu"
                    }]
                })

                success = self.whatsapp_service.send_interactive_list(
                    phone_number, msg, "Select Client", sections, language
                )

                if not success:
                    # Fallback to buttons (max 3)
                    buttons = []
                    for client in clients[:2]:
                        buttons.append({
                            "type": "reply",
                            "reply": {
                                "id": f"switch_client_{client['id']}",
                                "title": f"🏢 {client['name'][:16]}"
                            }
                        })
                    buttons.append({
                        "type": "reply",
                        "reply": {"id": "main_menu", "title": "🏠 Main Menu"}
                    })
                    self.whatsapp_service.send_message(phone_number, msg, language, buttons[:3])

        except Exception as e:
            print(f"❌ Error searching clients: {e}")
            import traceback
            traceback.print_exc()
            self.whatsapp_service.send_message(phone_number, "❌ Error searching clients.", language)

    def _do_client_switch(self, member, phone_number, client, language):
        """Switch the active client for a team member (in-memory preference)."""
        try:
            clean_phone = phone_number.replace('whatsapp:', '')

            # Verify the team_members record exists for this phone + client
            target_member = self.team_member_model.find_by_phone_and_client(clean_phone, client['id'])

            if not target_member:
                self.whatsapp_service.send_message(
                    phone_number,
                    f"❌ You don't have access to client *{client['name']}*.\n"
                    "Contact your administrator to be added.",
                    language
                )
                return

            # Store the active client preference (keyed by clean phone)
            self.user_active_client[clean_phone] = client['id']

            # Clear any cached property selections since client changed
            self.user_property_selections.pop(clean_phone, None)
            self.user_property_selections.pop(phone_number, None)

            # Clear user context to prevent stale state
            self._clear_user_context(phone_number)
            self._clear_user_context(clean_phone)

            confirmation = (
                f"✅ *Client Switched*\n\n"
                f"You are now working with: *{client['name']}*\n\n"
                f"Your tasks and inventory will now show data for this client."
            )

            buttons = [
                {"type": "reply", "reply": {"id": "btn_tasks", "title": "📋 View Tasks"}},
                {"type": "reply", "reply": {"id": "btn_inventory", "title": "📦 Inventory"}},
                {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
            ]

            self.whatsapp_service.send_message(phone_number, confirmation, language, buttons)

            print(f"✅ Client switched to '{client['name']}' (ID: {client['id']}) for phone {clean_phone}")

        except Exception as e:
            print(f"❌ Error switching client: {e}")
            import traceback
            traceback.print_exc()
            self.whatsapp_service.send_message(phone_number, "❌ Failed to switch client. Please try again.", language)

    def _switch_property(self, member, phone_number, search_term, language):
        """Find and switch to a property by ID or name."""
        properties = self.get_user_properties(member['id'])

        matched = []
        for prop in properties:
            # Match by ID (e.g., /property 208)
            if str(prop['id']) == search_term:
                matched = [prop]
                break
            # Match by name substring (e.g., /property mountain)
            if search_term.lower() in prop['name'].lower():
                matched.append(prop)

        if not matched:
            msg = f"❌ No property found matching *\"{search_term}\"*"
            buttons = [
                {"type": "reply", "reply": {"id": "property_change", "title": "🏠 All Properties"}},
                {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
            ]
            self.whatsapp_service.send_message(phone_number, msg, language, buttons)
            return

        if len(matched) == 1:
            # Single match — switch immediately
            prop = matched[0]
            self.handle_property_selection_result(phone_number, str(prop['id']), prop['name'])
        else:
            # Multiple matches — show selection
            msg = f"🔍 *Properties matching \"{search_term}\"*:\n\n"
            for i, prop in enumerate(matched, 1):
                msg += f"{i}. {prop['name']}\n"
                if prop.get('address'):
                    addr = prop['address'][:50] + "..." if len(prop['address']) > 50 else prop['address']
                    msg += f"   📍 {addr}\n"

            msg += "\n*Select a property:*"

            buttons = []
            for prop in matched[:2]:
                name_short = prop['name'][:15] + "..." if len(prop['name']) > 15 else prop['name']
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"property_{prop['id']}",
                        "title": f"🏠 {name_short}"
                    }
                })
            buttons.append({
                "type": "reply",
                "reply": {"id": "main_menu", "title": "🏠 Main Menu"}
            })
            self.whatsapp_service.send_message(phone_number, msg, language, buttons[:3])

    def show_client_selection_menu(self, member, phone_number, language):
        """Show only the clients where this team member has an active record."""
        try:
            # Only show clients associated with this team member's phone
            clients = self.task_model.get_clients_for_phone(phone_number)

            if not clients:
                self.whatsapp_service.send_message(
                    phone_number, "❌ No clients found in the system.", language
                )
                return

            # Highlight current client
            current_client_id = member.get('client_id')

            msg = "🏢 *Select a Client*\n\nPlease choose a client to work with:"

            sections = [{
                "title": "Available Clients",
                "rows": []
            }]

            for client in clients[:9]:  # Max 9 + 1 back = 10 rows
                is_current = " ✓" if client['id'] == current_client_id else ""
                sections[0]["rows"].append({
                    "id": f"switch_client_{client['id']}",
                    "title": (client['name'][:22] + is_current)[:24],
                    "description": "Currently selected" if client['id'] == current_client_id else f"Switch to {client['name'][:50]}"
                })

            # Add back button
            sections.append({
                "title": "Navigation",
                "rows": [{
                    "id": "back_settings",
                    "title": "⬅️ Back to Settings",
                    "description": "Return to settings menu"
                }]
            })

            success = self.whatsapp_service.send_interactive_list(
                phone_number, msg, "Select Client", sections, language
            )

            if not success:
                # Fallback to buttons
                buttons = []
                for client in clients[:2]:
                    buttons.append({
                        "type": "reply",
                        "reply": {
                            "id": f"switch_client_{client['id']}",
                            "title": f"🏢 {client['name'][:16]}"
                        }
                    })
                buttons.append({
                    "type": "reply",
                    "reply": {"id": "back_settings", "title": "⬅️ Back"}
                })
                self.whatsapp_service.send_message(phone_number, msg, language, buttons[:3])

        except Exception as e:
            print(f"❌ Error showing client selection: {e}")
            import traceback
            traceback.print_exc()
            self.whatsapp_service.send_message(phone_number, "❌ Error loading clients.", language)

    def _show_search_help(self, member, phone_number, language):
        """Show help card for search and slash commands."""
        help_msg = (
            "🔍 *Quick Search & Commands*\n\n"
            "*Search Commands:*\n"
            "• `# keyword` — Search everything\n"
            "• `#task keyword` — Search tasks\n"
            "• `#inv keyword` — Search inventory\n"
            "• `#property keyword` — Search properties\n\n"
            "*Quick Commands:*\n"
            "• `/client name` — Switch client\n"
            "• `/property id` — Switch property\n"
            "• `/help` — Show this help\n\n"
            "*Examples:*\n"
            "• `#inv towel`\n"
            "• `#task cleaning`\n"
            "• `# mountain`\n"
            "• `/property 208`\n"
            "• `/client abc`"
        )

        # Check if user has recent searches
        try:
            recent = self.task_model.get_recent_searches(member['id'], 3)
            if recent:
                help_msg += "\n\n📜 *Recent Searches:*\n"
                for search in recent:
                    scope_emoji = {'task': '📋', 'inventory': '📦', 'property': '🏠', 'all': '🔍'}.get(search['search_scope'], '🔍')
                    help_msg += f"• {scope_emoji} `#{search['search_scope'][:3]} {search['search_term']}` ({search['result_count']} results)\n"
        except Exception:
            pass

        buttons = self.whatsapp_service._create_welcome_buttons(language)
        self.whatsapp_service.send_message(phone_number, help_msg, language, buttons)


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
    
    def handle_language_change(self, member, phone_number, language):
        """Handle language change request and save to DB"""
        message = "🌐 *Language Settings*\n\nSearch and select your preferred language:"
        
        # WhatsApp allows max 10 rows total across all sections
        # Prioritize most relevant languages (9 languages + 1 back = 10 rows)
        languages = [
            {"id": "lang_en", "title": "English", "description": "Switch to English"},
            {"id": "lang_hi", "title": "Hindi", "description": "हिंदी में बदलें"},
            {"id": "lang_es", "title": "Spanish", "description": "Cambiar a Español"},
            {"id": "lang_fr", "title": "French", "description": "Passer au Français"},
            {"id": "lang_bn", "title": "Bengali", "description": "বাংলায় পরিবর্তন করুন"},
            {"id": "lang_mr", "title": "Marathi", "description": "मराठीत बदला"},
            {"id": "lang_ta", "title": "Tamil", "description": "தமிழுக்கு மாற்று"},
            {"id": "lang_te", "title": "Telugu", "description": "తెలుగులోకి మార్చు"},
            {"id": "lang_gu", "title": "Gujarati", "description": "ગુજરાતીમાં બદલો"},
        ]
        
        sections = [
            {
                "title": "Languages",
                "rows": languages
            },
            {
                "title": "Navigation",
                "rows": [
                    {
                        "id": "back_settings",
                        "title": "⬅️ Back to Settings",
                        "description": "Return to settings menu"
                    }
                ]
            }
        ]
        
        success = self.whatsapp_service.send_interactive_list(
            phone_number, 
            message, 
            "Search Language", 
            sections,
            language
        )
        
        if not success:
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "lang_en_btn",
                        "title": "English"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "lang_hi_btn",
                        "title": "Hindi"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "back_settings",
                        "title": "⬅️ Back"
                    }
                }
            ]
            self.whatsapp_service.send_message(phone_number, message, language, buttons)


    def get_inventory_for_task(self, task_occurrence_id):
        """Get inventory items linked to a task occurrence"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            query = """
                SELECT 
                    i.id,
                    i.name,
                    i.category,
                    i.quantity as current_quantity,
                    i.unit,
                    i.located_at,
                    til.task_occurrence_id
                FROM inventory i
                JOIN task_inventory_links til ON i.id = til.inventory_id
                WHERE til.task_occurrence_id = %s
            """
            cursor.execute(query, (task_occurrence_id,))
            inventory_items = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            print(f"📦 Found {len(inventory_items)} inventory items for task {task_occurrence_id}")
            for item in inventory_items:
                print(f"  - {item['name']}: {item['current_quantity']} {item.get('unit', 'units')}")
            
            return inventory_items
            
        except Exception as e:
            print(f"❌ Error getting inventory for task: {e}")
            import traceback
            traceback.print_exc()
            return []

    def handle_standalone_inventory_update(self, member, phone_number, message, language, user_context):
        """Handle ad-hoc updates to inventory from the standalone menu flow."""
        message_lower = message.strip().lower()
        
        # Check if user wants to exit
        if message_lower in ['exit', 'quit', 'cancel', 'main menu', 'menu']:
            self._clear_user_context(phone_number)
            self._clear_user_context(phone_number.replace('whatsapp:', ''))
            self.show_main_menu(member, phone_number, language)
            return True
            
        inventory_items = user_context.get('inventory_items', [])
        
        if not message_lower.startswith('set '):
            err_msg = "❌ Invalid format. Please reply with *set [number] [quantity]*.\nExample: *set 1 50*\nOr reply *exit* to leave."
            self.whatsapp_service.send_message(phone_number, err_msg, language)
            return True
            
        parts = message_lower.split()
        if len(parts) != 3:
            err_msg = "❌ Invalid format. Please reply with *set [number] [quantity]*.\nExample: *set 1 50*"
            self.whatsapp_service.send_message(phone_number, err_msg, language)
            return True
            
        try:
            item_num = int(parts[1])
            new_qty = str(parts[2])  
            
            if item_num < 1 or item_num > len(inventory_items):
                err_msg = f"❌ Invalid item number. Please choose a number between 1 and {len(inventory_items)}."
                self.whatsapp_service.send_message(phone_number, err_msg, language)
                return True
                
            selected_item = inventory_items[item_num - 1]
            old_qty = selected_item.get('current_quantity', '0')
            
            # Update the inventory
            success = self.update_inventory_quantity(selected_item['id'], new_qty)
            
            if success:
                # Log to task_activity_log using NULL as task_occurrence_id
                self.task_model._log_task_activity(
                    None, 
                    'standalone_inventory_updated', 
                    f"Item: {selected_item['name']}, Qty: {old_qty}", 
                    f"Item: {selected_item['name']}, Qty: {new_qty}", 
                    member['id']
                )
                
                # Re-fetch inventory items
                updated_items = self.task_model.get_inventory_by_property(user_context['property_id'])
                user_context['inventory_items'] = updated_items
                self._store_user_context(phone_number, user_context)
                
                success_msg = f"✅ Updated *{selected_item['name']}* to {new_qty} {selected_item.get('unit', '')}\n\n"
                success_msg += "📦 *Property Inventory*\n\n"
                for i, item in enumerate(updated_items, 1):
                    success_msg += f"{i}. {item['name']} - Current: {item['current_quantity']} {item.get('unit', '')}\n"
                
                success_msg += "\nTo update another item, reply:\n*set [number] [quantity]*\nOr reply *exit* to leave."
                
                buttons = [
                    {"type": "reply", "reply": {"id": "btn_inventory", "title": "⬅️ Properties"}},
                    {"type": "reply", "reply": {"id": "main_menu", "title": "🏠 Main Menu"}}
                ]
                self.whatsapp_service.send_message(phone_number, success_msg, language, buttons)
            else:
                self.whatsapp_service.send_message(phone_number, "❌ Failed to update inventory. Please enter a valid quantity.", language)
                
        except ValueError:
            self.whatsapp_service.send_message(phone_number, "❌ Please enter valid numbers.", language)
            
        return True
        

    def handle_inventory_update(self, member, phone_number, message, language):
        """Handle inventory quantity updates from text messages"""
        user_context = self._get_user_context(phone_number)
        
        if not user_context or 'completion_flow' not in user_context:
            return False
        
        task_id = user_context.get('pending_completion_task')
        inventory_items = user_context.get('inventory_items', [])
        
        if not task_id or not inventory_items:
            return False
        
        # Parse message like "1 10" or "2 5"
        try:
            parts = message.strip().split()
            if len(parts) != 2:
                return False
                
            item_index = int(parts[0]) - 1
            new_quantity = parts[1]
            
            if 0 <= item_index < len(inventory_items):
                item = inventory_items[item_index]
                # Update inventory quantity in database
                success = self.update_inventory_quantity(item['id'], new_quantity)
                
                if success:
                    # Remove this item from the list
                    inventory_items.pop(item_index)
                    user_context['inventory_items'] = inventory_items
                    self._store_user_context(phone_number, user_context)
                    
                    # Check if all items updated
                    if not inventory_items:
                        # All inventory updated, complete the task
                        self.task_model.update_task_status(task_id, 'completed', member['id'])
                        completion_msg = "✅ All inventory updated and task marked as completed!"
                        self.whatsapp_service.send_message(phone_number, completion_msg, language)
                        self._clear_user_context(phone_number)
                    else:
                        # Show remaining items
                        remaining_msg = f"✅ Item updated!\n\nRemaining items to update:\n"
                        for i, item in enumerate(inventory_items, 1):
                            remaining_msg += f"{i}. {item['name']}\n"
                        
                        self.whatsapp_service.send_message(phone_number, remaining_msg, language)
                    
                    return True
                    
        except (ValueError, IndexError):
            return False
        
        return False 

    def handle_skip_inventory(self, member, phone_number, task_id, language):
        """Handle skip inventory button - complete task without inventory updates"""
        try:
            clean_phone = phone_number.replace('whatsapp:', '')
            
            # Get the user context to retrieve photo filename if any
            user_context = self._get_user_context(clean_phone)
            if not user_context:
                user_context = self._get_user_context(phone_number)
            
            # Complete the task
            success = self.task_model.update_task_status(task_id, 'completed', member['id'])
            
            # If we have a photo filename from the context, attach it
            if success and user_context and user_context.get('photo_filename'):
                self.task_model.add_completion_images_direct(task_id, user_context['photo_filename'], member['id'])
            
            # Clear the context
            self._clear_user_context(clean_phone)
            self._clear_user_context(phone_number)
            
            if success:
                completion_msg = (
                    f"✅ *Task Completed!*\n\n"
                    f"Inventory update was skipped.\n"
                    f"Task has been marked as completed."
                )
                buttons = self.whatsapp_service._create_welcome_buttons(language)
                self.whatsapp_service.send_message(phone_number, completion_msg, language, buttons)
            else:
                error_msg = "❌ Failed to complete task. Please try again."
                self.whatsapp_service.send_message(phone_number, error_msg, language)
                
        except Exception as e:
            print(f"❌ Error handling skip inventory: {e}")
            import traceback
            traceback.print_exc()
            error_msg = "❌ An error occurred. Please try again."
            self.whatsapp_service.send_message(phone_number, error_msg, language)

    def update_inventory_quantity(self, inventory_id, new_quantity):
        """Update inventory quantity in database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # First, validate the new quantity
            try:
                # Try to parse as float for decimal values
                quantity_value = float(new_quantity)
            except ValueError:
                # Try to parse as integer
                try:
                    quantity_value = int(new_quantity)
                except ValueError:
                    print(f"❌ Invalid quantity value: {new_quantity}")
                    return False
            
            query = "UPDATE inventory SET quantity = %s WHERE id = %s"
            cursor.execute(query, (quantity_value, inventory_id))
            
            rows_affected = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"✅ Updated inventory ID {inventory_id} to quantity {quantity_value}")
            return rows_affected > 0
            
        except Exception as e:
            print(f"❌ Error updating inventory: {e}")
            import traceback
            traceback.print_exc()
            return False