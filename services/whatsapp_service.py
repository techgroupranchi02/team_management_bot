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

    def send_message(self, to, message, language='en'):
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
            
            print(f"📤 Headers: {headers}")
            print(f"📤 Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(self.graph_api_url, headers=headers, json=payload)
            
            print(f"📤 Response Status: {response.status_code}")
            print(f"📤 Response: {response.text}")
            
            if response.status_code == 200:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                self.logger.info(f"✅ WhatsApp message sent successfully! Message ID: {message_id}")
                return True
            else:
                self.logger.error(f"❌ Failed to send WhatsApp message. Status: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error sending WhatsApp message: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

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
            'cancelled': '❌',
            'overdue': '⚠️'
        }
        return emojis.get(status, '📝')