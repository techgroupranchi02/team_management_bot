import requests
import os
from dotenv import load_dotenv
import mimetypes
import json

load_dotenv()


class ImageService:
    def __init__(self):
        self.meta_access_token = os.getenv("META_ACCESS_TOKEN")
        self.api_version = os.getenv("META_API_VERSION", "v19.0")
        self.image_storage_path = "task_images"
        self.backend_api_url = os.getenv("BACKEND_API_URL")
        self.api_auth_token = os.getenv("API_AUTH_TOKEN")
        os.makedirs(self.image_storage_path, exist_ok=True)

    def download_meta_media(self, media_id, task_id, user_id):
        """Download media from Meta WhatsApp API"""
        try:
            # First, get the media URL
            headers = {"Authorization": f"Bearer {self.meta_access_token}"}
            media_url = f"https://graph.facebook.com/{self.api_version}/{media_id}"

            # Get media information
            response = requests.get(media_url, headers=headers)

            if response.status_code != 200:
                print(f"❌ Failed to get media info. Status: {response.status_code}")
                return None

            media_info = response.json()
            download_url = media_info.get("url")

            if not download_url:
                print(f"❌ No download URL in response: {media_info}")
                return None

            # Download the actual media
            download_response = requests.get(download_url, headers=headers)

            if download_response.status_code != 200:
                print(
                    f"❌ Failed to download media. Status: {download_response.status_code}"
                )
                return None

            # Determine file extension
            mime_type = media_info.get("mime_type", "image/jpeg")
            extension = mimetypes.guess_extension(mime_type) or ".jpg"

            # Create filename
            import datetime

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"task_{task_id}_{timestamp}{extension}"
            filepath = os.path.join(self.image_storage_path, filename)

            # Save image locally
            with open(filepath, "wb") as f:
                f.write(download_response.content)

            print(f"✅ Image saved: {filepath}")
            return filepath

        except Exception as e:
            print(f"❌ Error downloading Meta media: {e}")
            return None

    def upload_to_backend(self, image_path, task_id, client_id):
        """Upload image to your Node.js backend API"""
        try:
            print(f"📤 Uploading image to backend API for task {task_id}")

            # Read image file
            with open(image_path, "rb") as f:
                image_data = f.read()

            # Get filename
            filename = os.path.basename(image_path)

            # Prepare multipart form data - SIMPLIFIED version
            files = {"task_completion_images": (filename, image_data, "image/jpeg")}

            # Headers for API authentication
            headers = {
                "Authorization": f"Bearer {self.api_auth_token}",
                "Client-ID": str(client_id),
            }

            # API endpoint for updating task
            api_url = f"{self.backend_api_url}/team/active-tasks/{task_id}"

            print(f"📤 Sending to API: {api_url}")
            print(f"📤 Headers: {headers}")
            print(f"📤 File: {filename}")

            # Send to your Node.js backend
            response = requests.put(
                api_url,
                files=files,
                headers=headers,
                data={"status": "completed"},  # Auto-complete the task
            )

            print(f"📤 Backend API response status: {response.status_code}")
            print(f"📤 Response text: {response.text[:200]}...")

            if response.status_code == 200:
                result = response.json()
                print(f"✅ Image uploaded successfully via API")

                # Extract image filename from response
                if result.get("success") and "data" in result:
                    task_data = result["data"]
                    if (
                        "completion_images" in task_data
                        and task_data["completion_images"]
                    ):
                        # Return the first image name
                        return task_data["completion_images"][0]
                    elif (
                        "completion_image_urls" in task_data
                        and task_data["completion_image_urls"]
                    ):
                        # Extract filename from URL
                        image_url = task_data["completion_image_urls"][0]
                        return image_url.split("/")[-1]

                return filename
            else:
                print(f"❌ Backend API error: {response.text}")
                return None

        except Exception as e:
            print(f"❌ Error uploading to backend: {e}")
            import traceback

            traceback.print_exc()
            return None
