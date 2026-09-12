import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from backend.db.session import SessionLocal
from backend.services.monitor_service import create_share_token, validate_share_token

db = SessionLocal()
# Create a token with 720 hours (30 days) validity
token_info = create_share_token(db, ttl_hours=720)
print(f"New token: {token_info}")

# Validate it immediately
valid = validate_share_token(token_info.get("token", ""))
print(f"Valid: {valid}")

db.close()
