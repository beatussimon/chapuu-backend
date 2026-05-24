from rest_framework import viewsets, permissions
from rest_framework.pagination import PageNumberPagination
from reviews.models import StoreReview
from reviews.serializers import StoreReviewSerializer

class StoreReviewPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 50

class StoreReviewViewSet(viewsets.ModelViewSet):
    serializer_class = StoreReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StoreReviewPagination

    def get_queryset(self):
        store_id = self.request.query_params.get('store', None)
        if store_id is not None:
            return StoreReview.objects.filter(store__id=store_id).order_by('-created_at')
        return StoreReview.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        # Auto-assign customer
        serializer.save(customer=self.request.user)
