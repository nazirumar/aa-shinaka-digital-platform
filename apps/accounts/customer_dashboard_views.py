"""Staff customer overview (Phase 10, Task 16).

Read-only, capability-gated staff screens. Financial figures are only shown to
staff who hold the finance capability; every other section is real customer
data taken from the owning domain models.
"""

from __future__ import annotations

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from . import selectors
from .models import User, UserRole
from .permissions import capability_required, has_capability
from .roles import Capability


@capability_required(Capability.CUSTOMERS_VIEW)
def customer_list(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    status = request.GET.get("status", "")
    queryset = selectors.customer_directory(query=query, status=status)
    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/customer_dashboard_list.html",
        {
            "page_title": "Customers",
            "page_obj": page,
            "customers": page.object_list,
            "query": query,
            "status": status,
        },
    )


@capability_required(Capability.CUSTOMERS_VIEW)
def customer_detail(request: HttpRequest, pk) -> HttpResponse:
    customer = get_object_or_404(User, pk=pk, role=UserRole.CUSTOMER)
    return render(
        request,
        "accounts/customer_dashboard_detail.html",
        {
            "page_title": f"Customer · {customer.email}",
            "customer": customer,
            "overview": selectors.customer_overview(customer),
            "can_view_finance": has_capability(request.user, Capability.FINANCE_MANAGE),
        },
    )
