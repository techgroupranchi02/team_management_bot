import requests
import os
from dotenv import load_dotenv
from services.language_service import LanguageService
import logging
import json


load_dotenv()

class WhatsAppService:
    def __init__(self):
        self.meta_access_token = os.getenv('META_ACCESS_TOKEN')
        self.phone_number_id = os.getenv('META_PHONE_NUMBER_ID')
        self.api_version = os.getenv('META_API_VERSION', 'v19.0')
        self.graph_api_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        
        if not all([self.meta_access_token, self.phone_number_id]):
            raise ValueError("Missing Meta environment variables")
            
        self.language_service = LanguageService()
        self.logger = logging.getLogger(__name__)

    def _clean_phone_number_for_meta(self, phone_number):
        """Clean and format phone number for Meta API"""
        # Remove 'whatsapp:' prefix if present
        clean_number = phone_number.replace('whatsapp:', '')
        
        # Remove all non-digit characters
        clean_number = ''.join(c for c in clean_number if c.isdigit())
        
        # Meta requires the phone number with country code but without + prefix
        # Example: 917667130178 (India: 91 + 7667130178)
        return clean_number

    def _is_valid_phone_number(self, phone_number):
        """Basic phone number validation for Meta API"""
        if not phone_number:
            return False
        
        # Check if all digits
        if not phone_number.isdigit():
            return False
            
        # Check minimum length (should have country code + number)
        if len(phone_number) < 10:
            return False
            
        return True

    def format_task_list(self, tasks, language='en'):
        if not tasks:
            return self._get_translated_message("no_tasks", language)

        task_list = self._get_translated_message("task_list_header", language).format(len(tasks))
        
        for i, task in enumerate(tasks):
            task_list += f"*{i + 1}. {task['title']}*\n"
            
            # Add property name if available
            if task.get('property_name'):
                property_text = self._get_translated_message("property", language)
                task_list += f"   🏠 {property_text}: {task['property_name']}\n"
            
            description = task.get('description', self._get_translated_message("no_description", language))
            task_list += f"   📝 {description}\n"
            
            status_text = self._get_translated_message("status", language)
            status_emoji = self.get_status_emoji(task['status'])
            task_list += f"   {status_text}: {status_emoji} {task['status']}\n"
            
            if task.get('task_type'):
                type_text = self._get_translated_message("type", language)
                task_list += f"   {type_text}: {task['task_type']}\n"
            
            task_list += "\n"

        update_instruction = self._get_translated_message("update_instruction", language)
        task_list += update_instruction
        return task_list

    def _get_translated_message(self, message_key, language='en'):
        """Get translated message based on key and language"""
        messages = {
            'en': {
                'no_tasks': "You don't have any tasks assigned at the moment. 🎉",
                'task_list_header': "📋 *Your Tasks ({})*\n\n",
                'property': "Property",
                'no_description': "No description",
                'status': "Status",
                'type': "Type",
                'update_instruction': "To update status, reply:\n*status [number] [status]*\nExample: *status 1 completed*",
                'welcome': "Welcome back {}! 👋\n\nI'm your team management assistant.",
                'help': "Available commands:\n• *tasks* - List your assigned tasks\n• *status [task-number] [status]* - Update task status",
                'photo_required': "📸 *Photo Required* \n\nTask requires a completion photo.",
                'invalid_format': "❌ Invalid format. Please use: *status [task-number] [status]*",
                'task_completed': "✅ Task completed successfully!",
                'image_uploaded': "✅ Photo attached successfully!",
                'no_access': "❌ Sorry, you are not registered in our system.",
                'invalid_status': "❌ Invalid status. Use: pending, in_progress, or completed",
                'invalid_task': "❌ Invalid task number.",
                'no_tasks_photos': "❌ No tasks found that require photos.",
                'download_error': "❌ Failed to download image.",
                'thank_you': "Thank you for documenting your work!",
                'upload_error': "❌ Error processing image.",
                'no_pending_photos': "✅ No tasks waiting for photos!",
                'pending_photos_header': "📸 *Tasks Waiting for Photos:*\n\n",
                'send_photo_instruction': "Simply send a photo now!",
                'help_full': "Hello {}! I'm your team management assistant.",
                'unknown_command': "I didn't understand that command.",
                'status_updated': "📝 Status updated for"
            },
            'hi': {
                'no_tasks': "आपके पास इस समय कोई कार्य नहीं है। 🎉",
                'task_list_header': "📋 *आपके कार्य ({})*\n\n",
                'property': "संपत्ति",
                'no_description': "कोई विवरण नहीं",
                'status': "स्थिति", 
                'type': "प्रकार",
                'update_instruction': "स्थिति अपडेट करने के लिए, जवाब दें:\n*status [संख्या] [स्थिति]*\nउदाहरण: *status 1 completed*",
                'welcome': "वापसी पर स्वागत है {}! 👋\n\nमैं आपका टीम प्रबंधन सहायक हूं।",
                'help': "उपलब्ध आदेश:\n• *tasks* - आपके सौंपे गए कार्य देखें\n• *status [कार्य-संख्या] [स्थिति]* - कार्य स्थिति अपडेट करें",
                'photo_required': "📸 *फोटो आवश्यक* \n\nकार्य को पूरा करने के लिए फोटो की आवश्यकता है।",
                'invalid_format': "❌ गलत प्रारूप। कृपया उपयोग करें: *status [संख्या] [स्थिति]*",
                'task_completed': "✅ कार्य सफलतापूर्वक पूरा हुआ!",
                'image_uploaded': "✅ फोटो सफलतापूर्वक जोड़ा गया!",
                'no_access': "❌ क्षमा करें, आप हमारे सिस्टम में पंजीकृत नहीं हैं।",
                'invalid_status': "❌ गलत स्थिति। उपयोग करें: pending, in_progress, या completed",
                'invalid_task': "❌ गलत कार्य संख्या।",
                'no_tasks_photos': "❌ फोटो की आवश्यकता वाले कोई कार्य नहीं मिले।",
                'download_error': "❌ फोटो डाउनलोड करने में विफल।",
                'thank_you': "आपके काम को दस्तावेज करने के लिए धन्यवाद!",
                'upload_error': "❌ फोटो प्रोसेस करने में त्रुटि।",
                'no_pending_photos': "✅ फोटो की प्रतीक्षा में कोई कार्य नहीं!",
                'pending_photos_header': "📸 *फोटो की प्रतीक्षा में कार्य:*\n\n",
                'send_photo_instruction': "बस अब एक फोटो भेजें!",
                'help_full': "नमस्ते {}! मैं आपका टीम प्रबंधन सहायक हूं।",
                'unknown_command': "मैं उस आदेश को नहीं समझा।",
                'status_updated': "📝 स्थिति अपडेट की गई"
            },
            'es': {
                'no_tasks': "No tienes tareas asignadas en este momento. 🎉",
                'task_list_header': "📋 *Tus Tareas ({})*\n\n", 
                'property': "Propiedad",
                'no_description': "Sin descripción",
                'status': "Estado",
                'type': "Tipo",
                'update_instruction': "Para actualizar el estado, responde:\n*status [número] [estado]*\nEjemplo: *status 1 completed*",
                'welcome': "¡Bienvenido de nuevo {}! 👋\n\nSoy tu asistente de gestión de equipo.",
                'help': "Comandos disponibles:\n• *tasks* - Lista tus tareas asignadas\n• *status [número-tarea] [estado]* - Actualizar estado de tarea", 
                'photo_required': "📸 *Foto Requerida* \n\nLa tarea requiere una foto de finalización.",
                'invalid_format': "❌ Formato inválido. Por favor usa: *status [número] [estado]*",
                'task_completed': "✅ ¡Tarea completada con éxito!",
                'image_uploaded': "✅ ¡Foto adjuntada con éxito!",
                'no_access': "❌ Lo siento, no estás registrado en nuestro sistema.",
                'invalid_status': "❌ Estado inválido. Usa: pending, in_progress, o completed",
                'invalid_task': "❌ Número de tarea inválido.",
                'no_tasks_photos': "❌ No se encontraron tareas que requieran fotos.",
                'download_error': "❌ Error al descargar la imagen.",
                'thank_you': "¡Gracias por documentar tu trabajo!",
                'upload_error': "❌ Error al procesar la imagen.",
                'no_pending_photos': "✅ ¡No hay tareas esperando fotos!",
                'pending_photos_header': "📸 *Tareas Esperando Fotos:*\n\n",
                'send_photo_instruction': "¡Simplemente envía una foto ahora!",
                'help_full': "¡Hola {}! Soy tu asistente de gestión de equipo.",
                'unknown_command': "No entendí ese comando.",
                'status_updated': "📝 Estado actualizado para"
            },
            'fr': {
                'no_tasks': "Vous n'avez aucune tâche assignée pour le moment. 🎉",
                'task_list_header': "📋 *Vos Tâches ({})*\n\n",
                'property': "Propriété", 
                'no_description': "Aucune description",
                'status': "Statut",
                'type': "Type",
                'update_instruction': "Pour mettre à jour le statut, répondez:\n*status [numéro] [statut]*\nExemple: *status 1 completed*",
                'welcome': "Bon retour {}! 👋\n\nJe suis votre assistant de gestion d'équipe.",
                'help': "Commandes disponibles:\n• *tasks* - Lister vos tâches assignées\n• *status [numéro-tâche] [statut]* - Mettre à jour le statut de la tâche",
                'photo_required': "📸 *Photo Requise* \n\nLa tâche nécessite une photo d'achèvement.",
                'invalid_format': "❌ Format invalide. Veuillez utiliser: *status [numéro] [statut]*", 
                'task_completed': "✅ Tâche terminée avec succès!",
                'image_uploaded': "✅ Photo attachée avec succès!",
                'no_access': "❌ Désolé, vous n'êtes pas enregistré dans notre système.",
                'invalid_status': "❌ Statut invalide. Utilisez: pending, in_progress, ou completed",
                'invalid_task': "❌ Numéro de tâche invalide.",
                'no_tasks_photos': "❌ Aucune tâche nécessitant des photos trouvée.",
                'download_error': "❌ Échec du téléchargement de l'image.",
                'thank_you': "Merci d'avoir documenté votre travail!",
                'upload_error': "❌ Erreur de traitement de l'image.",
                'no_pending_photos': "✅ Aucune tâche n'attend de photos!",
                'pending_photos_header': "📸 *Tâches en attente de photos:*\n\n",
                'send_photo_instruction': "Envoyez simplement une photo maintenant!",
                'help_full': "Bonjour {}! Je suis votre assistant de gestion d'équipe.",
                'unknown_command': "Je n'ai pas compris cette commande.",
                'status_updated': "📝 Statut mis à jour pour"
            }
        }
        
        # Default to English if language not supported
        if language not in messages:
            language = 'en'
            
        return messages[language].get(message_key, messages['en'].get(message_key, ""))

    @staticmethod
    def get_status_emoji(status):
        emojis = {
            'pending': '⏳',
            'in_progress': '🔄',
            'completed': '✅',
            'skipped': '⏭️'
            
        }
        return emojis.get(status, '📝')

    
    
    
    def send_interactive_list(self, to, body_text, button_text, sections, language='en'):
        """Send an interactive list message"""
        try:
            clean_to = self._clean_phone_number_for_meta(to)
            
            if not self._is_valid_phone_number(clean_to):
                self.logger.error(f"Invalid phone number format: {clean_to}")
                return False

            headers = {
                'Authorization': f'Bearer {self.meta_access_token}',
                'Content-Type': 'application/json'
            }
            
            # Build the interactive list structure
            list_sections = []
            
            for section in sections:
                section_dict = {
                    "title": section['title'],
                    "rows": []
                }
                
                for row in section['rows']:
                    row_dict = {
                        "id": row['id'],
                        "title": row['title']
                    }
                    
                    if 'description' in row:
                        row_dict["description"] = row['description']
                    
                    section_dict["rows"].append(row_dict)
                
                list_sections.append(section_dict)
            
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {
                        "text": body_text
                    },
                    "action": {
                        "button": button_text,
                        "sections": list_sections
                    }
                }
            }
            
            print(f"📋 Sending interactive list with {len(sections)} sections")
            
            response = requests.post(self.graph_api_url, headers=headers, json=payload)
            
            print(f"📋 Response Status: {response.status_code}")
            
            if response.status_code == 200:
                self.logger.info("✅ Interactive list sent successfully!")
                return True
            else:
                self.logger.error(f"❌ Failed to send interactive list: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error sending interactive list: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def send_message(self, to, message, language='en', buttons=None):
        try:
            # Clean and format phone number for Meta API
            clean_to = self._clean_phone_number_for_meta(to)
            
            print(f"📤 Attempting to send to: {clean_to}, Original: {to}")
            print(f"📤 Message: {message[:50]}...")
            
            if not self._is_valid_phone_number(clean_to):
                self.logger.error(f"Invalid phone number format: {clean_to}")
                return False

            headers = {
                'Authorization': f'Bearer {self.meta_access_token}',
                'Content-Type': 'application/json'
            }
            
            if buttons:
                # Create interactive button message
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_to,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {
                            "text": message
                        },
                        "action": {
                            "buttons": buttons
                        }
                    }
                }
                
                # Debug: Print the button structure
                print(f"🔘 Button structure: {json.dumps(payload['interactive'], indent=2)}")
                
                response = requests.post(self.graph_api_url, headers=headers, json=payload)
                
                print(f"📤 Response Status: {response.status_code}")
                print(f"📤 Response: {response.text[:200]}")
                
                if response.status_code == 200:
                    response_data = response.json()
                    message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                    self.logger.info(f"✅ Interactive button message sent successfully! Message ID: {message_id}")
                    return True
                else:
                    self.logger.error(f"❌ Failed to send interactive button message. Status: {response.status_code}, Error: {response.text}")
                    # IMPORTANT: Don't fall back to text message - fix the button issue instead
                    # Check if buttons are properly formatted
                    self._debug_button_format(buttons)
                    
                    # Try sending the message without buttons but with instructions
                    return self._send_fallback_message(clean_to, message, headers, language)
                    
            else:
                # Regular text message
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_to,
                    "type": "text",
                    "text": {
                        "preview_url": False,
                        "body": message
                    }
                }
                
                print(f"📤 Sending text message...")
                
                response = requests.post(self.graph_api_url, headers=headers, json=payload)
                
                print(f"📤 Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    self.logger.info("✅ Text message sent successfully!")
                    return True
                else:
                    self.logger.error(f"❌ Failed to send text message: {response.text}")
                    return False
                
        except Exception as e:
            self.logger.error(f"❌ Error sending WhatsApp message: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def _send_fallback_message(self, clean_to, message, headers, language='en'):
        """Send fallback message when interactive buttons fail"""
        try:
            # Send a simpler message with text instructions
            fallback_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_to,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": message + "\n\nPlease reply with:\n1. Tasks\n2. Photos\n3. Recurring\n4. Settings\n5. Help"
                }
            }
            
            fallback_response = requests.post(self.graph_api_url, headers=headers, json=fallback_payload)
            
            if fallback_response.status_code == 200:
                self.logger.info("✅ Fallback text message sent successfully!")
                return True
            else:
                self.logger.error(f"❌ Fallback message also failed: {fallback_response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error in fallback: {str(e)}")
            return False

    def _debug_button_format(self, buttons):
        """Debug button formatting issues"""
        self.logger.info("🔧 Debugging button format...")
        
        # Check button structure
        for i, button in enumerate(buttons):
            self.logger.info(f"Button {i+1}:")
            self.logger.info(f"  Type: {button.get('type')}")
            reply = button.get('reply', {})
            self.logger.info(f"  ID: {reply.get('id')}")
            self.logger.info(f"  Title: {reply.get('title')}")
            
        # Check Meta API requirements
        self.logger.info("🔧 Meta API Requirements:")
        self.logger.info("1. Max 3 reply buttons")
        self.logger.info("2. Button IDs must be unique")
        self.logger.info("3. Button titles max 20 characters")
        self.logger.info("4. Only 'reply' button type supported")
        
        # Validate buttons
        if len(buttons) > 3:
            self.logger.error("❌ Too many buttons! Max is 3.")
            
        for button in buttons:
            title = button.get('reply', {}).get('title', '')
            if len(title) > 20:
                self.logger.error(f"❌ Button title too long: '{title}' (max 20 chars)")

    def _create_welcome_buttons(self, language='en'):
        """Create button options for welcome message - PROPERLY FORMATTED"""
        # Use simple, short titles
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": "btn_tasks",
                    "title": "📋 Tasks"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "btn_photos",
                    "title": "📷 Photos"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "btn_settings",
                    "title": "⚙️ Settings"
                }
            }
        ]
        
        return buttons

    def _create_task_action_buttons(self, language='en'):
        """Create buttons for task actions"""
        button_labels = {
            'en': ["📝 Update Status", "📋 View Tasks", "🏠 Main Menu"],
            'hi': ["📝 Status Update", "📋 View Tasks", "🏠 Main Menu"],  # Simplified Hindi
            'es': ["📝 Update Status", "📋 View Tasks", "🏠 Main Menu"],  # Simplified Spanish
            'fr': ["📝 Update Status", "📋 View Tasks", "🏠 Main Menu"]   # Simplified French
        }
        
        lang = 'en'  # Use English for now to simplify
        labels = button_labels[lang]
        
        buttons = []
        for i, label in enumerate(labels[:3], 1):  # Max 3 buttons
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"action_{i}",
                    "title": label[:20]
                }
            })
        
        return buttons

    def format_task_list_with_buttons(self, tasks, language='en'):
        if not tasks:
            return self._get_translated_message("no_tasks", language), None

        task_list = self._get_translated_message("task_list_header", language).format(len(tasks))
        
        for i, task in enumerate(tasks):
            task_list += f"*{i + 1}. {task['title']}*\n"
            
            # Add property name if available
            if task.get('property_name'):
                property_text = self._get_translated_message("property", language)
                task_list += f"   🏠 {property_text}: {task['property_name']}\n"
            
            description = task.get('description', self._get_translated_message("no_description", language))
            task_list += f"   📝 {description}\n"
            
            status_text = self._get_translated_message("status", language)
            status_emoji = self.get_status_emoji(task['status'])
            task_list += f"   {status_text}: {status_emoji} {task['status']}\n\n"
        
        # Add selection instruction
        task_list += "*Select a task to update:*"
        
        # Create buttons for task selection
        buttons = []
        for i, task in enumerate(tasks[:3], 1):  # Show max 3 tasks with buttons
            task_title_short = task['title'][:15] + "..." if len(task['title']) > 15 else task['title']
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"task_{task['id']}",
                    "title": f"#{i}: {task_title_short}"
                }
            })
        
        # Add view all button if more than 3 tasks
        if len(tasks) > 3:
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": "view_all_tasks",
                    "title": "📋 View All"
                }
            })
        
        return task_list, buttons

    def _create_task_completion_buttons(self, task_id, language='en'):
        """Create buttons for completing a specific task"""
        button_labels = {
            'en': ["✅ Mark Complete", "📝 Update Status", "📋 Back to Tasks"],
            'hi': ["✅ पूरा करें", "📝 स्थिति बदलें", "📋 वापस कार्य"],
            'es': ["✅ Completar", "📝 Cambiar Estado", "📋 Volver"],
            'fr': ["✅ Terminer", "📝 Modifier", "📋 Retour"]
        }
        
        lang = language if language in button_labels else 'en'
        labels = button_labels[lang]
        
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": f"mark_complete_{task_id}",
                    "title": labels[0][:20]
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": f"update_status_{task_id}",
                    "title": labels[1][:20]
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "back_to_tasks",
                    "title": labels[2][:20]
                }
            }
        ]
        
        return buttons

    def _create_task_status_buttons(self, task_id, language='en'):
        """Create buttons for selecting task status"""
        button_labels = {
            'en': ["⏳ Pending", "🔄 In Progress", "✅ Complete", "⏭️ Skipped", "📋 Back"],
            'hi': ["⏳ लंबित", "🔄 चालू", "✅ पूरा", "⏭️ छोड़ा गया", "📋 वापस"],
            'es': ["⏳ Pendiente", "🔄 En Progreso", "✅ Completado", "⏭️ Omitido", "📋 Atrás"],
            'fr': ["⏳ En Attente", "🔄 En Cours", "✅ Terminé", "⏭️ Ignoré", "📋 Retour"]
        }
        
        lang = language if language in button_labels else 'en'
        labels = button_labels[lang]
        
        buttons = []
        for i, label in enumerate(labels[:4], 1):  # First 4 are status options
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"status_{task_id}_{label.lower().replace(' ', '_').replace('⏭️_', '')}",
                    "title": label[:20]
                }
            })
        
        # Add back button
        buttons.append({
            "type": "reply",
            "reply": {
                "id": f"back_tasks_{task_id}",
                "title": labels[4][:20] if len(labels) > 4 else "📋 Back"
            }
        })
        
        return buttons    
