"""
Custom authentication supporting both Token and Bearer token formats,
plus shared auth utility functions used across views.
"""

from typing import Optional

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response


class BearerTokenAuthentication(TokenAuthentication):
    """
    Extends Django REST Framework's TokenAuthentication to support Bearer tokens.
    
    Supports both formats:
    - Authorization: Token abc123...
    - Authorization: Bearer abc123...
    
    This enables modern REST API standards while maintaining backward compatibility.
    """
    keyword = 'Bearer'  # Default to Bearer
    
    def authenticate(self, request):
        """
        Authenticate using either Bearer or Token format.
        """
        auth = request.META.get('HTTP_AUTHORIZATION', '').split()
        
        if not auth or len(auth) != 2:
            return None
        
        keyword, token = auth[0], auth[1]
        
        # Support both "Bearer" and "Token" prefixes
        if keyword.lower() == 'bearer' or keyword == 'Token':
            return self.authenticate_credentials(token)
        
        # If neither Bearer nor Token, reject
        raise AuthenticationFailed(
            f'Invalid authorization header. Expected "Bearer <token>" or "Token <token>", '
            f'got "{keyword} <token>".'
        )


# ---------------------------------------------------------------------------
# Shared auth utility functions
# ---------------------------------------------------------------------------

def build_auth_response(user, token) -> dict:
    """Return the standard login / signup token response payload."""
    return {
        'token': token.key,
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_staff': user.is_staff,
    }


def check_upload_ownership(request, uploader_id: str) -> Optional[Response]:
    """Return a 403 Response if the request user does not own the upload."""
    if request.user.username != uploader_id:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    return None


def check_upload_access(request, uploader_id: str) -> Optional[Response]:
    """Return a 403 Response if the user doesn't own the upload and isn't staff."""
    if request.user.username != uploader_id and not request.user.is_staff:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    return None
