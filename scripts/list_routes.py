import sys
import os
sys.path.append("/opt/fim")

from app.main import app

print("Registered Routes:")
for route in app.routes:
    methods = getattr(route, "methods", None)
    if methods:
        print(f"{list(methods)} {route.path}")
