from flask import Flask, request, jsonify
import mysql.connector
from dotenv import load_dotenv
import os
import logging
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
    'host': os.getenv('DB_HOST', '31.97.230.38'),
    'port': int(os.getenv('DB_PORT', 4000)),
    'user': os.getenv('DB_USER', 'mysqluser'),
    'password': os.getenv('DB_PASSWORD', 'mysqlpassword'),
    'database': os.getenv('DB_NAME', 'airbnb_db_copy'),
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
        # Log all incoming data for debugging
        logger.info(f"Incoming request form data: {dict(request.form)}")
        
        # Get incoming message data
        incoming_msg = request.form.get('Body', '').strip()
        from_number = request.form.get('From', '')
        media_url = request.form.get('MediaUrl0')
        media_content_type = request.form.get('MediaContentType0', '')
        
        logger.info(f"Received from {from_number}: {incoming_msg}")
        if media_url:
            logger.info(f"Media detected: {media_url} (Type: {media_content_type})")
        
        # Check if message contains media
        if media_url and media_content_type.startswith('image/'):
            logger.info("Processing image upload...")
            task_service.handle_message(from_number, "", media_url)
        elif incoming_msg.lower().startswith('join'):
            # Handle join command separately
            logger.info(f"Join command received: {incoming_msg}")
        else:
            # Process text message
            task_service.handle_message(from_number, incoming_msg, None)
        
        return '', 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return '', 500

@app.route('/whatsapp/webhook', methods=['GET'])
def verify_webhook():
    """Verify webhook for Twilio"""
    challenge = request.args.get('hub.challenge', '')
    logger.info(f"Webhook verification challenge: {challenge}")
    return challenge, 200

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