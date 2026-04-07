import os
import requests
import logging
from typing import Optional

class GroqTranslationService:
    def __init__(self):
        self.api_key = os.getenv('GROQ_API_KEY')
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.1-8b-instant"  # Fast inference model
        self.logger = logging.getLogger(__name__)

        self.supported_languages = {
            'en': 'English', 'hi': 'Hindi', 'es': 'Spanish', 'fr': 'French',
            'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian',
            'ja': 'Japanese', 'ko': 'Korean', 'ar': 'Arabic', 'zh': 'Chinese',
            'mr': 'Marathi', 'ta': 'Tamil', 'te': 'Telugu', 'kn': 'Kannada',
            'ml': 'Malayalam', 'bn': 'Bengali', 'gu': 'Gujarati', 'pa': 'Punjabi',
            'ur': 'Urdu'
        }

    def _call_groq_api(self, system_prompt: str, user_text: str) -> Optional[str]:
        """Helper method to make API calls to Groq."""
        if not self.api_key:
            self.logger.error("GROQ_API_KEY is not set in environment variables.")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.1, # Low temperature for more deterministic output
            "max_tokens": 1024
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data['choices'][0]['message']['content'].strip()
        except Exception as e:
            self.logger.error(f"Groq API error: {e}")
            return None

    def detect_language(self, text: str) -> str:
        """Detect the language of the provided text."""
        system_prompt = (
            "You are a language detection assistant. Your sole purpose is to analyze the "
            "provided text and determine its language.\n\n"
            "Respond ONLY with the ISO 639-1 language code (e.g., 'en', 'hi', 'es').\n"
            "Do not include any other text, explanation, punctuation, or formatting.\n"
            "If you are unable to determine the language with high confidence, respond with 'en'."
        )
        
        detected_code = self._call_groq_api(system_prompt, text)
        
        if detected_code:
            # Clean up the response just in case
            detected_code = detected_code.lower().strip(" \n\"'.")
            if len(detected_code) == 2 or len(detected_code) == 3:
                return detected_code
                
        self.logger.warning(f"Failed to detect language for text: '{text[:20]}...', defaulting to 'en'")
        return 'en'

    def translate_text(self, text: str, target_language: str = 'en', source_language: str = 'auto') -> str:
        """Translate text to the target language."""
        target_lang_name = self.supported_languages.get(target_language, target_language)
        
        system_prompt = (
            f"You are a highly accurate translation assistant. Translate the following text into {target_lang_name}.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. ALWAYS output ONLY the raw translated text.\n"
            "2. NEVER include conversational filler like 'Here is the translation:' or 'Certainly!'.\n"
            f"3. Even if the text is simple or common in another language, you must output the translated {target_lang_name} equivalent.\n"
            f"   - For example, if target is English and input is 'नमस्ते', output 'Hello'. Do NOT output 'नमस्ते'.\n"
            "4. Maintain the original formatting, capitalization, emojis, and punctuation as closely as possible.\n"
            "5. If the text is already completely in the target language, return it exactly as is."
        )

        translated_text = self._call_groq_api(system_prompt, text)

        if translated_text:
            return translated_text

        self.logger.warning(f"Failed to translate text: '{text[:20]}...', returning original text.")
        return text

    def get_language_name(self, language_code: str) -> str:
        """Get full language name from code"""
        return self.supported_languages.get(language_code, 'English')

    def is_language_supported(self, language_code: str) -> bool:
        """Check if language is supported"""
        return language_code in self.supported_languages

    def get_supported_languages(self) -> dict:
        """Get all supported languages"""
        return self.supported_languages

    def transcribe_audio(self, audio_file_path: str) -> dict:
        """Transcribe audio file using Groq Whisper API.
        
        Returns:
            dict with 'text' (transcribed text) and 'language' (detected language code)
        """
        if not self.api_key:
            self.logger.error("GROQ_API_KEY is not set in environment variables.")
            return {'text': '', 'language': 'en'}

        whisper_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            with open(audio_file_path, 'rb') as audio_file:
                files = {
                    'file': (os.path.basename(audio_file_path), audio_file, 'audio/ogg')
                }
                data = {
                    'model': 'whisper-large-v3-turbo',
                    'response_format': 'verbose_json'
                }

                self.logger.info(f"🎙️ Sending audio to Groq Whisper for transcription...")
                response = requests.post(whisper_url, headers=headers, files=files, data=data, timeout=30)
                response.raise_for_status()
                
                result = response.json()
                transcribed_text = result.get('text', '').strip()
                detected_language = result.get('language', 'en')
                
                # Map full language names to ISO codes if needed
                language_name_to_code = {v.lower(): k for k, v in self.supported_languages.items()}
                if detected_language.lower() in language_name_to_code:
                    detected_language = language_name_to_code[detected_language.lower()]
                
                self.logger.info(f"🎙️ Transcription: '{transcribed_text}' | Language: '{detected_language}'")
                
                return {
                    'text': transcribed_text,
                    'language': detected_language
                }

        except Exception as e:
            self.logger.error(f"🎙️ Whisper transcription error: {e}")
            return {'text': '', 'language': 'en'}
