from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg, F, Q
from django.db.models.functions import TruncDate, TruncHour, ExtractHour
from django.utils import timezone
from datetime import timedelta
from orders.models import Order, OrderItem


class SellerAnalyticsViewSet(viewsets.ViewSet):
    """
    Analytics endpoint for sellers.
    GET /api/analytics/seller/ — returns aggregated business metrics.
    Accepts ?from=YYYY-MM-DD&to=YYYY-MM-DD query params.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        user = request.user
        if user.role not in ['SELLER', 'ADMIN', 'SUPERUSER'] and not user.is_superuser:
            return Response({"error": "Permission denied"}, status=403)

        # Date range parsing
        today = timezone.now().date()
        from_date = request.query_params.get('from', (today - timedelta(days=30)).isoformat())
        to_date = request.query_params.get('to', today.isoformat())

        try:
            from datetime import date
            start = date.fromisoformat(from_date)
            end = date.fromisoformat(to_date)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        # Base queryset — seller sees only their store, admin sees all
        orders_qs = Order.objects.filter(
            created_at__date__gte=start,
            created_at__date__lte=end,
        )
        if user.role == 'SELLER':
            orders_qs = orders_qs.filter(store__owner=user)

        all_orders = orders_qs
        completed = orders_qs.filter(state='COMPLETED')

        # ── KPI Summary ──
        total_orders = all_orders.count()
        completed_orders = completed.count()
        total_revenue = completed.aggregate(total=Sum('total_amount'))['total'] or 0
        avg_order_value = completed.aggregate(avg=Avg('total_amount'))['avg'] or 0
        cancelled_orders = all_orders.filter(state='CANCELLED').count()

        # Query CommissionLedgerEntry for the period
        from billing.models import CommissionLedgerEntry
        ledger_qs = CommissionLedgerEntry.objects.filter(
            created_at__date__gte=start,
            created_at__date__lte=end,
        )
        if user.role == 'SELLER':
            ledger_qs = ledger_qs.filter(store__owner=user)

        total_commission = ledger_qs.aggregate(total=Sum('commission_amount'))['total'] or 0
        net_revenue = float(total_revenue) - float(total_commission)

        kpi = {
            'total_orders': total_orders,
            'completed_orders': completed_orders,
            'total_revenue': float(total_revenue),
            'total_commission': float(total_commission),
            'net_revenue': float(net_revenue),
            'avg_order_value': round(float(avg_order_value), 2),
            'cancelled_orders': cancelled_orders,
            'completion_rate': round((completed_orders / total_orders * 100) if total_orders > 0 else 0, 1),
        }

        # ── Revenue by Day ──
        # Group completed orders daily revenue
        daily_data = {}
        for item in (
            completed
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(revenue=Sum('total_amount'), count=Count('id'))
        ):
            day_str = item['day'].isoformat()
            daily_data[day_str] = {
                'day': day_str,
                'revenue': float(item['revenue']),
                'count': item['count'],
                'commission': 0.0,
                'net_revenue': float(item['revenue'])
            }
            
        # Merge in commission by day
        for item in (
            ledger_qs
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(commission=Sum('commission_amount'))
        ):
            day_str = item['day'].isoformat()
            comm = float(item['commission'])
            if day_str in daily_data:
                daily_data[day_str]['commission'] = comm
                daily_data[day_str]['net_revenue'] = daily_data[day_str]['revenue'] - comm
            else:
                daily_data[day_str] = {
                    'day': day_str,
                    'revenue': 0.0,
                    'count': 0,
                    'commission': comm,
                    'net_revenue': -comm
                }
                
        # Convert map to sorted list by date string
        revenue_by_day = sorted(daily_data.values(), key=lambda x: x['day'])

        # ── Orders by Hour ──
        orders_by_hour = list(
            all_orders
            .annotate(hour=ExtractHour('created_at'))
            .values('hour')
            .annotate(count=Count('id'))
            .order_by('hour')
        )
        # Fill missing hours with 0
        hour_map = {h['hour']: h['count'] for h in orders_by_hour}
        orders_by_hour = [{'hour': h, 'count': hour_map.get(h, 0)} for h in range(24)]

        # ── Top Products ──
        top_products = list(
            OrderItem.objects
            .filter(order__in=completed)
            .values(product_name=F('product__name'))
            .annotate(
                total_sold=Sum('quantity'),
                total_revenue=Sum(F('unit_price') * F('quantity'))
            )
            .order_by('-total_revenue')[:10]
        )
        for p in top_products:
            p['total_revenue'] = float(p['total_revenue'])

        # ── Fulfillment Breakdown ──
        fulfillment_breakdown = list(
            completed
            .values('fulfillment_mode')
            .annotate(count=Count('id'), revenue=Sum('total_amount'))
            .order_by('-count')
        )
        for f_item in fulfillment_breakdown:
            f_item['revenue'] = float(f_item['revenue'])

        # ── Order State Breakdown ──
        state_breakdown = list(
            all_orders
            .values('state')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        # ── Auto Insights ──
        insights = []
        if revenue_by_day:
            best_day = max(revenue_by_day, key=lambda d: d['revenue'])
            insights.append(f"Your best revenue day was {best_day['day']} with {best_day['count']} orders.")

        if orders_by_hour:
            busiest = max(orders_by_hour, key=lambda h: h['count'])
            if busiest['count'] > 0:
                insights.append(f"Your busiest hour is {busiest['hour']}:00 with {busiest['count']} orders.")

        if fulfillment_breakdown:
            top_mode = fulfillment_breakdown[0]
            total_completed = sum(f_item['count'] for f_item in fulfillment_breakdown)
            pct = round(top_mode['count'] / total_completed * 100) if total_completed > 0 else 0
            insights.append(f"{top_mode['fulfillment_mode'].replace('_', ' ').title()} makes up {pct}% of your completed orders.")

        if kpi['completion_rate'] < 80 and total_orders > 5:
            insights.append(f"Your completion rate is {kpi['completion_rate']}%. Consider investigating why {cancelled_orders} orders were cancelled.")

        if top_products:
            insights.append(f"Your top seller is \"{top_products[0]['product_name']}\" with {top_products[0]['total_sold']} units sold.")

        return Response({
            'kpi': kpi,
            'revenue_by_day': revenue_by_day,
            'orders_by_hour': orders_by_hour,
            'top_products': top_products,
            'fulfillment_breakdown': fulfillment_breakdown,
            'state_breakdown': state_breakdown,
            'insights': insights,
            'date_range': {'from': start.isoformat(), 'to': end.isoformat()},
        })
