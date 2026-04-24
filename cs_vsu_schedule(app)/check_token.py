import os
from dotenv import load_dotenv
load_dotenv()
token = os.getenv("BOT_TOKEN")
print(f"Token: '{token}'")
print(f"Length: {len(token)}")
