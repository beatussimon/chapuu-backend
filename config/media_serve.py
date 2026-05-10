from django.views.static import serve
from django.utils.http import http_date
import time

def cached_media_serve(request, path, document_root=None, **kwargs):
    """
    A wrapper around django.views.static.serve that adds Cache-Control headers.
    """
    response = serve(request, path, document_root, **kwargs)
    
    # Add aggressive caching for media files (1 year)
    if response.status_code == 200:
        response['Cache-Control'] = 'public, max-age=31536000, immutable'
        response['Expires'] = http_date(time.time() + 31536000)
    
    return response
