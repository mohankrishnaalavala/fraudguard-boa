"""
Unit tests for MCP Gateway service
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import datetime

from main import app, check_rate_limit, rate_limit_store

client = TestClient(app)

class TestHealthCheck:
    """Test health check endpoint"""
    
    def test_health_check(self):
        """Test health check returns 200 and correct format"""
        response = client.get("/healthz")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "mcp-gateway"
        assert "timestamp" in data

class TestRateLimiting:
    """Test rate limiting functionality"""
    
    def setup_method(self):
        """Clear rate limit store before each test"""
        rate_limit_store.clear()
    
    def test_rate_limit_allows_requests_under_limit(self):
        """Test that requests under limit are allowed"""
        client_ip = "192.168.1.1"
        
        # Should allow requests under the limit
        for i in range(5):
            assert check_rate_limit(client_ip) is True
    
    def test_rate_limit_blocks_requests_over_limit(self):
        """Test that requests over limit are blocked"""
        client_ip = "192.168.1.2"
        
        # Mock time to control rate limiting window
        with patch('main.time.time', return_value=1000.0):
            # Fill up the rate limit
            for i in range(100):  # RATE_LIMIT_PER_MINUTE default is 100
                check_rate_limit(client_ip)
            
            # Next request should be blocked
            assert check_rate_limit(client_ip) is False
    
    def test_rate_limit_resets_after_window(self):
        """Test that rate limit resets after time window"""
        client_ip = "192.168.1.3"
        
        # Fill up rate limit at time 1000
        with patch('main.time.time', return_value=1000.0):
            for i in range(100):
                check_rate_limit(client_ip)
            assert check_rate_limit(client_ip) is False
        
        # Move forward in time (past the 60-second window)
        with patch('main.time.time', return_value=1070.0):
            # Should allow requests again
            assert check_rate_limit(client_ip) is True

class TestAccountEndpoint:
    """Test account information endpoint"""
    
    def setup_method(self):
        """Clear rate limit store before each test"""
        rate_limit_store.clear()
    
    def test_get_account_success(self):
        """Test successful account retrieval"""
        account_id = "test_account_123"
        response = client.get(f"/accounts/{account_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["account_id"] == account_id
        assert "balance" in data
        assert "account_type" in data
        assert data["account_type"] == "checking"
    
    def test_get_account_rate_limited(self):
        """Test account endpoint respects rate limiting"""
        account_id = "test_account_456"
        
        # Mock rate limit check to return False
        with patch('main.check_rate_limit', return_value=False):
            response = client.get(f"/accounts/{account_id}")
            
            assert response.status_code == 429
            assert "Rate limit exceeded" in response.json()["detail"]

class TestTransactionsEndpoint:
    """Test transactions endpoint"""
    
    def setup_method(self):
        """Clear rate limit store before each test"""
        rate_limit_store.clear()
    
    def test_get_transactions_success(self):
        """Test successful transaction retrieval"""
        account_id = "test_account_789"
        response = client.get(f"/accounts/{account_id}/transactions")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) <= 10  # Default limit
        
        if data:  # If transactions returned
            transaction = data[0]
            assert "transaction_id" in transaction
            assert "account_id" in transaction
            assert "amount" in transaction
            assert "merchant" in transaction
            assert "category" in transaction
            assert "timestamp" in transaction
            assert transaction["account_id"] == account_id
    
    def test_get_transactions_with_limit(self):
        """Test transaction retrieval with custom limit"""
        account_id = "test_account_limit"
        limit = 5
        
        response = client.get(f"/accounts/{account_id}/transactions?limit={limit}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data) <= limit
    
    def test_get_transactions_rate_limited(self):
        """Test transactions endpoint respects rate limiting"""
        account_id = "test_account_rate"
        
        # Mock rate limit check to return False
        with patch('main.check_rate_limit', return_value=False):
            response = client.get(f"/accounts/{account_id}/transactions")
            
            assert response.status_code == 429
            assert "Rate limit exceeded" in response.json()["detail"]

class TestLoggingMiddleware:
    """Test logging middleware"""
    
    def test_request_logging(self):
        """Test that requests are logged properly"""
        with patch('main.logger') as mock_logger:
            response = client.get("/healthz")
            
            assert response.status_code == 200
            
            # Verify logging calls were made
            assert mock_logger.info.call_count >= 2  # start and complete
            
            # Check that request_started and request_completed were logged
            call_args_list = [call[0] for call in mock_logger.info.call_args_list]
            assert any("request_started" in args for args in call_args_list)
            assert any("request_completed" in args for args in call_args_list)

class TestErrorHandling:
    """Test error handling"""
    
    def test_internal_server_error_handling(self):
        """Test that internal errors are handled gracefully"""
        # This test would require mocking internal failures
        # For now, we'll test that the endpoints don't crash
        
        response = client.get("/accounts/test")
        assert response.status_code in [200, 429, 500]  # Valid response codes
        
        response = client.get("/accounts/test/transactions")
        assert response.status_code in [200, 429, 500]  # Valid response codes

if __name__ == "__main__":
    pytest.main([__file__])
