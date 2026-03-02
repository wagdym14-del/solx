# --- Enhanced Authentication Manager (v1.0) ---

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from omar.config import AUTH_FILE


class AuthManager:
    """
    Enhanced authentication manager for handling cookies and session data.
    Provides validation, status checking, and improved cookie management.
    """
    
    def __init__(self, auth_file: str = AUTH_FILE):
        self.auth_file = auth_file
        self.auth_data: Optional[Dict] = None
        self._load_auth_data()
    
    def _load_auth_data(self) -> None:
        """Load authentication data from file with error handling."""
        try:
            if os.path.exists(self.auth_file):
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    self.auth_data = json.load(f)
            else:
                self.auth_data = None
        except (json.JSONDecodeError, IOError) as e:
            print(f"[AuthManager] Error loading auth data: {e}")
            self.auth_data = None
    
    def get_auth_status(self) -> Dict[str, Any]:
        """Get comprehensive authentication status."""
        status = {
            "exists": False,
            "last_updated": None,
            "cookies_count": 0,
            "is_valid": False,
            "has_session": False,
            "domains": []
        }
        
        if not self.auth_data:
            return status
        
        status["exists"] = True
        
        # Get file modification time
        try:
            mtime = os.path.getmtime(self.auth_file)
            status["last_updated"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass
        
        # Analyze cookies
        cookies = self.auth_data.get("cookies", [])
        status["cookies_count"] = len(cookies)
        
        # Check for essential session cookies
        session_indicators = ["session", "token", "auth", "jwt", "sid"]
        status["has_session"] = any(
            any(indicator in cookie.get("name", "").lower() for indicator in session_indicators)
            for cookie in cookies
        )
        
        # Check cookie validity
        current_time = datetime.now(timezone.utc).timestamp()
        valid_cookies = 0
        domains = set()
        
        for cookie in cookies:
            # Check expiration
            expires = cookie.get("expires")
            if expires and isinstance(expires, (int, float)):
                if expires > current_time:
                    valid_cookies += 1
                    domains.add(cookie.get("domain", ""))
            else:
                # No expiration means it might be valid
                valid_cookies += 1
                domains.add(cookie.get("domain", ""))
        
        status["is_valid"] = valid_cookies > 0 and status["has_session"]
        status["domains"] = list(domains)
        
        return status
    
    def validate_auth_data(self) -> bool:
        """Validate authentication data structure and content."""
        if not self.auth_data:
            return False
        
        # Check required structure
        if "cookies" not in self.auth_data:
            return False
        
        cookies = self.auth_data["cookies"]
        if not isinstance(cookies, list):
            return False
        
        # Check at least one cookie exists
        if len(cookies) == 0:
            return False
        
        # Check cookie structure
        for cookie in cookies[:3]:  # Check first 3 cookies
            if not isinstance(cookie, dict):
                return False
            
            required_fields = ["name", "value", "domain"]
            if not all(field in cookie for field in required_fields):
                return False
        
        return True
    
    def get_cookie_summary(self) -> Dict[str, Any]:
        """Get detailed cookie information."""
        if not self.auth_data or "cookies" not in self.auth_data:
            return {"total": 0, "domains": [], "session_cookies": 0, "persistent": 0}
        
        cookies = self.auth_data["cookies"]
        current_time = datetime.now(timezone.utc).timestamp()
        
        summary = {
            "total": len(cookies),
            "domains": list(set(cookie.get("domain", "") for cookie in cookies)),
            "session_cookies": 0,
            "persistent": 0,
            "expired": 0,
            "secure": 0,
            "http_only": 0
        }
        
        for cookie in cookies:
            # Check if session cookie (no expiration)
            expires = cookie.get("expires")
            if expires is None:
                summary["session_cookies"] += 1
            elif isinstance(expires, (int, float)):
                if expires > current_time:
                    summary["persistent"] += 1
                else:
                    summary["expired"] += 1
            
            # Check security flags
            if cookie.get("secure"):
                summary["secure"] += 1
            if cookie.get("httpOnly"):
                summary["http_only"] += 1
        
        return summary
    
    def refresh_auth_data(self) -> bool:
        """Reload authentication data from file."""
        self._load_auth_data()
        return self.auth_data is not None
    
    def backup_auth_data(self, backup_suffix: str = None) -> bool:
        """Create a backup of current authentication data."""
        if not self.auth_data:
            return False
        
        if backup_suffix is None:
            backup_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        backup_file = f"{self.auth_file}.backup_{backup_suffix}"
        
        try:
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(self.auth_data, f, indent=2)
            print(f"[AuthManager] Backup created: {backup_file}")
            return True
        except IOError as e:
            print(f"[AuthManager] Failed to create backup: {e}")
            return False
    
    def cleanup_expired_cookies(self) -> int:
        """Remove expired cookies and return count of removed cookies."""
        if not self.auth_data or "cookies" not in self.auth_data:
            return 0
        
        current_time = datetime.now(timezone.utc).timestamp()
        original_count = len(self.auth_data["cookies"])
        
        # Filter out expired cookies
        valid_cookies = []
        for cookie in self.auth_data["cookies"]:
            expires = cookie.get("expires")
            if expires is None or (isinstance(expires, (int, float)) and expires > current_time):
                valid_cookies.append(cookie)
        
        removed_count = original_count - len(valid_cookies)
        
        if removed_count > 0:
            self.auth_data["cookies"] = valid_cookies
            # Save the cleaned data
            try:
                with open(self.auth_file, 'w', encoding='utf-8') as f:
                    json.dump(self.auth_data, f, indent=2)
                print(f"[AuthManager] Cleaned up {removed_count} expired cookies")
            except IOError as e:
                print(f"[AuthManager] Failed to save cleaned auth data: {e}")
                return 0
        
        return removed_count


# Global instance for easy access
auth_manager = AuthManager()
