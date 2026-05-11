"""
Frontend SPA Handler - Serve Next.js static files with fallback
"""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
import os

router = APIRouter()

WEB_DIR = "/opt/fim/web"

@router.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """
    Serve Next.js static files with SPA fallback
    """
    # Try exact file match first
    file_path = os.path.join(WEB_DIR, full_path)
    
    # If it's a file and exists, serve it
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Check for .html extension
    html_path = file_path + ".html"
    if os.path.isfile(html_path):
        return FileResponse(html_path)
    
    # Check for index.html in directory
    index_path = os.path.join(file_path, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    
    # Fallback to root index.html for SPA routing
    root_index = os.path.join(WEB_DIR, "index.html")
    if os.path.isfile(root_index):
        return FileResponse(root_index)
    
    # If nothing found, return 404
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not Found")
