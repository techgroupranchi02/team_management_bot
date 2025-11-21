from datetime import datetime
from bson import ObjectId

class Team:
    def __init__(self, db):
        self.collection = db.teams

    def create_team(self, name, admin_id, description=None):
        team_data = {
            "name": name,
            "description": description,
            "admin": ObjectId(admin_id),
            "members": [ObjectId(admin_id)],
            "created_at": datetime.utcnow()
        }
        result = self.collection.insert_one(team_data)
        return result.inserted_id

    def add_member(self, team_id, user_id):
        result = self.collection.update_one(
            {"_id": ObjectId(team_id)},
            {"$addToSet": {"members": ObjectId(user_id)}}
        )
        return result.modified_count > 0