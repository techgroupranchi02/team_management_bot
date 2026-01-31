from enum import member
from flask import Flask, request, jsonify
import mysql.connector
from dotenv import load_dotenv
import os
import logging
import json 
from services.task_service import TaskService
from services.reminder_service import ReminderService

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', ),
    'port': int(os.getenv('DB_PORT', )),
    'user': os.getenv('DB_USER', ),
    'password': os.getenv('DB_PASSWORD', ),
    'database': os.getenv('DB_NAME', ),
    'charset': 'utf8mb4',
    'buffered': True,  # Add this line
    'autocommit': True 
}

def get_db_connection():
    """Create and return MySQL database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

# Initialize services
task_service = TaskService(DB_CONFIG)
reminder_service = ReminderService(DB_CONFIG)

def check_existing_data():
    """Check what data already exists in the database"""
    from models.team_member import TeamMember
    from models.task import Task
    
    team_member_model = TeamMember(DB_CONFIG)
    task_model = Task(DB_CONFIG)
    
    # Check if sample team member exists
    sample_member = team_member_model.find_by_phone('7667130178')
    if sample_member:
        print(f"✅ Team member found: {sample_member['name']} (ID: {sample_member['id']})")
        
        # Check tasks for this member
        tasks = task_model.get_tasks_by_user(sample_member['id'])
        print(f"📋 Number of tasks assigned: {len(tasks)}")
        
        for task in tasks:
            print(f"  - {task['title']} (Status: {task['status']})")
    else:
        print("❌ Team member not found")

@app.route('/')
def home():
    return jsonify({"message": "Team Management WhatsApp Bot is running!"})

@app.route('/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook():
    try:
        # Meta sends JSON data, not form data
        data = request.get_json()
        
        if not data or 'entry' not in data:
            logger.info("No valid message data in webhook")
            return '', 200
        
        # Process each entry
        for entry in data['entry']:
            for change in entry.get('changes', []):
                if change.get('field') == 'messages':
                    value = change.get('value', {})
                    
                    # Check if this is a message or a status update
                    if 'messages' in value:
                        # This is an actual message from user
                        messages = value.get('messages', [])
                        contacts = value.get('contacts', [])
                        
                        if messages:
                            message = messages[0]
                            message_type = message.get('type')
                            from_number = message.get('from', '')
                            
                            # Get contact name if available
                            contact_name = contacts[0].get('profile', {}).get('name', '') if contacts else ''
                            
                            # Get member info
                            clean_phone = from_number.replace('whatsapp:', '')
                            member = task_service.team_member_model.find_by_phone(clean_phone)
                            
                            logger.info(f"📨 Message type: {message_type} from: {from_number} (Contact: {contact_name})")
                            
                            try:
                                if message_type == 'text':
                                    incoming_msg = message.get('text', {}).get('body', '').strip()
                                    logger.info(f"📝 Text message: {incoming_msg}")
                                    
                                    if incoming_msg.lower().startswith('join'):
                                        logger.info(f"Join command received: {incoming_msg}")
                                    else:
                                        # Process text message
                                        task_service.handle_message(f"whatsapp:{from_number}", incoming_msg, None)
                                
                                elif message_type == 'image':
                                    # Get image information
                                    image_data = message.get('image', {})
                                    media_id = image_data.get('id', '')
                                    caption = image_data.get('caption', '')
                                    
                                    logger.info(f"🖼️ Image message, Media ID: {media_id}, Caption: {caption}")
                                    
                                    # Process image upload with caption (if any)
                                    task_service.handle_message(f"whatsapp:{from_number}", caption or "", media_id)
                                
                                elif message_type == 'interactive':
                                    # Handle interactive messages
                                    interactive_data = message.get('interactive', {})
                                    interactive_type = interactive_data.get('type')
                                    
                                    if interactive_type == 'button_reply':
                                        button_reply = interactive_data.get('button_reply', {})
                                        if button_reply:
                                            button_id = button_reply.get('id', '')
                                            title = button_reply.get('title', '')
                                            logger.info(f"🔄 Button click: {button_id} - {title}")
                                            # Send the button title as the message
                                            task_service.handle_message(f"whatsapp:{from_number}", title, None)
                                    
                                    elif interactive_type == 'list_reply':
                                        list_reply = interactive_data.get('list_reply', {})
                                        if list_reply:
                                            list_id = list_reply.get('id', '')
                                            list_title = list_reply.get('title', '')
                                            list_description = list_reply.get('description', '')
                                            logger.info(f"📋 List selection: {list_id} - {list_title}")
                                            
                                            if member:
                                                # Handle settings menu selections
                                                if list_id == "property_info":
                                                    # Show current property info
                                                    task_service.show_current_property_info(member, f"whatsapp:{from_number}", 'en')
                                                elif list_id == "property_change":
                                                    # Show property selection menu
                                                    task_service.show_property_selection_menu(member, f"whatsapp:{from_number}", 'en')
                                                elif list_id == "back_main":
                                                    # Return to main menu
                                                    task_service.show_main_menu(member, f"whatsapp:{from_number}", 'en')
                                                elif list_id == "language_change":
                                                    # Handle language change
                                                    task_service.handle_language_change(member, f"whatsapp:{from_number}", 'en')
                                                elif list_id.startswith('lang_'):
                                                    # Language selection
                                                    if list_id == "lang_en":
                                                        task_service.save_language_preference(f"whatsapp:{from_number}", 'en', 'English')
                                                    elif list_id == "lang_hi":
                                                        task_service.save_language_preference(f"whatsapp:{from_number}", 'hi', 'Hindi')
                                                    elif list_id == "lang_es":
                                                        task_service.save_language_preference(f"whatsapp:{from_number}", 'es', 'Spanish')
                                                elif list_id == "back_settings":
                                                    # Return to settings
                                                    task_service.show_settings_menu(member, f"whatsapp:{from_number}", 'en')
                                                elif list_id.startswith('property_'):
                                                    # Property selection from property list
                                                    property_id = list_id.replace('property_', '')
                                                    logger.info(f"🎯 Property selected: ID={property_id}, Name={list_title}")
                                                    task_service.handle_property_selection_result(f"whatsapp:{from_number}", property_id, list_title)
                                                else:
                                                    # Send list title as regular message
                                                    task_service.handle_message(f"whatsapp:{from_number}", list_title, None)
                                            else:
                                                logger.error(f"Member not found for {from_number}")
                                                # Fallback to regular message handling
                                                task_service.handle_message(f"whatsapp:{from_number}", list_title, None)
                                
                                else:
                                    logger.info(f"⚠️ Unhandled message type: {message_type}")
                            
                            except Exception as e:
                                # Log error but don't crash - return 200 to Meta
                                logger.error(f"Error processing message: {e}")
                                import traceback
                                traceback.print_exc()
                                return '', 200  # IMPORTANT: Return 200 even on error
                    
                    elif 'statuses' in value:
                        # This is a status update for a message we sent (ignore to reduce logs)
                        pass
        
        return '', 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        # Still return 200 to Meta to prevent retries
        return '', 200
    
@app.route('/whatsapp/webhook', methods=['GET'])
def verify_webhook():
    """Verify webhook for Facebook/Meta WhatsApp Business API"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    # Your verify token (should match what you set in Meta Developer Portal)
    verify_token = os.getenv('META_VERIFY_TOKEN', 'your-verify-token')
    
    logger.info(f"Webhook verification attempt - Mode: {mode}, Token: {token}")
    
    if mode == 'subscribe' and token == verify_token:
        logger.info("✅ Webhook verified successfully")
        return challenge, 200
    else:
        logger.error("❌ Webhook verification failed")
        return jsonify({"error": "Verification failed"}), 403

@app.route('/debug', methods=['GET'])
def debug_info():
    """Debug endpoint to check application status"""
    from models.team_member import TeamMember
    team_member_model = TeamMember(DB_CONFIG)
    
    member = team_member_model.find_by_phone('7667130178')
    
    return jsonify({
        "status": "running",
        "member_exists": bool(member),
        "member_details": member if member else None,
        "database_connected": bool(get_db_connection())
    })
@app.route('/send-test-reminder/<int:task_id>', methods=['POST'])
def send_test_reminder(task_id):
    """Endpoint to test reminder for a specific task"""
    try:
        success = reminder_service.send_immediate_reminder(task_id)
        if success:
            return jsonify({"status": "success", "message": "Test reminder sent"})
        else:
            return jsonify({"status": "error", "message": "Failed to send test reminder"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500    

@app.route('/test-whatsapp/<phone_number>', methods=['POST'])
def test_whatsapp(phone_number):
    """Test endpoint to send a WhatsApp message"""
    try:
        from services.whatsapp_service import WhatsAppService
        whatsapp_service = WhatsAppService()
        
        test_message = "🔔 Test message from your Team Management Bot\n\nThis is a test to verify WhatsApp messaging is working."
        
        success = whatsapp_service.send_message(phone_number, test_message, 'en')
        
        if success:
            return jsonify({
                "status": "success", 
                "message": f"Test message sent to {phone_number}",
                "cleaned_number": phone_number
            })
        else:
            return jsonify({
                "status": "error", 
                "message": f"Failed to send test message to {phone_number}"
            }), 400
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Check existing data instead of creating sample data
    print("🔍 Checking existing data...")
    check_existing_data()
    
    # Start the reminder scheduler
    print("🔔 Starting reminder scheduler...")
    reminder_service.start_reminder_scheduler()
    
    # Run the application
    port = int(os.getenv('PORT', 7000))
    logger.info(f"Starting Flask app on port {port}")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=True)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        reminder_service.stop_reminder_scheduler()