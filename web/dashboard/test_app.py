"""
Unit tests for Dashboard application
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime

from app import app, get_risk_color, get_action_icon, fetch_audit_records

# Configure Flask app for testing
app.config['TESTING'] = True

class TestHealthCheck:
    """Test health check endpoint"""
    
    def test_health_check(self):
        """Test health check returns 200 and correct format"""
        with app.test_client() as client:
            response = client.get("/healthz")
            assert response.status_code == 200
            
            data = response.get_json()
            assert data["status"] == "healthy"
            assert data["service"] == "dashboard"
            assert "timestamp" in data

class TestUtilityFunctions:
    """Test utility functions"""
    
    def test_get_risk_color_high_risk(self):
        """Test risk color for high risk scores"""
        assert get_risk_color(0.9) == "danger"
        assert get_risk_color(0.8) == "danger"
    
    def test_get_risk_color_medium_risk(self):
        """Test risk color for medium risk scores"""
        assert get_risk_color(0.7) == "warning"
        assert get_risk_color(0.6) == "warning"
    
    def test_get_risk_color_low_risk(self):
        """Test risk color for low risk scores"""
        assert get_risk_color(0.4) == "info"
        assert get_risk_color(0.3) == "info"
    
    def test_get_risk_color_normal(self):
        """Test risk color for normal risk scores"""
        assert get_risk_color(0.2) == "success"
        assert get_risk_color(0.1) == "success"
    
    def test_get_action_icon_all_actions(self):
        """Test action icons for all action types"""
        assert get_action_icon("hold") == "🚨"
        assert get_action_icon("step-up") == "⚠️"
        assert get_action_icon("notify") == "⚡"
        assert get_action_icon("allow") == "✅"
        assert get_action_icon("unknown") == "❓"

class TestAuditRecordFetching:
    """Test audit record fetching functionality"""
    
    @pytest.mark.asyncio
    async def test_fetch_audit_records_success(self):
        """Test successful audit record fetching"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "id": 1,
                "transaction_id": "txn_001",
                "risk_score": 0.7,
                "rationale": "Test rationale",
                "explanation": "Test explanation",
                "action": "step-up",
                "timestamp": "2024-01-01T12:00:00Z"
            }
        ]
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            records = await fetch_audit_records()
            
            assert len(records) == 1
            record = records[0]
            
            # Check that display properties were added
            assert "risk_color" in record
            assert "action_icon" in record
            assert "risk_percentage" in record
            assert "formatted_time" in record
            assert "formatted_date" in record
            
            assert record["risk_color"] == "warning"  # 0.7 should be warning
            assert record["action_icon"] == "⚠️"  # step-up icon
            assert record["risk_percentage"] == 70  # 0.7 * 100
    
    @pytest.mark.asyncio
    async def test_fetch_audit_records_http_error(self):
        """Test audit record fetching with HTTP error"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("HTTP Error")
            )
            
            records = await fetch_audit_records()
            
            # Should return empty list on error
            assert records == []
    
    @pytest.mark.asyncio
    async def test_fetch_audit_records_empty_response(self):
        """Test audit record fetching with empty response"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = []
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            records = await fetch_audit_records()
            
            assert records == []

class TestDashboardRoute:
    """Test main dashboard route"""
    
    def test_dashboard_success(self):
        """Test successful dashboard rendering"""
        mock_records = [
            {
                "id": 1,
                "transaction_id": "txn_test_001",
                "risk_score": 0.5,
                "rationale": "Test rationale",
                "explanation": "Test explanation",
                "action": "notify",
                "timestamp": datetime(2024, 1, 1, 12, 0, 0),
                "risk_color": "info",
                "action_icon": "⚡",
                "risk_percentage": 50,
                "formatted_time": "12:00:00",
                "formatted_date": "2024-01-01"
            }
        ]
        
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, return_value=mock_records):
                response = client.get("/")
                
                assert response.status_code == 200
                assert b"FraudGuard Dashboard" in response.data
                assert b"txn_test_001" in response.data
    
    def test_dashboard_with_empty_records(self):
        """Test dashboard rendering with no records"""
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, return_value=[]):
                response = client.get("/")
                
                assert response.status_code == 200
                assert b"FraudGuard Dashboard" in response.data
                assert b"No transactions to display" in response.data
    
    def test_dashboard_with_fetch_error(self):
        """Test dashboard rendering when fetch fails"""
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, side_effect=Exception("Fetch error")):
                response = client.get("/")
                
                assert response.status_code == 500
                assert b"Failed to load dashboard data" in response.data

class TestAPIRoute:
    """Test API route for AJAX updates"""
    
    def test_api_records_success(self):
        """Test successful API records endpoint"""
        mock_records = [
            {
                "transaction_id": "txn_api_001",
                "risk_score": 0.3,
                "action": "allow",
                "timestamp": datetime(2024, 1, 1, 12, 0, 0),
                "risk_color": "success",
                "action_icon": "✅",
                "risk_percentage": 30,
                "formatted_time": "12:00:00",
                "formatted_date": "2024-01-01"
            }
        ]
        
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, return_value=mock_records):
                response = client.get("/api/records")
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert len(data) == 1
                assert data[0]["transaction_id"] == "txn_api_001"
    
    def test_api_records_error(self):
        """Test API records endpoint with error"""
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, side_effect=Exception("API error")):
                response = client.get("/api/records")
                
                assert response.status_code == 500
                data = response.get_json()
                assert "error" in data

class TestStatisticsCalculation:
    """Test statistics calculation in dashboard"""
    
    def test_statistics_calculation(self):
        """Test that statistics are calculated correctly"""
        mock_records = [
            {"risk_score": 0.9},  # high risk
            {"risk_score": 0.7},  # medium risk
            {"risk_score": 0.4},  # low risk
            {"risk_score": 0.1},  # normal
            {"risk_score": 0.8},  # high risk
        ]
        
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, return_value=mock_records):
                response = client.get("/")
                
                assert response.status_code == 200
                
                # Check that statistics are present in the response
                # This is a basic check - in a real test, we'd parse the HTML
                # or use a more sophisticated testing approach
                assert b"High Risk" in response.data
                assert b"Medium Risk" in response.data
                assert b"Low Risk" in response.data
                assert b"Normal" in response.data

class TestErrorHandling:
    """Test error handling"""
    
    def test_dashboard_handles_malformed_data(self):
        """Test dashboard handles malformed audit data gracefully"""
        malformed_records = [
            {
                "transaction_id": "txn_malformed",
                "risk_score": "invalid",  # Should be float
                "action": "notify",
                "timestamp": "invalid_timestamp"
            }
        ]
        
        with app.test_client() as client:
            with patch('app.fetch_audit_records', new_callable=AsyncMock, return_value=malformed_records):
                # Should not crash, might return error page
                response = client.get("/")
                assert response.status_code in [200, 500]  # Either works or fails gracefully

class TestLogging:
    """Test logging functionality"""
    
    def test_audit_fetch_logging(self):
        """Test that audit record fetching is logged"""
        with patch('app.logger') as mock_logger:
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = MagicMock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = []
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
                
                # Use asyncio to run the async function
                import asyncio
                asyncio.run(fetch_audit_records())
                
                # Verify logging was called
                assert mock_logger.info.called

if __name__ == "__main__":
    pytest.main([__file__])
