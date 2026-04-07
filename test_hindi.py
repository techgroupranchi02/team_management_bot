from app import DB_CONFIG
from services.task_service import TaskService

ts = TaskService(DB_CONFIG)

def mock_send_message(to, message, language='en', buttons=None):
    print(f"SENDING TO {to} IN {language}:")
    print(message)
    if buttons:
        print(f"BUTTONS: {buttons}")
    return True

ts.whatsapp_service.send_message = mock_send_message
ts.handle_message("7667130178", "कार्य")
