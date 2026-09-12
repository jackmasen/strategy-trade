import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from backend.db.session import SessionLocal
from backend.models.monitor_token import MonitorToken
from datetime import datetime

db = SessionLocal()
tokens = db.query(MonitorToken).all()
now = datetime.now()
if not tokens:
    print("No tokens found in database")
else:
    for t in tokens:
        exp = t.expires_at
        valid = (exp > now) if exp else True
        print(f"token={t.token} created={t.created_at} expires={t.expires_at} valid={valid}")
db.close()
