"""
Dash application factory and server initialization.
"""
import dash
import dash_bootstrap_components as dbc

from .config import APP_TITLE


def create_app():
    """
    Create and configure the Dash application.

    Returns:
        Configured Dash app instance
    """
    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        suppress_callback_exceptions=True,
        prevent_initial_callbacks=True,
        assets_folder="../assets"
    )
    app.title = APP_TITLE
    return app


# Create the singleton app instance
app = create_app()

# Expose Flask server for Gunicorn
server = app.server
