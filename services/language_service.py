from services.free_translation_service import FreeTranslationService
import logging

class LanguageService:
    def __init__(self):
        self.translation_service = FreeTranslationService()
        self.logger = logging.getLogger(__name__)

    def detect_language(self, text):
        """Detect language of the input text"""
        return self.translation_service.detect_language(text)

    def translate_text(self, text, target_language='en', source_language='auto'):
        """Translate text using free services"""
        return self.translation_service.translate_text(text, target_language, source_language)

    def get_language_name(self, language_code):
        """Get full language name from code"""
        return self.translation_service.get_language_name(language_code)

    def is_language_supported(self, language_code):
        """Check if language is supported"""
        return self.translation_service.is_language_supported(language_code)