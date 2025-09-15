#!/usr/bin/env python3
"""
Ultra-minimal debug version of FraudGuard Dashboard
"""

import sys
import traceback
import logging
from datetime import datetime

# Configure basic logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from flask import Flask
    logger.info("Flask imported successfully")
except Exception as e:
    logger.error(f"Failed to import Flask: {e}")
    sys.exit(1)

app = Flask(__name__)
logger.info("Flask app created successfully")

@app.route("/healthz")
def health_check():
    """Health check endpoint"""
    try:
        logger.info("Health check called")
        response = {
            "status": "healthy",
            "service": "dashboard-debug",
            "timestamp": datetime.utcnow().isoformat(),
            "python_version": sys.version,
            "flask_version": getattr(Flask, '__version__', 'unknown')
        }
        logger.info(f"Health check response: {response}")
        return response
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        logger.error(traceback.format_exc())
        return {"error": str(e)}, 500

@app.route("/")
def dashboard():
    """Main dashboard page with extensive error handling"""
    try:
        logger.info("Dashboard route called")
        
        # Test basic string return
        html_content = """<!DOCTYPE html>
<html>
<head>
    <title>FraudGuard Debug Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .status { color: green; font-weight: bold; }
        .debug { background: #f0f0f0; padding: 10px; margin: 10px 0; }
    </style>
</head>
<body>
    <h1>🛡️ FraudGuard Debug Dashboard</h1>
    <p class="status">✅ Dashboard is working!</p>
    
    <div class="debug">
        <h3>Debug Information:</h3>
        <p><strong>Timestamp:</strong> """ + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC") + """</p>
        <p><strong>Python Version:</strong> """ + sys.version + """</p>
        <p><strong>Flask Version:</strong> """ + getattr(Flask, '__version__', 'unknown') + """</p>
        <p><strong>Route:</strong> /</p>
        <p><strong>Method:</strong> GET</p>
    </div>
    
    <div class="debug">
        <h3>Test Data:</h3>
        <table border="1" style="border-collapse: collapse;">
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>High Risk Transactions</td><td>0</td></tr>
            <tr><td>Medium Risk Transactions</td><td>1</td></tr>
            <tr><td>Low Risk Transactions</td><td>0</td></tr>
            <tr><td>Normal Transactions</td><td>1</td></tr>
        </table>
    </div>
    
    <p><em>This is a debug version with no external dependencies.</em></p>
</body>
</html>"""
        
        logger.info("HTML content generated successfully")
        logger.info(f"HTML content length: {len(html_content)} characters")
        
        return html_content
        
    except Exception as e:
        logger.error(f"Dashboard route failed: {e}")
        logger.error(traceback.format_exc())
        
        error_html = f"""<!DOCTYPE html>
<html>
<head><title>Dashboard Error</title></head>
<body>
    <h1>Dashboard Error</h1>
    <p>Error: {str(e)}</p>
    <pre>{traceback.format_exc()}</pre>
</body>
</html>"""
        return error_html, 500

@app.route("/debug")
def debug_info():
    """Debug information endpoint"""
    try:
        import os
        debug_data = {
            "environment_variables": dict(os.environ),
            "python_path": sys.path,
            "working_directory": os.getcwd(),
            "flask_app": str(app),
            "routes": [str(rule) for rule in app.url_map.iter_rules()],
            "timestamp": datetime.utcnow().isoformat()
        }
        return debug_data
    except Exception as e:
        logger.error(f"Debug info failed: {e}")
        return {"error": str(e)}, 500

if __name__ == "__main__":
    logger.info("Starting Flask app in debug mode")
    try:
        app.run(host="0.0.0.0", port=8080, debug=True)
    except Exception as e:
        logger.error(f"Failed to start Flask app: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
