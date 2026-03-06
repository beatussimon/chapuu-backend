from rest_framework import viewsets, permissions
from reviews.models import StoreReview
from reviews.serializers import StoreReviewSerializer

class StoreReviewViewSet(viewsets.ModelViewSet):
    serializer_class = StoreReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        store_id = self.request.query_params.get('store', None)
        if store_id is not None:
            return StoreReview.objects.filter(store__id=store_id).order_by('-created_at')
        return StoreReview.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        # Auto-assign customer
        serializer.save(customer=self.request.user)
