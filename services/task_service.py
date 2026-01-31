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


        # Check database structure on initialization
        print("🔍 Checking database structure...")
        self.check_database_structure()

    def get_connection(self):
        """Get database connection"""
        return self.task_model.get_connection()    

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
        
        # Get user language
        user_language = self._get_user_language(clean_phone, message)
        
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
            '📷 Photos': lambda: self.handle_pending_photos(member, clean_phone, user_language),
            '⚙️ Settings': lambda: self.show_settings_menu(member, clean_phone, user_language),
            '❓ Help': lambda: self.handle_help(member, clean_phone, user_language),
            
            # Task list buttons
            'Main Menu': lambda: self.show_main_menu(member, clean_phone, user_language),
            '🏠 Main Menu': lambda: self.show_main_menu(member, clean_phone, user_language),
            
            # Property buttons (ADD THESE)
            'Select Property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            '🏠 Select Property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
            '🔄 Change Property': lambda: self.show_property_selection_menu(member, clean_phone, user_language),
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
        
        # Check if message matches any button title
        if message in button_mappings:
            print(f"✅ Button matched by title: {message}")
            button_mappings[message]()
            return
        
        # Check for button IDs (from interactive buttons)
        button_id_mappings = {
            # Main menu button IDs
            'btn_tasks': lambda: self.handle_list_tasks(member, clean_phone, user_language),
            'btn_photos': lambda: self.handle_pending_photos(member, clean_phone, user_language),
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
        
        # Check if message is a button ID
        if message in button_id_mappings:
            print(f"✅ Button matched by ID: {message}")
            button_id_mappings[message]()
            return
        
        # Check for task button IDs (like "task_123")
        if message.startswith('task_'):
            task_id = message.replace('task_', '')
            self.show_task_options(member, clean_phone, task_id, user_language)
            return
        
        # Check for status button IDs (like "status_pending_123")
        if message.startswith('status_'):
            parts = message.split('_')
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
        if message.startswith('back_task_'):
            task_id = message.replace('back_task_', '')
            self.show_task_options(member, clean_phone, task_id, user_language)
            return
        
        # Check for mark_complete button IDs (like "mark_complete_123")
        if message.startswith('mark_complete_'):
            task_id = message.replace('mark_complete_', '')
            self.mark_task_complete(member, clean_phone, task_id, user_language)
            return

        # Check for update_status button IDs (like "update_status_123") 
        if message.startswith('update_status_'):
            task_id = message.replace('update_status_', '')
            # Store the task_id in user context
            self._store_user_context(clean_phone, {'current_task_id': task_id})
            self.show_status_options(member, clean_phone, task_id, user_language)
            return

        # Check for back_to_tasks button
        if message == 'back_to_tasks':
            self.handle_list_tasks(member, clean_phone, user_language)
            return
        
        # For text commands (lowercase processing)
        message_text = message.strip().lower()
        
        if message_text in ['hi', 'hello', 'hii', 'hey', 'नमस्ते', 'hola', 'bonjour']:
            self.show_main_menu(member, clean_phone, user_language)
        elif message_text in ['tasks', 'my tasks', 'task', '📋 tasks']:
            self.handle_list_tasks(member, clean_phone, user_language)
        elif message_text.startswith('status '):
            self.handle_update_status(member, clean_phone, message_text, user_language)
        elif message_text in ['pending photos', 'pending', 'photos', '📷 photos']:
            self.handle_pending_photos(member, clean_phone, user_language)
        elif message_text in ['settings', 'setting', '⚙️ settings']:
            self.show_settings_menu(member, clean_phone, user_language)
        elif message_text in ['help', '❓ help']:
            self.handle_help(member, clean_phone, user_language)
        elif message_text in ['recurring', 'recurring tasks', '🔄 recurring']:
            self.handle_recurring_tasks(member, clean_phone, user_language)
        elif message_text in ['main menu', 'menu', 'home']:  # Added these
            self.show_main_menu(member, clean_phone, user_language)
        elif message_text in ['select property', 'change property', 'property']:  # ADDED THESE
            self.show_property_selection_menu(member, clean_phone, user_language)
        elif media_url:
            self.handle_image_upload(member, clean_phone, media_url, user_language)
        else:
            self.handle_unknown_command(member, clean_phone, user_language)

    def show_main_menu(self, member, phone_number, language):
        """Show the main menu with interactive buttons"""
        welcome_msg = self.whatsapp_service._get_translated_message('welcome', language)
        welcome_message = f"{welcome_msg.format(member['name'])} 👋\n\nI'm your team management assistant. Please select an option:"
        
        # Create properly formatted interactive buttons
        buttons = self.whatsapp_service._create_welcome_buttons(language)
        
        # Send with buttons
        success = self.whatsapp_service.send_message(phone_number, welcome_message, language, buttons)
        
        if not success:
            # If buttons fail, show simple text menu
            text_menu = f"{welcome_message}\n\nReply with:\n1. Tasks\n2. Photos\n3. Settings\n4. Help\n5. Recurring"
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
        sections = [
            {
                "title": "Available Properties",
                "rows": []
            }
        ]
        
        for prop in properties:
            # Format address (truncate if too long)
            address = prop.get('address', '')
            if address and len(address) > 50:
                address = address[:47] + "..."
            
            sections[0]['rows'].append({
                "id": f"property_{prop['id']}",  # Use actual database ID
                "title": f"🏠 {prop['name']}",
                "description": address or "No address"
            })
        
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
            # Fallback to buttons
            buttons = []
            for i, prop in enumerate(properties[:3], 1):
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"prop_{prop['id']}",
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
        """Handle 'Mark Complete' button click"""
        user_context = self._get_user_context(phone_number)
        
        if user_context and 'current_task_id' in user_context:
            task_id = user_context['current_task_id']
            self.mark_task_complete(member, phone_number, task_id, language)
        else:
            # Try to find the most recent pending task
            tasks = self.task_model.get_tasks_by_user(member['id'])
            pending_tasks = [t for t in tasks if t['status'] == 'pending']
            
            if pending_tasks:
                task = pending_tasks[0]
                self._store_user_context(phone_number, {'current_task_id': task['id']})
                self.mark_task_complete(member, phone_number, task['id'], language)
            else:
                error_msg = "No tasks found to mark as complete. Please select a task first."
                self.whatsapp_service.send_message(phone_number, error_msg, language)

    def handle_update_status_button(self, member, phone_number, language):
        """Handle 'Update Status' button click"""
        print(f"🔍 DEBUG: handle_update_status_button called for {phone_number}")
        print(f"🔍 DEBUG: Checking user context...")
        
        user_context = self._get_user_context(phone_number)
        print(f"🔍 DEBUG: User context: {user_context}")
        
        if user_context and 'current_task_id' in user_context:
            task_id = user_context['current_task_id']
            print(f"🔍 DEBUG: Found current_task_id: {task_id}")
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
                self._store_user_context(phone_number, {'current_task_id': task_id})
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
            
            if 'notification_preferences' in preferences:
                updates.append("notification_preferences = %s")
                values.append(json.dumps(preferences['notification_preferences']))
            
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
                AND COLUMN_NAME IN ('preferred_language', 'last_selected_property_id', 'notification_preferences', 'settings_updated_at')
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
                    notification_preferences,
                    settings_updated_at
                FROM team_members 
                WHERE id = %s
            """
            cursor.execute(query, (member['id'],))
            preferences = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            # Parse JSON if exists
            if preferences and preferences.get('notification_preferences'):
                try:
                    preferences['notification_preferences'] = json.loads(preferences['notification_preferences'])
                except:
                    preferences['notification_preferences'] = {}
            
            return preferences
            
        except Exception as e:
            print(f"Error getting user preferences: {e}")
            return None
    
    def _get_user_language(self, phone_number, message):
        """Get user's language preference, check DB first, then detect from message"""
        # Check database first
        preferences = self.get_user_preferences(phone_number)
        if preferences and preferences.get('preferred_language'):
            db_language = preferences['preferred_language']
            self.user_languages[phone_number] = db_language
            return db_language
        
        # If not in DB, check in-memory cache
        if phone_number in self.user_languages:
            return self.user_languages[phone_number]
        
        # Detect language from message
        detected_lang = self.language_service.detect_language(message)
        self.user_languages[phone_number] = detected_lang
        return detected_lang
    
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

    def handle_list_tasks(self, member, phone_number, language):
        tasks = self.task_model.get_tasks_by_user(member['id'])
        if not tasks:
            no_tasks_msg = self.whatsapp_service._get_translated_message('no_tasks', language)
            buttons = self.whatsapp_service._create_welcome_buttons(language)
            self.whatsapp_service.send_message(phone_number, no_tasks_msg, language, buttons)
            return
        
        # Format task list
        task_list = self.whatsapp_service.format_task_list(tasks, language)
        
        # Add selection instruction
        message = task_list + "\n\n*Select a task to update:*"
        
        # Create SIMPLER task selection buttons
        buttons = []
        for i, task in enumerate(tasks[:3], 1):  # Show max 3 tasks
            task_title_short = task['title'][:12] + "..." if len(task['title']) > 12 else task['title']
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"task_{task['id']}",
                    "title": f"#{i}: {task_title_short}"
                }
            })
        
        # Add main menu button
        buttons.append({
            "type": "reply",
            "reply": {
                "id": "main_menu",
                "title": "🏠 Main Menu"  # Changed to include emoji for consistency
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

    def show_task_options(self, member, phone_number, task_id, language):
        """Show options for a specific task"""
        # Store the current task ID in user context
        self._store_user_context(phone_number, {'current_task_id': task_id})
        
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

    def mark_task_complete(self, member, phone_number, task_id, language):
        """Mark a task as complete via button"""
        task = self.task_model.get_task_by_id(task_id, member['id'])
        
        if not task:
            error_msg = self.whatsapp_service._get_translated_message('invalid_task', language)
            self.whatsapp_service.send_message(phone_number, error_msg, language)
            return
        
        # Check if task requires photo
        can_complete, reason = self.task_model.can_complete_task(task_id, member['id'])
        
        if not can_complete and reason == "photo_required":
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
        
        # Task can be completed without photo
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
            print(f"🖼️ Processing image upload from {phone_number}")
            print(f"📎 Media ID: {media_id}")
            
            # Check if user has a pending photo task from button interaction
            user_context = self._get_user_context(phone_number)
            task_id = None
            
            if user_context and 'pending_photo_task' in user_context:
                task_id = user_context['pending_photo_task']
                # Clear the context
                self._clear_user_context(phone_number)
            else:
                # Fallback to the old method
                pending_photo_tasks = self.task_model.get_pending_photo_tasks(member['id'])
                if not pending_photo_tasks:
                    no_tasks_msg = self.whatsapp_service._get_translated_message('no_tasks_photos', language)
                    self.whatsapp_service.send_message(phone_number, no_tasks_msg, language)
                    return
                task = pending_photo_tasks[0]
                task_id = task['id']
            
            print(f"📋 Found task to attach image: Task ID: {task_id}")
            
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
            
            if uploaded_filename:
                # Successfully uploaded via API
                task_completed_msg = self.whatsapp_service._get_translated_message('task_completed', language)
                
                message = (
                    f"{task_completed_msg} 🎉\n\n"
                    f"✅ Photo attached successfully!\n"
                    f"✅ Task marked as completed automatically!\n\n"
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

        except Exception as e:
            print(f"❌ Error in image upload: {e}")
            error_msg = self.whatsapp_service._get_translated_message('upload_error', language)
            self.whatsapp_service.send_message(phone_number, error_msg, language)

    def _store_user_context(self, phone_number, context_data):
        """Store temporary user context for button interactions"""
        # Simple in-memory storage - consider using database for production
        if not hasattr(self, '_user_contexts'):
            self._user_contexts = {}
        self._user_contexts[phone_number] = context_data

    def _get_user_context(self, phone_number):
        """Get user context for button interactions"""
        if hasattr(self, '_user_contexts'):
            return self._user_contexts.get(phone_number)
        return None

    def _clear_user_context(self, phone_number):
        """Clear user context"""
        if hasattr(self, '_user_contexts'):
            self._user_contexts.pop(phone_number, None)

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
        message = "🌐 *Language Settings*\n\nSelect your preferred language:"
        
        sections = [
            {
                "title": "Available Languages",
                "rows": [
                    {
                        "id": "lang_en",
                        "title": "🇺🇸 English",
                        "description": "Switch to English"
                    },
                    {
                        "id": "lang_hi",
                        "title": "🇮🇳 Hindi",
                        "description": "हिंदी में बदलें"
                    },
                    {
                        "id": "lang_es",
                        "title": "🇪🇸 Spanish",
                        "description": "Cambiar a Español"
                    }
                ]
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
            "Select Language", 
            sections,
            language
        )
        
        if not success:
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": "lang_en_btn",
                        "title": "🇺🇸 English"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "lang_hi_btn",
                        "title": "🇮🇳 Hindi"
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