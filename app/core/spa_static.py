"""
SPA-aware static file serving
Serves index.html for all routes that don't match files or API endpoints
"""
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 404:
            # Serve index.html for all non-file routes (SPA routing)
            response = await super().get_response("index.html", scope)
        return response
