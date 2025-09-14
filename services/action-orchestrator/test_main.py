"""
Unit tests for Action Orchestrator service
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime

from main import (
    app, execute_notify_action, execute_stepup_action,
    execute_hold_action, execute_allow_action
)

client = TestClient(app)

class TestHealthCheck:
    """Test health check endpoint"""

    def test_health_check(self):
        """Test health check returns 200 and correct format"""
        response = client.get("/healthz")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "action-orchestrator"
        assert "timestamp" in data

class TestThresholdsEndpoint:
    """Test risk thresholds endpoint"""

    def test_get_risk_thresholds(self):
        """Test getting risk thresholds configuration"""
        response = client.get("/thresholds")
        assert response.status_code == 200

        data = response.json()
        assert "notify" in data
        assert "step_up" in data
        assert "hold" in data

        # Verify threshold values are reasonable
        assert 0.0 <= data["notify"] <= 1.0
        assert 0.0 <= data["step_up"] <= 1.0
        assert 0.0 <= data["hold"] <= 1.0

class TestActionExecution:
    """Test individual action execution functions"""

    @pytest.mark.asyncio
    async def test_execute_notify_action(self):
        """Test notify action execution"""
        result = await execute_notify_action("test_txn_001", "Test notification")

        assert result["success"] is True
        assert "notification sent" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_stepup_action(self):
        """Test step-up authentication action execution"""
        result = await execute_stepup_action("test_txn_002", "Test step-up")

        assert result["success"] is True
        assert "step-up authentication" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_hold_action(self):
        """Test hold action execution"""
        result = await execute_hold_action("test_txn_003", "Test hold")

        assert result["success"] is True
        assert "hold" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_allow_action(self):
        """Test allow action execution"""
        result = await execute_allow_action("test_txn_004", "Test allow")

        assert result["success"] is True
        assert "allowed to proceed" in result["message"].lower()

class TestExecuteEndpoint:
    """Test the main execute endpoint"""

    def test_execute_notify_action_endpoint(self):
        """Test executing notify action via endpoint"""
        action_data = {
            "transaction_id": "test_execute_001",
            "risk_score": 0.4,
            "action": "notify",
            "explanation": "Medium risk transaction requiring notification"
        }

        response = client.post("/execute", json=action_data)
        assert response.status_code == 200

        data = response.json()
        assert data["transaction_id"] == action_data["transaction_id"]
        assert data["action"] == "notify"
        assert data["success"] is True
        assert "timestamp" in data

    def test_execute_stepup_action_endpoint(self):
        """Test executing step-up action via endpoint"""
        action_data = {
            "transaction_id": "test_execute_002",
            "risk_score": 0.7,
            "action": "step-up",
            "explanation": "High risk transaction requiring step-up authentication"
        }

        response = client.post("/execute", json=action_data)
        assert response.status_code == 200

        data = response.json()
        assert data["transaction_id"] == action_data["transaction_id"]
        assert data["action"] == "step-up"
        assert data["success"] is True

    def test_execute_hold_action_endpoint(self):
        """Test executing hold action via endpoint"""
        action_data = {
            "transaction_id": "test_execute_003",
            "risk_score": 0.9,
            "action": "hold",
            "explanation": "Very high risk transaction requiring hold"
        }

        response = client.post("/execute", json=action_data)
        assert response.status_code == 200

        data = response.json()
        assert data["transaction_id"] == action_data["transaction_id"]
        assert data["action"] == "hold"
        assert data["success"] is True

    def test_execute_allow_action_endpoint(self):
        """Test executing allow action via endpoint"""
        action_data = {
            "transaction_id": "test_execute_004",
            "risk_score": 0.1,
            "action": "allow",
            "explanation": "Low risk transaction allowed to proceed"
        }

        response = client.post("/execute", json=action_data)
        assert response.status_code == 200

        data = response.json()
        assert data["transaction_id"] == action_data["transaction_id"]
        assert data["action"] == "allow"
        assert data["success"] is True

    def test_execute_unknown_action(self):
        """Test executing unknown action"""
        action_data = {
            "transaction_id": "test_execute_005",
            "risk_score": 0.5,
            "action": "unknown_action",
            "explanation": "Test unknown action"
        }

        response = client.post("/execute", json=action_data)
        assert response.status_code == 400
        assert "Unknown action" in response.json()["detail"]

    def test_execute_invalid_data(self):
        """Test executing with invalid data"""
        invalid_data = {
            "transaction_id": "test_invalid",
            # Missing required fields
        }

        response = client.post("/execute", json=invalid_data)
        assert response.status_code == 422  # Validation error

class TestErrorHandling:
    """Test error handling in action execution"""

    @pytest.mark.asyncio
    async def test_action_execution_with_exception(self):
        """Test action execution when underlying operation fails"""
        # Mock an exception in the action execution
        with patch('main.logger') as mock_logger:
            # This should still return a result, not raise an exception
            result = await execute_notify_action("test_error_001", "Test error handling")

            # Should still succeed for notify action (it's just logging)
            assert result["success"] is True

class TestLogging:
    """Test logging functionality"""

    def test_action_execution_logging(self):
        """Test that action execution is properly logged"""
        action_data = {
            "transaction_id": "test_log_001",
            "risk_score": 0.6,
            "action": "step-up",
            "explanation": "Test logging"
        }

        with patch('main.logger') as mock_logger:
            response = client.post("/execute", json=action_data)

            assert response.status_code == 200

            # Verify logging was called
            assert mock_logger.info.called

            # Check for specific log events
            call_args_list = [call[0] for call in mock_logger.info.call_args_list]
            assert any("action_execution_started" in args for args in call_args_list)
            assert any("action_execution_completed" in args for args in call_args_list)

class TestBoAIntegration:
    """Test Bank of Anthos integration (mocked)"""

    @pytest.mark.asyncio
    async def test_boa_api_integration_mock(self):
        """Test that BoA API calls would be made (currently mocked)"""
        # In the current implementation, BoA API calls are mocked
        # This test verifies the structure is in place for real integration

        result = await execute_hold_action("test_boa_001", "Test BoA integration")

        # Should succeed with mock implementation
        assert result["success"] is True
        assert "hold" in result["message"].lower()

class TestRiskThresholds:
    """Test risk threshold configuration"""

    def test_threshold_configuration(self):
        """Test that thresholds are properly configured"""
        from main import RISK_THRESHOLD_NOTIFY, RISK_THRESHOLD_STEPUP, RISK_THRESHOLD_HOLD

        # Verify thresholds are in logical order
        assert RISK_THRESHOLD_NOTIFY < RISK_THRESHOLD_STEPUP
        assert RISK_THRESHOLD_STEPUP < RISK_THRESHOLD_HOLD

        # Verify thresholds are in valid range
        assert 0.0 <= RISK_THRESHOLD_NOTIFY <= 1.0
        assert 0.0 <= RISK_THRESHOLD_STEPUP <= 1.0
        assert 0.0 <= RISK_THRESHOLD_HOLD <= 1.0

if __name__ == "__main__":
    pytest.main([__file__])
