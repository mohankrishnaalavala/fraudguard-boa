"""
Unit tests for Explain Agent service
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime
import tempfile
import os

from main import app, create_user_friendly_explanation, determine_action, save_audit_record

client = TestClient(app)

class TestHealthCheck:
    """Test health check endpoint"""

    def test_health_check(self):
        """Test health check returns 200 and correct format"""
        response = client.get("/healthz")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "explain-agent"
        assert "timestamp" in data

class TestExplanationGeneration:
    """Test user-friendly explanation generation"""

    def test_create_high_risk_explanation(self):
        """Test high risk explanation generation"""
        explanation = create_user_friendly_explanation(0.9, "Unusual spending pattern detected")

        assert "🚨 High Risk" in explanation
        assert "immediate attention" in explanation
        assert "Unusual spending pattern detected" in explanation

    def test_create_medium_risk_explanation(self):
        """Test medium risk explanation generation"""
        explanation = create_user_friendly_explanation(0.7, "Late night transaction")

        assert "⚠️ Medium Risk" in explanation
        assert "verification recommended" in explanation
        assert "Late night transaction" in explanation

    def test_create_low_risk_explanation(self):
        """Test low risk explanation generation"""
        explanation = create_user_friendly_explanation(0.4, "Slightly unusual amount")

        assert "⚡ Low Risk" in explanation
        assert "Monitor for patterns" in explanation
        assert "Slightly unusual amount" in explanation

    def test_create_normal_explanation(self):
        """Test normal risk explanation generation"""
        explanation = create_user_friendly_explanation(0.1, "Normal transaction pattern")

        assert "✅ Normal" in explanation
        assert "appears legitimate" in explanation
        assert "Normal transaction pattern" in explanation

class TestActionDetermination:
    """Test action determination logic"""

    def test_determine_hold_action(self):
        """Test that high risk scores trigger hold action"""
        action = determine_action(0.9)
        assert action == "hold"

    def test_determine_stepup_action(self):
        """Test that medium-high risk scores trigger step-up action"""
        action = determine_action(0.7)
        assert action == "step-up"

    def test_determine_notify_action(self):
        """Test that medium risk scores trigger notify action"""
        action = determine_action(0.4)
        assert action == "notify"

    def test_determine_allow_action(self):
        """Test that low risk scores trigger allow action"""
        action = determine_action(0.1)
        assert action == "allow"

class TestAuditRecordStorage:
    """Test audit record storage functionality"""

    def test_save_audit_record(self):
        """Test saving audit record to database"""
        from main import AuditRecord

        # Use temporary database for testing
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_db:
            tmp_db_path = tmp_db.name

        try:
            with patch('main.DATABASE_URL', f'sqlite:///{tmp_db_path}'):
                # Initialize database
                from main import init_database
                init_database()

                record = AuditRecord(
                    transaction_id="test_audit_001",
                    risk_score=0.7,
                    rationale="Test rationale",
                    explanation="Test explanation",
                    action="step-up",
                    timestamp=datetime.utcnow()
                )

                # Should not raise an exception
                save_audit_record(record)

        finally:
            # Clean up temporary database
            if os.path.exists(tmp_db_path):
                os.unlink(tmp_db_path)

class TestProcessEndpoint:
    """Test the main process endpoint"""

    def test_process_risk_analysis_success(self):
        """Test successful risk analysis processing"""
        analysis_data = {
            "transaction_id": "test_process_001",
            "risk_score": 0.6,
            "rationale": "Medium risk transaction",
            "timestamp": "2024-01-01T12:00:00Z"
        }

        with patch('main.save_audit_record'):
            with patch('main.send_to_action_orchestrator', new_callable=AsyncMock):
                response = client.post("/process", json=analysis_data)

                assert response.status_code == 200
                data = response.json()

                assert data["transaction_id"] == analysis_data["transaction_id"]
                assert data["risk_score"] == analysis_data["risk_score"]
                assert data["rationale"] == analysis_data["rationale"]
                assert "explanation" in data
                assert "action" in data
                assert "timestamp" in data

    def test_process_risk_analysis_invalid_data(self):
        """Test processing with invalid data"""
        invalid_data = {
            "transaction_id": "test_invalid",
            # Missing required fields
        }

        response = client.post("/process", json=invalid_data)
        assert response.status_code == 422  # Validation error

class TestAuditEndpoints:
    """Test audit record retrieval endpoints"""

    def test_get_audit_record_not_found(self):
        """Test getting non-existent audit record"""
        with patch('main.DATABASE_URL', 'sqlite:///tmp/test_not_found.db'):
            from main import init_database
            init_database()

            response = client.get("/audit/nonexistent_txn")
            assert response.status_code == 404

    def test_get_recent_audit_records_empty(self):
        """Test getting recent audit records when none exist"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_db:
            tmp_db_path = tmp_db.name

        try:
            with patch('main.DATABASE_URL', f'sqlite:///{tmp_db_path}'):
                from main import init_database
                init_database()

                response = client.get("/audit")
                assert response.status_code == 200

                data = response.json()
                assert isinstance(data, list)
                assert len(data) == 0

        finally:
            if os.path.exists(tmp_db_path):
                os.unlink(tmp_db_path)

class TestActionOrchestratorIntegration:
    """Test integration with action orchestrator"""

    @pytest.mark.asyncio
    async def test_send_to_action_orchestrator_success(self):
        """Test successful sending to action orchestrator"""
        from main import AuditRecord, send_to_action_orchestrator

        record = AuditRecord(
            transaction_id="test_orchestrator_001",
            risk_score=0.5,
            rationale="Test rationale",
            explanation="Test explanation",
            action="notify",
            timestamp=datetime.utcnow()
        )

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            # Should not raise an exception
            await send_to_action_orchestrator(record)

    @pytest.mark.asyncio
    async def test_send_to_action_orchestrator_http_error(self):
        """Test sending with HTTP error"""
        from main import AuditRecord, send_to_action_orchestrator

        record = AuditRecord(
            transaction_id="test_orchestrator_002",
            risk_score=0.3,
            rationale="Test rationale",
            explanation="Test explanation",
            action="allow",
            timestamp=datetime.utcnow()
        )

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("HTTP Error")
            )

            # Should not raise an exception (errors are logged)
            await send_to_action_orchestrator(record)

class TestLogging:
    """Test logging functionality"""

    def test_processing_logging(self):
        """Test that processing is properly logged"""
        analysis_data = {
            "transaction_id": "test_log_001",
            "risk_score": 0.4,
            "rationale": "Test rationale",
            "timestamp": "2024-01-01T12:00:00Z"
        }

        with patch('main.logger') as mock_logger:
            with patch('main.save_audit_record'):
                with patch('main.send_to_action_orchestrator', new_callable=AsyncMock):
                    response = client.post("/process", json=analysis_data)

                    assert response.status_code == 200

                    # Verify logging was called
                    assert mock_logger.info.called

if __name__ == "__main__":
    pytest.main([__file__])
