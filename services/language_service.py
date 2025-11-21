from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

# For consistent results
DetectorFactory.seed = 0

class LanguageService:
    def __init__(self):
        self.supported_languages = ['en', 'hi']  # English, Hindi
        
    def detect_language(self, text):
        """
        Detect the language of the input text
        Returns 'en' for English, 'hi' for Hindi, or default 'en'
        """
        if not text or not text.strip():
            return 'en'
            
        try:
            # Clean text for detection
            clean_text = text.strip()
            if len(clean_text) < 3:
                return 'en'
                
            detected_lang = detect(clean_text)
            
            # Map to supported languages
            if detected_lang in ['hi', 'mr', 'gu', 'pa', 'bn', 'ta', 'te', 'kn', 'ml', 'or', 'as']:
                return 'hi'
            else:
                return 'en'
                
        except LangDetectException:
            return 'en'
    
    def hindi_to_english_numbers(self, text):
        """Convert Hindi numbers to English numbers"""
        hindi_to_eng_map = {
            '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
            '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
        }
        
        result = ''
        for char in text:
            result += hindi_to_eng_map.get(char, char)
        return result
    
    def get_message(self, message_key, lang='en'):
        """Get translated message for the given key and language"""
        messages = {
            'en': {
                'welcome': "Welcome back {name}! 👋\n\nI'm your team management assistant. Here's what you can do:\n\n📋 *Tasks* - View all your assigned tasks\n🔄 *Status* - Update task status (pending/in-progress/completed)\n📷 *Send Image* - Attach photo to completed task\n\nType *tasks* to see your current assignments or type *help* for more options.",
                'help': "Hello {name}! I'm your team management assistant.\n\nAvailable commands:\n• *tasks* - List your assigned tasks\n• *status [task-number] [status]* - Update task status\n• Send image to attach to completed task\n\nExamples:\n*status 1 completed* - Mark task 1 as completed\n*tasks* - View all your tasks",
                'error_not_registered': "Sorry, you are not registered in our system. Please contact your administrator.",
                'invalid_status_format': "Invalid format. Please use: *status [task-number] [status]*\n\nExample: *status 1 completed*\nAvailable status: pending, in-progress, completed",
                'invalid_status': "Invalid status. Use: pending, in-progress, or completed",
                'invalid_task_number': "Invalid task number. Use *tasks* to see your task list.",
                'task_completed': "✅ Task \"{task_title}\" marked as completed!\n\nPlease send a photo of the completed work to attach to this task.",
                'status_updated': "📝 Status updated for \"{task_title}\" to: {status}",
                'status_update_error': "Error updating task status. Please try again.",
                'no_recent_task': "❌ No recently completed task found.\n\nPlease:\n1. First mark a task as completed using: *status [number] completed*\n2. Then send the image immediately after",
                'image_download_error': "❌ Failed to download image from WhatsApp. Please try again.",
                'image_upload_success': "✅ Image successfully uploaded!\n\n📋 Task: {task_title}\n🏠 Property: {property_name}\n\n📸 View image: {image_url}\n\nThank you for documenting your work! 🎉",
                'image_saved': "✅ Image received and saved!\n\n📋 Task: {task_title}\n🏠 Property: {property_name}\n\nThe image has been stored with your task completion. 📸",
                'image_save_error': "❌ Error saving image to task. Please try again.",
                'image_processing_error': "❌ Error processing image. Please try again or contact support.",
                'unknown_command': "I didn't understand that command. Type *help* to see available commands."
            },
            'hi': {
                'welcome': "वापसी पर स्वागत है {name}! 👋\n\nमैं आपकी टीम प्रबंधन सहायक हूं। यहां बताई गई चीजें आप कर सकते हैं:\n\n📋 *कार्य* - अपने सभी सौंपे गए कार्य देखें\n🔄 *स्थिति* - कार्य स्थिति अपडेट करें (लंबित/चल रहा/पूरा)\n📷 *छवि भेजें* - पूर्ण कार्य में फोटो संलग्न करें\n\nअपने वर्तमान कार्य देखने के लिए *कार्य* टाइप करें या अधिक विकल्पों के लिए *मदद* टाइप करें।",
                'help': "नमस्ते {name}! मैं आपकी टीम प्रबंधन सहायक हूं।\n\nउपलब्ध कमांड:\n• *कार्य* - अपने सौंपे गए कार्यों की सूची देखें\n• *स्थिति [कार्य-संख्या] [स्थिति]* - कार्य स्थिति अपडेट करें\n• पूर्ण कार्य में संलग्न करने के लिए छवि भेजें\n\nउदाहरण:\n*स्थिति 1 पूरा* - कार्य 1 को पूरा के रूप में चिह्नित करें\n*कार्य* - अपने सभी कार्य देखें",
                'error_not_registered': "क्षमा करें, आप हमारे सिस्टम में पंजीकृत नहीं हैं। कृपया अपने प्रशासक से संपर्क करें।",
                'invalid_status_format': "अमान्य प्रारूप। कृपया उपयोग करें: *स्थिति [कार्य-संख्या] [स्थिति]*\n\nउदाहरण: *स्थिति 1 पूरा*\nउपलब्ध स्थिति: लंबित, चल रहा, पूरा",
                'invalid_status': "अमान्य स्थिति। उपयोग करें: लंबित, चल रहा, या पूरा",
                'invalid_task_number': "अमान्य कार्य संख्या। अपनी कार्य सूची देखने के लिए *कार्य* का उपयोग करें।",
                'task_completed': "✅ कार्य \"{task_title}\" पूरा के रूप में चिह्नित!\n\nकृपया इस कार्य से संलग्न करने के लिए पूर्ण कार्य की एक फोटो भेजें।",
                'status_updated': "📝 \"{task_title}\" के लिए स्थिति अपडेट की गई: {status}",
                'status_update_error': "कार्य स्थिति अपडेट करने में त्रुटि। कृपया पुनः प्रयास करें।",
                'no_recent_task': "❌ कोई हाल ही में पूरा किया गया कार्य नहीं मिला।\n\nकृपया:\n1. पहले *स्थिति [संख्या] पूरा* का उपयोग करके एक कार्य को पूरा के रूप में चिह्नित करें\n2. उसके तुरंत बाद छवि भेजें",
                'image_download_error': "❌ व्हाट्सएप से छवि डाउनलोड करने में विफल। कृपया पुनः प्रयास करें।",
                'image_upload_success': "✅ छवि सफलतापूर्वक अपलोड की गई!\n\n📋 कार्य: {task_title}\n🏠 संपत्ति: {property_name}\n\n📸 छवि देखें: {image_url}\n\nअपना कार्य दस्तावेज करने के लिए धन्यवाद! 🎉",
                'image_saved': "✅ छवि प्राप्त और सहेजी गई!\n\n📋 कार्य: {task_title}\n🏠 संपत्ति: {property_name}\n\nछवि आपके कार्य पूर्णता के साथ संग्रहीत की गई है। 📸",
                'image_save_error': "❌ कार्य में छवि सहेजने में त्रुटि। कृपया पुनः प्रयास करें।",
                'image_processing_error': "❌ छवि प्रसंस्करण में त्रुटि। कृपया पुनः प्रयास करें या समर्थन से संपर्क करें।",
                'unknown_command': "मैं उस कमांड को नहीं समझ पाया। उपलब्ध कमांड देखने के लिए *मदद* टाइप करें।"
            }
        }
        
        return messages.get(lang, messages['en']).get(message_key, message_key)
    
    def get_welcome_message(self, name, lang='en'):
        """Get welcome message in specified language"""
        return self.get_message('welcome', lang).format(name=name)
    
    def get_help_message(self, name, lang='en'):
        """Get help message in specified language"""
        return self.get_message('help', lang).format(name=name)
    
    def get_status_text(self, status, lang='en'):
        """Get status text in specified language"""
        status_map = {
            'en': {
                'pending': 'pending',
                'in-progress': 'in-progress', 
                'completed': 'completed'
            },
            'hi': {
                'pending': 'लंबित',
                'in-progress': 'चल रहा',
                'completed': 'पूरा'
            }
        }
        return status_map.get(lang, status_map['en']).get(status, status)