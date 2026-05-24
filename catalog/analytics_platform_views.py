from rest_framework import viewsets, permissions
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta
from orders.models import Order
from billing.models import CommissionLedgerEntry
from stores.models import Store
from django.contrib.auth import get_user_model
from users.permissions import IsPlatformAdmin

User = get_user_model()

class PlatformAnalyticsViewSet(viewsets.ViewSet):
    """
    Platform-wide analytics suite for Admins and Superusers.
    GET /api/analytics/platform/
    """
    permission_classes = [IsPlatformAdmin]

    def list(self, request):
        today = timezone.now().date()
        # Period: default to last 30 days
        from_date = request.query_params.get('from', (today - timedelta(days=30)).isoformat())
        to_date = request.query_params.get('to', today.isoformat())

        try:
            from datetime import date
            start = date.fromisoformat(from_date)
            end = date.fromisoformat(to_date)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        # 1. Base Querysets
        completed_orders = Order.objects.filter(
            state=Order.State.COMPLETED,
            created_at__date__gte=start,
            created_at__date__lte=end
        )
        
        commission_entries = CommissionLedgerEntry.objects.filter(
            created_at__date__gte=start,
            created_at__date__lte=end
        )

        # 2. KPI Aggregates
        gpv = completed_orders.aggregate(total=Sum('total_amount'))['total'] or 0.0
        platform_commission = commission_entries.aggregate(total=Sum('commission_amount'))['total'] or 0.0
        
        active_merchants_count = Store.objects.filter(is_active=True).count()
        customer_count = User.objects.filter(role=User.Role.CUSTOMER).count()
        staff_count = User.objects.filter(role__in=[
            User.Role.CHEF, User.Role.DELIVERY, User.Role.ACCOUNTANT
        ]).count()

        kpi = {
            'gpv': float(gpv),
            'platform_commission': float(platform_commission),
            'active_merchants_count': active_merchants_count,
            'customer_count': customer_count,
            'staff_count': staff_count,
        }

        # 3. Graphical/Trends Data (last 30 days daily gpv & commission)
        daily_trends = {}
        # Iterate and sum daily gpv
        for entry in completed_orders.annotate(day=TruncDate('created_at')).values('day').annotate(revenue=Sum('total_amount'), count=Count('id')):
            day_str = entry['day'].isoformat()
            daily_trends[day_str] = {
                'day': day_str,
                'gpv': float(entry['revenue']),
                'commission': 0.0,
                'order_count': entry['count']
            }

        # Sum daily commission
        for entry in commission_entries.annotate(day=TruncDate('created_at')).values('day').annotate(commission=Sum('commission_amount')):
            day_str = entry['day'].isoformat()
            comm = float(entry['commission'])
            if day_str in daily_trends:
                daily_trends[day_str]['commission'] = comm
            else:
                daily_trends[day_str] = {
                    'day': day_str,
                    'gpv': 0.0,
                    'commission': comm,
                    'order_count': 0
                }

        trends_list = sorted(daily_trends.values(), key=lambda x: x['day'])

        # 4. Store Performance Leaderboard
        store_leaderboard = list(
            completed_orders
            .values(store_name=F('store__name'))
            .annotate(
                total_sales=Sum('total_amount'),
                order_count=Count('id')
            )
            .order_by('-total_sales')[:5]
        )
        for s in store_leaderboard:
            s['total_sales'] = float(s['total_sales'])

        # 5. Order State Funnel Ratios
        all_orders_period = Order.objects.filter(
            created_at__date__gte=start,
            created_at__date__lte=end
        )
        total_orders_count = all_orders_period.count()
        state_counts = list(
            all_orders_period
            .values('state')
            .annotate(count=Count('id'))
        )
        state_funnel = {item['state']: item['count'] for item in state_counts}

        # 6. Safety & Dispute Analytics
        locked_orders_count = Order.objects.filter(is_locked=True).count()
        suspicious_orders_count = Order.objects.filter(is_suspicious=True).count()
        
        # Failed handoff verification attempts aggregate
        failed_handoff_attempts = Order.objects.aggregate(total=Sum('delivery_code_attempts'))['total'] or 0

        safety_disputes = {
            'locked_orders_count': locked_orders_count,
            'suspicious_orders_count': suspicious_orders_count,
            'failed_handoff_attempts': failed_handoff_attempts,
        }

        # 7. Spatial Analytics (Haversine distances for completed deliveries)
        from stores.geo_utils import haversine_km

        delivery_orders = completed_orders.filter(
            fulfillment_mode=Order.FulfillmentMode.DELIVERY,
            delivery_latitude__isnull=False,
            delivery_longitude__isnull=False
        ).select_related('store')

        distances = []
        hyperlocal_count = 0  # <= 0.5 km
        medium_count = 0      # 0.5 km - 2.0 km
        long_count = 0        # > 2.0 km

        for order in delivery_orders:
            if (order.store.latitude is not None and 
                order.store.longitude is not None and 
                order.delivery_latitude is not None and 
                order.delivery_longitude is not None):
                
                dist = haversine_km(
                    order.store.latitude, order.store.longitude,
                    order.delivery_latitude, order.delivery_longitude
                )
                if dist is not None:
                    distances.append(dist)
                    if dist <= 0.5:
                        hyperlocal_count += 1
                    elif dist <= 2.0:
                        medium_count += 1
                    else:
                        long_count += 1

        avg_distance = sum(distances) / len(distances) if distances else 0.0
        max_distance = max(distances) if distances else 0.0

        spatial_analytics = {
            'average_distance_km': round(avg_distance, 2),
            'max_distance_km': round(max_distance, 2),
            'total_deliveries_analyzed': len(distances),
            'zones': {
                'hyperlocal': hyperlocal_count,
                'medium': medium_count,
                'long': long_count
            }
        }

        # Auto insights for platform growth/security
        insights = []
        if locked_orders_count > 0:
            insights.append(f"There are currently {locked_orders_count} locked suspicious orders requiring dispute resolution.")
        if suspicious_orders_count > 0:
            insights.append(f"A total of {suspicious_orders_count} orders have been flagged as suspicious across the system.")
        if store_leaderboard:
            insights.append(f"Top merchant \"{store_leaderboard[0]['store_name']}\" leads with {store_leaderboard[0]['order_count']} completed transactions.")
        if float(gpv) > 0.0:
            avg_comm = (float(platform_commission) / float(gpv)) * 100
            insights.append(f"Platform is operating at an average commission rate of {round(avg_comm, 2)}%.")
        
        if len(distances) > 0:
            insights.append(f"The average delivery distance is {round(avg_distance, 2)} km across the platform.")
            if hyperlocal_count > max(medium_count, long_count):
                insights.append("Hyper-local deliveries (<=0.5km) dominate, indicating high community concentration around merchants.")
            elif long_count > 0:
                insights.append(f"Long-range deliveries (>2km) comprise {round(long_count / len(distances) * 100, 1)}% of orders.")

        return Response({
            'kpi': kpi,
            'daily_trends': trends_list,
            'store_leaderboard': store_leaderboard,
            'state_funnel': state_funnel,
            'total_orders_count': total_orders_count,
            'safety_disputes': safety_disputes,
            'spatial_analytics': spatial_analytics,
            'insights': insights,
            'date_range': {'from': start.isoformat(), 'to': end.isoformat()}
        })
