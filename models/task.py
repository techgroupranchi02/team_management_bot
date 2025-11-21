from datetime import datetime
from bson import ObjectId

class Task:
    def __init__(self, db):
        self.collection = db.tasks

    def create_task(self, title, description, assigned_to, assigned_by, priority="medium", due_date=None, property_name=None):
        task_data = {
            "title": title,
            "description": description,
            "assigned_to": ObjectId(assigned_to),
            "assigned_by": ObjectId(assigned_by),
            "status": "pending",
            "priority": priority,
            "due_date": due_date,
            "property_name": property_name,
            "completion_image": None,
            "completed_at": None,
            "created_at": datetime.utcnow()
        }
        result = self.collection.insert_one(task_data)
        return str(result.inserted_id)

    def get_tasks_by_user(self, user_id):
        pipeline = [
            {"$match": {"assigned_to": ObjectId(user_id)}},
            {"$lookup": {
                "from": "users", 
                "localField": "assigned_by",
                "foreignField": "_id",
                "as": "assigner"
            }},
            {"$sort": {"created_at": -1}}
        ]
        tasks = list(self.collection.aggregate(pipeline))
        
        # Convert ObjectId to string for JSON serialization and remove unwanted fields
        for task in tasks:
            task['_id'] = str(task['_id'])
            task['assigned_to'] = str(task['assigned_to'])
            # Remove assigned_by from the response
            if 'assigned_by' in task:
                del task['assigned_by']
            # Remove priority from the response  
            if 'priority' in task:
                del task['priority']
            # Remove assigner array completely since we don't need it
            if 'assigner' in task:
                del task['assigner']
        
        return tasks

    def update_task_status(self, task_id, status, user_id):
        update_data = {"status": status}
        
        if status == "completed":
            update_data["completed_at"] = datetime.utcnow()
            # Clear completion image when task is marked completed again
            update_data["completion_image"] = None
        
        result = self.collection.update_one(
            {"_id": ObjectId(task_id), "assigned_to": ObjectId(user_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0

    def add_completion_image(self, task_id, image_url, user_id):
        """Add completion image URL to task"""
        result = self.collection.update_one(
            {"_id": ObjectId(task_id), "assigned_to": ObjectId(user_id)},
            {"$set": {
                "completion_image": image_url,
                "image_added_at": datetime.utcnow()
            }}
        )
        return result.modified_count > 0

    def get_recent_completed_task(self, user_id):
        """Get most recently completed task without completion image"""
        task = self.collection.find_one({
            "assigned_to": ObjectId(user_id),
            "status": "completed", 
            "completion_image": None
        }, sort=[("completed_at", -1)])
        
        if task:
            task['_id'] = str(task['_id'])
            task['assigned_to'] = str(task['assigned_to'])
            # Remove assigned_by from the response
            if 'assigned_by' in task:
                del task['assigned_by']
            # Remove priority from the response
            if 'priority' in task:
                del task['priority']
            # Remove assigner if it exists
            if 'assigner' in task:
                del task['assigner']
        
        return task

    def get_task_with_images(self, user_id):
        """Get tasks that have completion images"""
        tasks = self.collection.find({
            "assigned_to": ObjectId(user_id),
            "completion_image": {"$ne": None}
        }).sort("completed_at", -1)
        
        task_list = []
        for task in tasks:
            task['_id'] = str(task['_id'])
            task['assigned_to'] = str(task['assigned_to'])
            if 'assigned_by' in task:
                del task['assigned_by']
            task_list.append(task)
        
        return task_list