"""
WSGI entry point for Gunicorn.

Usage:
    gunicorn wsgi:server
"""

from app import server

if __name__ == "__main__":
    server.run()
