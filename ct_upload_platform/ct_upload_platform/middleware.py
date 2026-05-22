"""
Middleware for the ct_upload_platform project.
"""

import logging
from django.conf import settings
from django.http import HttpResponseForbidden

logger = logging.getLogger(__name__)


class IPWhitelistMiddleware:
    """
    Middleware to restrict access to the Django application based on IP whitelist.
    
    Configure via environment variable IP_WHITELIST (comma-separated IPs or CIDR ranges):
    - IP_WHITELIST="192.168.1.1,10.0.0.0/8,127.0.0.1"
    - If not set, all IPs are allowed
    
    Exempted paths (always allowed):
    - /admin/login/
    - /api/v1/auth/login/
    """
    
    EXEMPTED_PATHS = [
        '/admin/login/',
        '/api/v1/auth/login/',
        '/api/v1/auth/signup/',
        '/signup/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.whitelist = self._parse_whitelist()
        
    def _parse_whitelist(self):
        """Parse the IP whitelist from environment settings."""
        ip_whitelist_env = getattr(settings, 'IP_WHITELIST', None)
        if not ip_whitelist_env:
            return None
        
        # Parse comma-separated IPs and CIDR ranges
        ips = [ip.strip() for ip in ip_whitelist_env.split(',')]
        return ips
    
    def _is_ip_allowed(self, client_ip):
        """Check if client IP is in whitelist."""
        if not self.whitelist:
            return True
        
        for allowed_ip in self.whitelist:
            # Simple IP match (supports both single IPs and CIDR ranges)
            if '/' in allowed_ip:
                # CIDR range
                try:
                    from ipaddress import ip_address, ip_network
                    if ip_address(client_ip) in ip_network(allowed_ip, strict=False):
                        return True
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid CIDR range in whitelist: {allowed_ip}, error: {e}")
            else:
                # Single IP
                if client_ip == allowed_ip:
                    return True
        
        return False
    
    def _get_client_ip(self, request):
        """Extract client IP from request."""
        # Check for X-Forwarded-For (proxied requests)
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # X-Forwarded-For can contain multiple IPs, get the first one
            ip = x_forwarded_for.split(',')[0].strip()
            return ip
        
        # Fallback to REMOTE_ADDR
        return request.META.get('REMOTE_ADDR')
    
    def __call__(self, request):
        """Check IP whitelist on each request."""
        # Check if path is exempted
        path = request.path
        if any(path.startswith(exempted) for exempted in self.EXEMPTED_PATHS):
            return self.get_response(request)
        
        # Check IP whitelist
        if self.whitelist:
            client_ip = self._get_client_ip(request)
            if not self._is_ip_allowed(client_ip):
                logger.warning(f"Access denied for IP: {client_ip} to path: {path}")
                return HttpResponseForbidden(
                    'Access denied. Your IP address is not whitelisted.'
                )
        
        response = self.get_response(request)
        return response
