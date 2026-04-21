from flask import Flask, request, jsonify
import mysql.connector
from dotenv import load_dotenv
import os
import logging
import json
import hmac
import hashlib
import functools
import signal
import time
import threading
import queue
from collections import OrderedDict
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from utils.helpers import normalize_phone
from services.task_service import TaskService
from services.reminder_service import ReminderService

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://"
)

# Message deduplication cache (message_id -> timestamp)
class MessageDeduplicationCache:
    """Thread-safe LRU cache with TTL for deduplicating webhook messages"""
    def __init__(self, max_size=10000, ttl_seconds=300):
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def is_duplicate(self, message_id):
        """Returns True if message was already processed (duplicate)"""
        now = time.time()
        with self._lock:
            # Check if exists and not expired
            if message_id in self._cache:
                if now - self._cache[message_id] < self._ttl:
                    return True
                else:
                    del self._cache[message_id]
            # Add to cache
            self._cache[message_id] = now
            # Evict oldest if over capacity
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
            return False

processed_messages = MessageDeduplicationCache()

def redact_phone(phone):
    """Redact phone number for logging, keeping last 4 digits"""
    if not phone:
        return '***'
    phone_str = str(phone)
    if len(phone_str) > 4:
        return '***' + phone_str[-4:]
    return '***'

def verify_webhook_signature(req):
    """Validate the HMAC-SHA256 signature from Meta using App Secret"""
    app_secret = os.getenv('META_APP_SECRET')
    if not app_secret:
        logger.warning("META_APP_SECRET not configured, skipping signature verification")
        return True  # Allow if not configured (dev mode)
    signature = req.headers.get('X-Hub-Signature-256', '')
    if not signature:
        return False
    expected = 'sha256=' + hmac.new(
        app_secret.encode(),
        req.data,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

def require_admin_auth(f):
    """Decorator to protect admin/debug endpoints"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # Disable debug endpoints in production
        if os.getenv('FLASK_ENV') == 'production':
            return jsonify({"error": "Endpoint disabled in production"}), 403
        # Check for admin API key
        admin_key = os.getenv('ADMIN_API_KEY')
        if admin_key:
            provided_key = request.headers.get('X-Admin-Key', '')
            if not hmac.compare_digest(provided_key, admin_key):
                return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    return decorated

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
from models.db_pool import init_pool
init_pool(DB_CONFIG, pool_size=10)
from models.bot_session import BotSession
from models.analytics import Analytics
bot_session = BotSession(DB_CONFIG)
analytics = Analytics(DB_CONFIG)
task_service = TaskService(DB_CONFIG, bot_session=bot_session, analytics=analytics)
reminder_service = ReminderService(DB_CONFIG)

# ── Async message processing queue (8.1) ──────────────────
_message_queue = queue.Queue(maxsize=500)

def _process_message_worker():
    """Worker thread that drains the message queue."""
    while True:
        try:
            func, args, kwargs = _message_queue.get(timeout=5)
        except queue.Empty:
            # Periodically flush analytics
            analytics.flush()
            continue
        try:
            func(*args, **kwargs)
        except Exception:
            logger.error("Error in async message worker", exc_info=True)
        finally:
            _message_queue.task_done()

# Start 2 worker threads (safe because Gunicorn worker is single-process)
for _i in range(2):
    _t = threading.Thread(target=_process_message_worker, daemon=True)
    _t.start()

# Start reminder scheduler at module level (needed for Gunicorn)
reminder_service.start_reminder_scheduler()

@app.route('/')
def home():
    return jsonify({"message": "Team Management WhatsApp Bot is running!"})

@app.route('/whatsapp/webhook', methods=['POST'])
@limiter.limit("60 per minute")
def whatsapp_webhook():
    try:
        # Verify webhook signature from Meta
        if not verify_webhook_signature(request):
            logger.warning("Invalid webhook signature received")
            return jsonify({"error": "Invalid signature"}), 403

        # Meta sends JSON data, not form data
        data = request.get_json()
        
        if not data or 'entry' not in data:
            return '', 200
        
        # Process each entry
        for entry in data['entry']:
            for change in entry.get('changes', []):
                if change.get('field') == 'messages':
                    value = change.get('value', {})
                    
                    if 'messages' in value:
                        messages = value.get('messages', [])
                        contacts = value.get('contacts', [])
                        
                        if messages:
                            message = messages[0]
                            message_id = message.get('id', '')
                            
                            if message_id and processed_messages.is_duplicate(message_id):
                                logger.info(f"Skipping duplicate message: {message_id}")
                                continue
                            
                            message_type = message.get('type')
                            from_number = message.get('from', '')
                            phone = normalize_phone(from_number)
                            
                            # Get member info
                            member = task_service.team_member_model.find_by_phone(phone)
                            
                            # Check if user has an active client preference
                            if member:
                                active_cid = task_service.get_active_client(phone)
                                if active_cid and member.get('client_id') != active_cid:
                                    switched = task_service.team_member_model.find_by_phone_and_client(phone, active_cid)
                                    if switched:
                                        member = switched
                            
                            logger.info(f"Message type: {message_type} from: {redact_phone(from_number)}")
                            analytics.log_event('message_received', phone, message_type)
                            
                            # Dispatch to async worker (return 200 immediately)
                            try:
                                _dispatch_message(message, message_type, from_number, phone, member, contacts)
                            except queue.Full:
                                logger.error("Message queue full, dropping message")
        
        return '', 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return '', 200


def _dispatch_message(message, message_type, from_number, phone, member, contacts):
    """Parse message and push work item to async queue."""
    if message_type == 'text':
        incoming_msg = message.get('text', {}).get('body', '').strip()
        if not incoming_msg:
            return
        if incoming_msg.lower().startswith('join'):
            logger.info(f"Join command received: {incoming_msg}")
            return
        _message_queue.put_nowait((
            task_service.handle_message,
            (f"whatsapp:{from_number}", incoming_msg, None),
            {},
        ))

    elif message_type == 'image':
        image_data = message.get('image', {})
        media_id = image_data.get('id', '')
        caption = image_data.get('caption', '')
        _message_queue.put_nowait((
            task_service.handle_message,
            (f"whatsapp:{from_number}", caption or "", media_id),
            {},
        ))

    elif message_type == 'audio':
        audio_data = message.get('audio', {})
        media_id = audio_data.get('id', '')
        _message_queue.put_nowait((
            task_service.handle_voice_message,
            (f"whatsapp:{from_number}", media_id),
            {},
        ))

    elif message_type == 'interactive':
        interactive_data = message.get('interactive', {})
        interactive_type = interactive_data.get('type')

        if interactive_type == 'button_reply':
            button_reply = interactive_data.get('button_reply', {})
            if button_reply:
                button_id = button_reply.get('id', '')
                title = button_reply.get('title', '')
                logger.info(f"Button click: {button_id} - {title}")
                _message_queue.put_nowait((
                    task_service.handle_message,
                    (f"whatsapp:{from_number}", title, None),
                    {"button_id": button_id},
                ))

        elif interactive_type == 'list_reply':
            list_reply = interactive_data.get('list_reply', {})
            if list_reply:
                _message_queue.put_nowait((
                    _handle_list_reply,
                    (list_reply, from_number, member),
                    {},
                ))
    else:
        # Unsupported message type
        try:
            unsupported_msg = "📎 I can only process text, images, and voice messages. Please send your request in one of these formats."
            task_service.whatsapp_service.send_message(
                f"whatsapp:{from_number}", unsupported_msg, 'en'
            )
        except Exception:
            pass


def _handle_list_reply(list_reply, from_number, member):
    """Handle interactive list replies (runs in worker thread)."""
    list_id = list_reply.get('id', '')
    list_title = list_reply.get('title', '')
    logger.info(f"List selection: {list_id} - {list_title}")

    if member:
        if list_id == "property_info":
            task_service.show_current_property_info(member, f"whatsapp:{from_number}", 'en')
        elif list_id == "property_change":
            task_service.show_property_selection_menu(member, f"whatsapp:{from_number}", 'en')
        elif list_id == "back_main":
            task_service.show_main_menu(member, f"whatsapp:{from_number}", 'en')
        elif list_id == "language_change":
            task_service.handle_language_change(member, f"whatsapp:{from_number}", 'en')
        elif list_id.startswith('lang_'):
            lang_code = list_id.replace('lang_', '')
            lang_name = list_title
            task_service.save_language_preference(f"whatsapp:{from_number}", lang_code, lang_name)
        elif list_id == "back_settings":
            task_service.show_settings_menu(member, f"whatsapp:{from_number}", 'en')
        elif list_id == "client_change":
            task_service.show_client_selection_menu(member, f"whatsapp:{from_number}", 'en')
        elif list_id.startswith('switch_client_'):
            client_id = list_id.replace('switch_client_', '')
            user_language = task_service._get_user_language(f"whatsapp:{from_number}", '')
            try:
                matched_client = task_service.task_model.get_client_by_id(int(client_id))
                if not matched_client:
                    matched_client = {'id': int(client_id), 'name': list_title}
                task_service._do_client_switch(member, f"whatsapp:{from_number}", matched_client, user_language)
            except Exception as e:
                logger.error(f"Error switching client: {e}", exc_info=True)
                task_service.whatsapp_service.send_message(f"whatsapp:{from_number}", "❌ Failed to switch client. Please try again.", 'en')
        elif list_id.startswith('property_'):
            property_id = list_id.replace('property_', '')
            task_service.handle_property_selection_result(f"whatsapp:{from_number}", property_id, list_title)
        elif list_id.startswith('inv_prop_'):
            property_id = list_id.replace('inv_prop_', '')
            user_language = task_service._get_user_language(f"whatsapp:{from_number}", '')
            task_service.handle_property_inventory_selection(member, f"whatsapp:{from_number}", property_id, user_language)
        else:
            task_service.handle_message(f"whatsapp:{from_number}", list_title, None)
    else:
        task_service.handle_message(f"whatsapp:{from_number}", list_title, None)
    
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
@require_admin_auth
def debug_info():
    """Debug endpoint to check application status (protected)"""
    conn = get_db_connection()
    db_ok = bool(conn)
    if conn:
        try:
            conn.close()
        except Exception:
            pass
    return jsonify({
        "status": "running",
        "database_connected": db_ok
    })
@app.route('/send-test-reminder/<int:task_id>', methods=['POST'])
@require_admin_auth
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
@require_admin_auth
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

# ── Health check (7.1) ─────────────────────────────────────
@app.route('/health', methods=['GET'])
def health_check():
    """Comprehensive health endpoint for monitoring."""
    import psutil, os as _os
    checks = {}

    # DB connectivity
    conn = get_db_connection()
    checks['database'] = bool(conn)
    if conn:
        try:
            conn.close()
        except Exception:
            pass

    # Meta token health
    try:
        checks['meta_token'] = task_service.whatsapp_service.check_token_health()
    except Exception:
        checks['meta_token'] = False

    # Reminder scheduler alive
    try:
        thread_alive = (
            reminder_service.reminder_thread is not None
            and reminder_service.reminder_thread.is_alive()
        )
        checks['reminder_scheduler'] = thread_alive
        # Auto-restart if dead
        if reminder_service.is_running and not thread_alive:
            logger.warning("Reminder scheduler thread died — restarting")
            reminder_service.is_running = False
            reminder_service.start_reminder_scheduler()
            checks['reminder_scheduler_restarted'] = True
    except Exception:
        checks['reminder_scheduler'] = False

    # Process stats
    proc = psutil.Process(_os.getpid())
    checks['memory_mb'] = round(proc.memory_info().rss / 1024 / 1024, 1)
    checks['uptime_seconds'] = round(time.time() - _app_start_time)
    checks['message_queue_size'] = _message_queue.qsize()

    healthy = checks['database'] and checks.get('meta_token', False)
    status_code = 200 if healthy else 503

    return jsonify({"healthy": healthy, "checks": checks}), status_code

_app_start_time = time.time()


# ── Admin notification helper (8.4) ────────────────────────
def _notify_admins(message):
    """Send a WhatsApp alert to admin numbers on critical errors."""
    admin_phones = os.getenv('ADMIN_PHONE_NUMBERS', '').split(',')
    for phone in admin_phones:
        phone = phone.strip()
        if phone:
            try:
                task_service.whatsapp_service.send_message(phone, message, 'en')
            except Exception:
                logger.error(f"Failed to notify admin {phone}")


# ── Graceful shutdown (7.4) ────────────────────────────────
def _graceful_shutdown(signum, frame):
    logger.info("Received signal %s — shutting down gracefully", signum)
    reminder_service.stop_reminder_scheduler()
    analytics.flush()
    from models.db_pool import _pool
    if _pool:
        logger.info("Closing connection pool")
    logger.info("Shutdown complete")

signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


if __name__ == '__main__':
    # Start the reminder scheduler
    logger.info("Starting reminder scheduler...")
    reminder_service.start_reminder_scheduler()
    
    # Run the application
    port = int(os.getenv('PORT', 7000))
    logger.info(f"Starting Flask app on port {port}")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_ENV') == 'development')
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        reminder_service.stop_reminder_scheduler()
        analytics.flush()