from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

@app.route("/healthz")
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "dashboard",
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/")
def dashboard():
    """Main dashboard page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FraudGuard Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-4">
            <h1>🛡️ FraudGuard Dashboard</h1>
            <p class="lead">Real-time transaction risk monitoring</p>
            
            <div class="row mb-4">
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title text-danger">🚨 High Risk</h5>
                            <h2 class="card-text">0</h2>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title text-warning">⚠️ Medium Risk</h5>
                            <h2 class="card-text">1</h2>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title text-info">⚡ Low Risk</h5>
                            <h2 class="card-text">0</h2>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title text-success">✅ Normal</h5>
                            <h2 class="card-text">1</h2>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h5>Recent Transactions</h5>
                </div>
                <div class="card-body">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Transaction ID</th>
                                <th>Risk Score</th>
                                <th>Action</th>
                                <th>Explanation</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><code>demo_001</code></td>
                                <td><span class="badge bg-success">20%</span></td>
                                <td>✅ Allow</td>
                                <td>Normal transaction pattern</td>
                            </tr>
                            <tr>
                                <td><code>demo_002</code></td>
                                <td><span class="badge bg-warning">70%</span></td>
                                <td>⚠️ Review</td>
                                <td>Unusual transaction amount</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
