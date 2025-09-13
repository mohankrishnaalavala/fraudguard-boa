"""
Unit tests for Transaction Watcher service
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime
import asyncio

from main import app, fetch_recent_transactions, send_for_risk_analysis, watcher_status

client = TestClient(app)

class TestHealthCheck:
    """Test health check endpoint"""
    
    def test_health_check(self):
        """Test health check returns 200 and correct format"""
        response = client.get("/healthz")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "txn-watcher"
        assert "timestamp" in data
        assert "watcher_running" in data

class TestStatusEndpoint:
    """Test status endpoint"""
    
    def test_get_status(self):
        """Test status endpoint returns watcher information"""
        response = client.get("/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "last_poll" in data
        assert "processed_count" in data
        assert "poll_interval_seconds" in data

class TestTransactionFetching:
    """Test transaction fetching functionality"""
    
    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_success(self):
        """Test successful transaction fetching"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "transaction_id": "txn_001",
                "account_id": "acc_001",
                "amount": 100.0,
                "merchant": "test_merchant",
                "category": "test",
                "timestamp": "2024-01-01T12:00:00Z"
            }
        ]
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            transactions = await fetch_recent_transactions()
            
            assert len(transactions) > 0
            assert isinstance(transactions, list)
    
    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_http_error(self):
        """Test transaction fetching with HTTP error"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("HTTP Error")
            )
            
            transactions = await fetch_recent_transactions()
            
            # Should return empty list on error
            assert transactions == []
    
    @pytest.mark.asyncio
    async def test_fetch_recent_transactions_timeout(self):
        """Test transaction fetching with timeout"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=asyncio.TimeoutError("Request timeout")
            )
            
            transactions = await fetch_recent_transactions()
            
            # Should return empty list on timeout
            assert transactions == []

class TestRiskAnalysisSending:
    """Test sending transactions for risk analysis"""
    
    @pytest.mark.asyncio
    async def test_send_for_risk_analysis_success(self):
        """Test successful sending to risk scorer"""
        transaction = {
            "transaction_id": "txn_test_001",
            "account_id": "acc_test",
            "amount": 50.0,
            "merchant": "test_merchant",
            "category": "test",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            # Should not raise an exception
            await send_for_risk_analysis(transaction)
    
    @pytest.mark.asyncio
    async def test_send_for_risk_analysis_http_error(self):
        """Test sending with HTTP error"""
        transaction = {
            "transaction_id": "txn_test_002",
            "account_id": "acc_test",
            "amount": 50.0,
            "merchant": "test_merchant",
            "category": "test",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("HTTP Error")
            )
            
            # Should not raise an exception (errors are logged but not propagated)
            await send_for_risk_analysis(transaction)

class TestWatcherStatus:
    """Test watcher status tracking"""
    
    def test_watcher_status_initialization(self):
        """Test that watcher status is properly initialized"""
        assert "last_poll" in watcher_status
        assert "processed_count" in watcher_status
        assert "running" in watcher_status
        
        assert isinstance(watcher_status["processed_count"], int)
        assert isinstance(watcher_status["running"], bool)

class TestErrorHandling:
    """Test error handling"""
    
    def test_endpoints_dont_crash(self):
        """Test that endpoints handle errors gracefully"""
        response = client.get("/healthz")
        assert response.status_code == 200
        
        response = client.get("/status")
        assert response.status_code == 200

class TestLogging:
    """Test logging functionality"""
    
    @pytest.mark.asyncio
    async def test_transaction_fetch_logging(self):
        """Test that transaction fetching is logged"""
        with patch('main.logger') as mock_logger:
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = MagicMock()
                mock_response.raise_for_status.return_value = None
                mock_response.json.return_value = []
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
                
                await fetch_recent_transactions()
                
                # Verify logging was called
                assert mock_logger.info.called
    
    @pytest.mark.asyncio
    async def test_risk_analysis_send_logging(self):
        """Test that sending for risk analysis is logged"""
        transaction = {
            "transaction_id": "txn_log_test",
            "account_id": "acc_test",
            "amount": 25.0,
            "merchant": "test",
            "category": "test",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        with patch('main.logger') as mock_logger:
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = MagicMock()
                mock_response.raise_for_status.return_value = None
                mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
                
                await send_for_risk_analysis(transaction)
                
                # Verify logging was called
                assert mock_logger.info.called

if __name__ == "__main__":
    pytest.main([__file__])
