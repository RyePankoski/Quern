import os
from dotenv import load_dotenv
load_dotenv()
print(repr(os.getenv("SECRET_KEY")))