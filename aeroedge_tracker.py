"""
AeroEdge Usage Tracking Module for Dash/Flask Applications

This module provides middleware and decorators for tracking page views,
feature usage, and custom events in AeroEdge Dash applications.

Usage:
    from aeroedge_tracker import init_tracking, track_feature, track_event

    # Initialize on Flask server
    server = app.server
    init_tracking(server)

    # Decorate functions to track feature usage
    @track_feature('overlay_generate')
    def generate_overlay(...):
        ...

    # Track custom events
    track_event('template_selected', {'template': 'marketing_v2'})
"""

import hashlib
import time
import os
import threading
from functools import wraps
from typing import Optional, Callable, Any
import requests
from flask import request, g, has_request_context

# Configuration
TRACKING_API_URL = os.environ.get('TRACKING_API_URL', 'https://aeroedge-tracking-api.onrender.com')
PROJECT_SLUG = os.environ.get('PROJECT_SLUG', 'overlay-tool')
IP_HASH_SALT = os.environ.get('IP_HASH_SALT', 'aeroedge')
TRACKING_ENABLED = os.environ.get('TRACKING_ENABLED', 'true').lower() == 'true'
TRACKING_TIMEOUT = 0.5  # seconds - fire-and-forget timeout


def hash_ip(ip: str) -> str:
    """Hash IP address for privacy"""
    if not ip:
        return 'unknown'
    return hashlib.sha256(f"{IP_HASH_SALT}{ip}".encode()).hexdigest()[:16]


def get_client_ip() -> str:
    """Get client IP address, handling proxies"""
    if not has_request_context():
        return 'unknown'

    # Check for forwarded headers (common with proxies/load balancers)
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(',')[0].strip()

    return request.remote_addr or 'unknown'


def _send_async(url: str, data: dict):
    """Send tracking data asynchronously (fire-and-forget)"""
    if not TRACKING_ENABLED:
        return

    def _do_send():
        try:
            requests.post(url, json=data, timeout=TRACKING_TIMEOUT)
        except Exception:
            pass  # Silently fail - tracking should never break the app

    thread = threading.Thread(target=_do_send, daemon=True)
    thread.start()


def init_tracking(app):
    """
    Initialize tracking middleware on a Flask application.

    This sets up before_request and after_request hooks to automatically
    track page views with timing and bandwidth metrics.

    Args:
        app: Flask application instance (typically dash_app.server)
    """
    if not TRACKING_ENABLED:
        return

    @app.before_request
    def before_request():
        g.start_time = time.time()
        g.request_size = request.content_length or 0

    @app.after_request
    def after_request(response):
        # Skip tracking for static files and health checks
        path = request.path
        if any(path.startswith(p) for p in ['/_dash', '/static', '/favicon', '/health', '/assets']):
            return response

        duration_ms = int((time.time() - getattr(g, 'start_time', time.time())) * 1000)
        response_size = response.content_length or 0

        # Try to get actual response size if content_length is None
        if response_size == 0:
            try:
                response_size = len(response.get_data())
            except Exception:
                pass

        _send_async(f"{TRACKING_API_URL}/track/pageview", {
            'project_slug': PROJECT_SLUG,
            'hashed_ip': hash_ip(get_client_ip()),
            'route': path,
            'user_agent': request.user_agent.string if request.user_agent else None,
            'response_bytes': response_size
        })

        return response


def track_feature(
    feature_key: str,
    metadata_fn: Optional[Callable[..., dict]] = None
):
    """
    Decorator to track feature usage.

    Args:
        feature_key: Unique identifier for the feature (e.g., 'overlay_generate')
        metadata_fn: Optional function that takes the same args as the decorated
                    function and returns metadata dict to include in tracking

    Example:
        @track_feature('overlay_generate')
        def generate_overlay(template, assets):
            ...

        @track_feature('final_export', lambda t, f: {'format': f})
        def export(template, format):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            duration_ms = int((time.time() - start) * 1000)

            # Estimate response size
            response_bytes = 0
            if result is not None:
                try:
                    if hasattr(result, '__len__'):
                        response_bytes = len(result)
                    elif isinstance(result, (dict, list)):
                        import json
                        response_bytes = len(json.dumps(result))
                except Exception:
                    pass

            # Get metadata if function provided
            metadata = None
            if metadata_fn:
                try:
                    metadata = metadata_fn(*args, **kwargs)
                except Exception:
                    pass

            # Get request context info if available
            hashed_ip = None
            request_bytes = 0
            if has_request_context():
                hashed_ip = hash_ip(get_client_ip())
                request_bytes = getattr(g, 'request_size', 0)

            _send_async(f"{TRACKING_API_URL}/track/feature", {
                'project_slug': PROJECT_SLUG,
                'feature_key': feature_key,
                'hashed_ip': hashed_ip,
                'request_bytes': request_bytes,
                'response_bytes': response_bytes,
                'duration_ms': duration_ms,
                'metadata': metadata
            })

            return result
        return wrapper
    return decorator


def track_event(event_name: str, metadata: Optional[dict] = None):
    """
    Track a custom event.

    Args:
        event_name: Name of the event (e.g., 'template_selected', 'error_occurred')
        metadata: Optional dictionary of additional event data

    Example:
        track_event('simulation_started', {'complexity': 'high', 'duration': 30})
    """
    hashed_ip = None
    if has_request_context():
        hashed_ip = hash_ip(get_client_ip())

    _send_async(f"{TRACKING_API_URL}/track/event", {
        'project_slug': PROJECT_SLUG,
        'event_name': event_name,
        'hashed_ip': hashed_ip,
        'metadata': metadata
    })


def log_feature(feature_key: str, metadata: Optional[dict] = None, response_bytes: int = 0):
    """
    Log feature usage directly (non-decorator version).

    Use this inside Dash callbacks or anywhere you want to track feature usage
    without using a decorator or context manager.

    Args:
        feature_key: Unique identifier for the feature (e.g., 'maneuver_select')
        metadata: Optional dictionary with details (e.g., {'maneuver': 'steep_turn'})
        response_bytes: Optional size of response data

    Example:
        @app.callback(...)
        def update_maneuver(selected):
            log_feature('maneuver_select', {'maneuver': selected})
            return ...
    """
    hashed_ip = None
    request_bytes = 0
    if has_request_context():
        hashed_ip = hash_ip(get_client_ip())
        request_bytes = getattr(g, 'request_size', 0)

    _send_async(f"{TRACKING_API_URL}/track/feature", {
        'project_slug': PROJECT_SLUG,
        'feature_key': feature_key,
        'hashed_ip': hashed_ip,
        'request_bytes': request_bytes,
        'response_bytes': response_bytes,
        'duration_ms': 0,
        'metadata': metadata
    })


class FeatureTracker:
    """
    Context manager for tracking feature usage with automatic timing.

    Example:
        with FeatureTracker('simulation_run') as tracker:
            result = run_simulation(params)
            tracker.set_metadata({'frames': result.frame_count})
    """

    def __init__(self, feature_key: str):
        self.feature_key = feature_key
        self.start_time = None
        self.metadata = None
        self.response_bytes = 0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)

        hashed_ip = None
        request_bytes = 0
        if has_request_context():
            hashed_ip = hash_ip(get_client_ip())
            request_bytes = getattr(g, 'request_size', 0)

        _send_async(f"{TRACKING_API_URL}/track/feature", {
            'project_slug': PROJECT_SLUG,
            'feature_key': self.feature_key,
            'hashed_ip': hashed_ip,
            'request_bytes': request_bytes,
            'response_bytes': self.response_bytes,
            'duration_ms': duration_ms,
            'metadata': self.metadata
        })

        return False  # Don't suppress exceptions

    def set_metadata(self, metadata: dict):
        """Set metadata to include with the tracking event"""
        self.metadata = metadata

    def set_response_bytes(self, size: int):
        """Set the response size in bytes"""
        self.response_bytes = size
