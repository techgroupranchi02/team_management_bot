import requests
import os
from dotenv import load_dotenv
import base64

load_dotenv()

class ImageService:
    def __init__(self):
        self.twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.image_storage_path = "task_images"
        os.makedirs(self.image_storage_path, exist_ok=True)

    def download_twilio_media(self, media_url, task_id, user_id):
        """Download media from Twilio URL with authentication"""
        try:
            # Create the auth header for Twilio
            auth = (self.twilio_account_sid, self.twilio_auth_token)
            
            # Download the media from Twilio
            response = requests.get(media_url, auth=auth)
            
            if response.status_code != 200:
                print(f"❌ Failed to download media. Status: {response.status_code}")
                return None
            
            # Create filename
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"task_{task_id}_{timestamp}.jpg"
            filepath = os.path.join(self.image_storage_path, filename)
            
            # Save image locally
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            print(f"✅ Image saved: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"❌ Error downloading Twilio media: {e}")
            return None

    def upload_to_cloudinary(self, image_path, task_id, user_id):
        """Upload image to Cloudinary (optional)"""
        try:
            import cloudinary
            import cloudinary.uploader
            
            # Configure Cloudinary if credentials exist
            cloudinary.config(
                cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
                api_key=os.getenv('CLOUDINARY_API_KEY'),
                api_secret=os.getenv('CLOUDINARY_API_SECRET'),
                secure=True
            )
            
            result = cloudinary.uploader.upload(
                image_path,
                folder="task_completions",
                public_id=f"task_{task_id}_user_{user_id}",
                overwrite=True
            )
            
            return result.get('secure_url')
            
        except Exception as e:
            print(f"❌ Cloudinary upload failed: {e}")
            return None