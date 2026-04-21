import requests
from deep_translator import GoogleTranslator
import logging
from typing import Optional

class FreeTranslationService:
    def __init__(self):
        self.supported_languages = {
            'en': 'English',
            'hi': 'Hindi', 
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'ru': 'Russian',
            'ja': 'Japanese',
            'ko': 'Korean',
            'ar': 'Arabic',
            'zh': 'Chinese',
            'mr': 'Marathi',
            'ta': 'Tamil',
            'te': 'Telugu',
            'kn': 'Kannada',
            'ml': 'Malayalam',
            'bn': 'Bengali',
            'gu': 'Gujarati',
            'pa': 'Punjabi',
            'ur': 'Urdu'
        }
        self.logger = logging.getLogger(__name__)
        
    def detect_language(self, text: str) -> str:
        """
        Detect language using multiple free methods
        """
        try:
            text_lower = text.lower().strip()
            
            # Method 1: Keyword-based detection
            detected = self._keyword_detection(text_lower)
            if detected:
                return detected
                
            # Method 2: Try deep-translator library
            try:
                detected = GoogleTranslator().detect(text)
                if detected in self.supported_languages:
                    return detected
            except:
                pass
                
            # Method 3: Character range detection
            detected = self._character_based_detection(text)
            if detected:
                return detected
                
        except Exception as e:
            self.logger.error(f"Language detection error: {e}")
            
        return 'en'  # Default to English
    
    def _keyword_detection(self, text: str) -> Optional[str]:
        """Keyword-based language detection"""
        language_keywords = {
            'hi': ['नमस्ते', 'धन्यवाद', 'कैसे', 'हैं', 'में', 'का', 'की', 'से', 'है', 'और', 'क्या', 'कर', 'यह', 'वह', 'तो'],
            'es': ['hola', 'gracias', 'por favor', 'cómo', 'estás', 'buenos', 'días', 'noche', 'adiós', 'sí', 'no'],
            'fr': ['bonjour', 'merci', 's\'il vous plaît', 'comment', 'ça va', 'oui', 'non', 'au revoir', 'madame', 'monsieur'],
            'de': ['hallo', 'guten tag', 'danke', 'bitte', 'wie', 'geht', 'es', 'ihnen', 'ja', 'nein', 'tschüss'],
            'it': ['ciao', 'buongiorno', 'grazie', 'per favore', 'come', 'sta', 'si', 'no', 'arrivederci'],
            'pt': ['olá', 'bom dia', 'obrigado', 'por favor', 'como', 'está', 'sim', 'não', 'adeus'],
            'ru': ['привет', 'здравствуйте', 'спасибо', 'пожалуйста', 'как', 'дела', 'да', 'нет', 'до свидания'],
            'ja': ['こんにちは', 'ありがとう', 'お願いします', 'はい', 'いいえ', 'さようなら', 'おはよう'],
            'ko': ['안녕하세요', '감사합니다', '부탁합니다', '네', '아니요', '안녕히 가세요'],
            'ar': ['مرحبا', 'شكرا', 'من فضلك', 'كيف', 'الحال', 'نعم', 'لا', 'مع السلامة'],
            'zh': ['你好', '谢谢', '请', '是的', '不是', '再见', '早上好'],
            'mr': ['नमस्कार', 'धन्यवाद', 'कसे', 'आहे', 'मध्ये', 'चा', 'ची', 'पासून'],
            'ta': ['வணக்கம்', 'நன்றி', 'தயவு செய்து', 'எப்படி', 'உள்ளது', 'ஆம்', 'இல்லை'],
            'te': ['నమస్కారం', 'ధన్యవాదాలు', 'దయచేసి', 'ఎలా', 'ఉంది', 'అవును', 'కాదు'],
            'kn': ['ನಮಸ್ಕಾರ', 'ಧನ್ಯವಾದ', 'ದಯವಿಟ್ಟು', 'ಹೇಗೆ', 'ಇದೆ', 'ಹೌದು', 'ಇಲ್ಲ'],
            'ml': ['നമസ്കാരം', 'നന്ദി', 'ദയവായി', 'എങ്ങനെ', 'ആണ്', 'അതെ', 'ഇല്ല'],
            'bn': ['নমস্কার', 'ধন্যবাদ', 'দয়া করে', 'কেমন', 'আছে', 'হ্যাঁ', 'না'],
            'gu': ['નમસ્તે', 'આભાર', 'કૃપા કરીને', 'કેવી રીતે', 'છે', 'હા', 'ના'],
            'pa': ['ਸਤ ਸ੍ਰੀ ਅਕਾਲ', 'ਧੰਨਵਾਦ', 'ਕ੍ਰਿਪਾ ਕਰਕੇ', 'ਕਿਵੇਂ', 'ਹੈ', 'ਹਾਂ', 'ਨਹੀਂ'],
            'ur': ['سلام', 'شکریہ', 'براہ کرم', 'کیسے', 'ہے', 'جی ہاں', 'نہیں']
        }
        
        for lang_code, keywords in language_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    return lang_code
        return None
    
    def _character_based_detection(self, text: str) -> Optional[str]:
        """Detect language based on character ranges"""
        # Hindi, Marathi, Sanskrit, etc. (Devanagari script)
        if any('\u0900' <= char <= '\u097F' for char in text):
            return 'hi'
        
        # Arabic script (Arabic, Urdu, Persian)
        if any('\u0600' <= char <= '\u06FF' for char in text):
            return 'ar'
        
        # Chinese, Japanese, Korean characters
        if any('\u4E00' <= char <= '\u9FFF' for char in text):  # CJK Unified Ideographs
            return 'zh'
        if any('\u3040' <= char <= '\u309F' for char in text):  # Hiragana
            return 'ja'
        if any('\u30A0' <= char <= '\u30FF' for char in text):  # Katakana
            return 'ja'
        if any('\uAC00' <= char <= '\uD7AF' for char in text):  # Hangul
            return 'ko'
        
        # Cyrillic (Russian, Ukrainian, etc.)
        if any('\u0400' <= char <= '\u04FF' for char in text):
            return 'ru'
            
        return None
    
    def translate_text(self, text: str, target_language: str = 'en', source_language: str = 'auto') -> str:
        """
        Translate text using free translation services
        """
        try:
            # If same language, return original
            if source_language == target_language:
                return text
                
            # Try deep-translator (free library)
            try:
                if source_language == 'auto':
                    translator = GoogleTranslator(source='auto', target=target_language)
                else:
                    translator = GoogleTranslator(source=source_language, target=target_language)
                
                translated = translator.translate(text)
                if translated and translated != text:
                    return translated
            except Exception as e:
                self.logger.warning(f"Deep-translator failed: {e}")
                
            # Fallback: Try MyMemory Translation API (free)
            try:
                translated = self._translate_mymemory(text, target_language, source_language)
                if translated:
                    return translated
            except Exception as e:
                self.logger.warning(f"MyMemory translation failed: {e}")
                
        except Exception as e:
            self.logger.error(f"Translation error: {e}")
            
        return text  # Return original text if translation fails
    
    def _translate_mymemory(self, text: str, target_lang: str, source_lang: str = 'auto') -> Optional[str]:
        """Use MyMemory Translation API (free)"""
        try:
            if source_lang == 'auto':
                source_lang = 'auto'
                
            url = "https://api.mymemory.translated.net/get"
            params = {
                'q': text,
                'langpair': f'{source_lang}|{target_lang}'
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data['responseStatus'] == 200:
                    return data['responseData']['translatedText']
                    
        except Exception as e:
            self.logger.warning(f"MyMemory API error: {e}")
            
        return None
    
    def get_language_name(self, language_code: str) -> str:
        """Get full language name from code"""
        return self.supported_languages.get(language_code, 'English')
    
    def is_language_supported(self, language_code: str) -> bool:
        """Check if language is supported"""
        return language_code in self.supported_languages
    
    def get_supported_languages(self) -> dict:
        """Get all supported languages"""
        return self.supported_languages