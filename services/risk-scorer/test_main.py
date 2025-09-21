"""
Unit tests for Risk Scorer service
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime

from main import app, create_risk_analysis_prompt, call_gemini_api, send_to_explain_agent

client = TestClient(app)

class TestHealthCheck:
    """Test health check endpoint"""

    def test_health_check(self):
        """Test health check returns 200 and correct format"""
        response = client.get("/healthz")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "risk-scorer"
        assert "timestamp" in data

class TestPromptCreation:
    """Test risk analysis prompt creation"""

    def test_create_risk_analysis_prompt(self):
        """Test that prompt is created with transaction data"""
        from main import Transaction

        transaction = Transaction(
            transaction_id="test_001",
            account_id="acc_001",
            amount=100.50,
            merchant="grocery_store",
            category="grocery",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            location="San Francisco"
        )

        prompt = create_risk_analysis_prompt(transaction)

        assert "$100.50" in prompt
        assert "Account ID: acc_001" in prompt
        assert "Timestamp:" in prompt
        assert "risk_score" in prompt
        assert "rationale" in prompt

class TestGeminiAPI:
    """Test Gemini API integration"""

    @pytest.mark.asyncio
    async def test_call_gemini_api_mock_response(self):
        """Test Gemini API call with mock response"""
        prompt = "Test prompt for risk analysis"

        result = await call_gemini_api(prompt)

        assert "risk_score" in result
        assert "rationale" in result
        assert isinstance(result["risk_score"], float)
        assert 0.0 <= result["risk_score"] <= 1.0
        assert isinstance(result["rationale"], str)
        assert len(result["rationale"]) > 0

    @pytest.mark.asyncio
    async def test_call_gemini_api_high_risk_pattern(self):
        """Test that high-risk patterns are detected"""
        prompt = "online transaction $500 at 22:30"

        result = await call_gemini_api(prompt)

        # Should detect high risk for late night high-value online transaction
        assert result["risk_score"] >= 0.5

    @pytest.mark.asyncio
    async def test_call_gemini_api_low_risk_pattern(self):
        """Test that low-risk patterns are detected"""
        prompt = "grocery transaction $25 at 14:00"

        result = await call_gemini_api(prompt)

        # Should detect low risk for normal grocery transaction
        assert result["risk_score"] <= 0.5

class TestExplainAgentIntegration:
    """Test integration with explain agent"""

    @pytest.mark.asyncio
    async def test_send_to_explain_agent_success(self):
        """Test successful sending to explain agent"""
        from main import RiskScore

        risk_result = RiskScore(
            transaction_id="test_explain_001",
            risk_score=0.7,
            rationale="Test rationale",
            timestamp=datetime.utcnow()
        )

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            # Should not raise an exception
            await send_to_explain_agent(risk_result)

    @pytest.mark.asyncio
    async def test_send_to_explain_agent_http_error(self):
        """Test sending with HTTP error"""
        from main import RiskScore

        risk_result = RiskScore(
            transaction_id="test_explain_002",
            risk_score=0.3,
            rationale="Test rationale",
            timestamp=datetime.utcnow()
        )

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("HTTP Error")
            )

            # Should not raise an exception (errors are logged)
            await send_to_explain_agent(risk_result)

class TestAnalyzeEndpoint:
    """Test the main analyze endpoint"""

    def test_analyze_transaction_success(self):
        """Test successful transaction analysis"""
        transaction_data = {
            "transaction_id": "test_analyze_001",
            "account_id": "acc_test",
            "amount": 75.0,
            "merchant": "restaurant_bar",
            "category": "restaurant",
            "timestamp": "2024-01-01T22:30:00Z",
            "location": "Las Vegas"
        }

        with patch('main.send_to_explain_agent', new_callable=AsyncMock):
            response = client.post("/analyze", json=transaction_data)

            assert response.status_code == 200
            data = response.json()

            assert data["transaction_id"] == transaction_data["transaction_id"]
            assert "risk_score" in data
            assert "rationale" in data
            assert "timestamp" in data
            assert isinstance(data["risk_score"], float)
            assert 0.0 <= data["risk_score"] <= 1.0

    def test_analyze_transaction_invalid_data(self):
        """Test analysis with invalid transaction data"""
        invalid_data = {
            "transaction_id": "test_invalid",
            # Missing required fields
        }

        response = client.post("/analyze", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_analyze_transaction_missing_fields(self):
        """Test analysis with missing required fields"""
        incomplete_data = {
            "transaction_id": "test_incomplete",
            "account_id": "acc_test",
            # Missing amount, merchant, category, timestamp
        }

        response = client.post("/analyze", json=incomplete_data)
        assert response.status_code == 422  # Validation error

class TestErrorHandling:
    """Test error handling"""

    def test_analyze_with_gemini_error(self):
        """Test analysis when Gemini API fails"""
        transaction_data = {
            "transaction_id": "test_error_001",
            "account_id": "acc_test",
            "amount": 100.0,
            "merchant": "test_merchant",
            "category": "test",
            "timestamp": "2024-01-01T12:00:00Z",
            "location": "Test City"
        }

        with patch('main.call_gemini_api', side_effect=Exception("Gemini API Error")):
            with patch('main.send_to_explain_agent', new_callable=AsyncMock):
                response = client.post("/analyze", json=transaction_data)

                # Should still return a response with fallback scoring
                assert response.status_code == 200
                data = response.json()
                assert data["risk_score"] == 0.5  # Fallback score

class TestLogging:
    """Test logging functionality"""

    def test_analysis_logging(self):
        """Test that analysis is properly logged"""
        transaction_data = {
            "transaction_id": "test_log_001",
            "account_id": "acc_test",
            "amount": 50.0,
            "merchant": "test_merchant",
            "category": "test",
            "timestamp": "2024-01-01T12:00:00Z"
        }

        with patch('main.logger') as mock_logger:
            with patch('main.send_to_explain_agent', new_callable=AsyncMock):
                response = client.post("/analyze", json=transaction_data)

                assert response.status_code == 200

                # Verify logging was called
                assert mock_logger.info.called

                # Check for specific log events
                call_args_list = [call[0] for call in mock_logger.info.call_args_list]
                assert any("risk_analysis_started" in args for args in call_args_list)
                assert any("risk_analysis_completed" in args for args in call_args_list)

class TestBusinessRuleEscalation:
    def test_new_recipient_high_amount_escalation(self, monkeypatch):
        # Ensure environment thresholds
        monkeypatch.setenv("NEW_RECIPIENT_HIGH_AMOUNT_THRESHOLD", "999")
        monkeypatch.setenv("NEW_RECIPIENT_MIN_SCORE", "0.8")

        # Mock AI to return a medium score to observe escalation
        async def fake_ai(prompt: str):
            return {"risk_score": 0.55, "rationale": "Medium risk; Amount $1500.00"}

        async def fake_history(account_id: str, limit: int = 100):
            return []  # no history -> new recipient

        from main import send_to_explain_agent
        # Avoid network to explain agent during test
        async def fake_send(_: object):
            return None

        with patch('main.call_gemini_api', new=fake_ai), \
             patch('main.fetch_account_history', new=fake_history), \
             patch('main.send_to_explain_agent', new=fake_send):
            transaction_data = {
                "transaction_id": "test_rule_001",
                "account_id": "acc_test",
                "amount": 1500.0,
                "merchant": "acct:9876543210",
                "label": "acct:9876543210",
                "category": "transfer",
                "timestamp": "2024-01-01T12:00:00Z"
            }
            response = client.post("/analyze", json=transaction_data)
            assert response.status_code == 200
            body = response.json()
            assert body["risk_score"] >= 0.8
            assert "New recipient" in body["rationale"]

if __name__ == "__main__":
    pytest.main([__file__])
