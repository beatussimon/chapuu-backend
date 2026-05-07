from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.authentication import JWTAuthentication

User = get_user_model()

@database_sync_to_async
def get_user_from_token(token_string):
    try:
        validated_token = UntypedToken(token_string)
        user = JWTAuthentication().get_user(validated_token)
        return user
    except (InvalidToken, TokenError, Exception):
        return AnonymousUser()

class JWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        if token:
            user = await get_user_from_token(token)
            if not isinstance(user, AnonymousUser):
                scope['user'] = user

        return await self.inner(scope, receive, send)
