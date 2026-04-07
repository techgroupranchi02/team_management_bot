from app import DB_CONFIG
from services.task_service import TaskService

ts = TaskService(DB_CONFIG)
prefs = ts.get_user_preferences("7667130178")
print(f"Preferences: {prefs}")
