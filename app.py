from flask import Flask, request, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import logging
from services.task_service import TaskService

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
def get_database():
    client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://31.97.230.38:27017/'))
    return client['team_management']

# Initialize services
db = get_database()
task_service = TaskService(db)

def initialize_sample_data():
    """Initialize sample user and tasks for testing"""
    from models.user import User
    from models.task import Task
    
    user_model = User(db)
    task_model = Task(db)
    
    # Check if sample user exists
    sample_user = user_model.find_by_phone('917667130178')
    if not sample_user:
        print("Creating sample user...")
        user_id = user_model.create_user(
            phone_number='917667130178',
            name='Shiva',
            role='member'
        )
        
        # Create sample tasks with property names
        task_model.create_task(
            title="Check shampoo bottles in bathroom",
            description="Verify shampoo bottles are filled and replace if needed in master and guest bathrooms",
            assigned_to=user_id,
            assigned_by=user_id,
            priority="medium",
            property_name="Seaside Apartments"
        )
        
        task_model.create_task(
            title="Deep clean kitchen.",
            description="Clean kitchen countertops, sanitize sink, wipe down appliances, and mop floor",
            assigned_to=user_id,
            assigned_by=user_id,
            priority="high",
            property_name="Ocean View Villa"
        )
        
        task_model.create_task(
            title="Replace toilet paper.",
            description="Check and refill toilet paper in all bathrooms, ensure backup rolls are available",
            assigned_to=user_id,
            assigned_by=user_id,
            priority="low",
            property_name="Mountain Lodge"
        )
        
        task_model.create_task(
            title="Vacuum living room carpet",
            description="Vacuum all carpeted areas in living room and dining area, spot clean any stains",
            assigned_to=user_id,
            assigned_by=user_id,
            priority="medium",
            property_name="Beachfront Cottage"
        )
        
        task_model.create_task(
            title="Check coffee supplies in kitchen",
            description="Ensure coffee pods, filters, and sugar packets are stocked for guest arrival",
            assigned_to=user_id,
            assigned_by=user_id,
            priority="low",
            property_name="City Center Loft"
        )
        
        print("✅ Sample data created successfully!")
    else:
        print("✅ Sample user already exists")

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
    from models.user import User
    user_model = User(db)
    
    user = user_model.find_by_phone('917667130178')
    
    return jsonify({
        "status": "running",
        "user_exists": bool(user),
        "user_details": {
            "name": user.get('name') if user else None,
            "phone": user.get('phone_number') if user else None
        } if user else None
    })

if __name__ == '__main__':
    # Initialize sample data
    initialize_sample_data()
    
    # Run the application
    port = int(os.getenv('PORT', 7000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)