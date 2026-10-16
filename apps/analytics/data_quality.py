"""Data-quality checks (Phase 11 — Task 18).

These checks are **read-only and reporting-only**: they surface integrity signals
that would skew analytics, but they never mutate a business or financial record.
Each check returns a count and a small sample so an operator can investigate.

Checks are intentionally conservative — they look for states that are objectively
inconsistent (settled money without a verification timestamp, reserved stock above
on-hand, a delivered shipment with no arrival date) rather than judgement calls.
"""

from __future__ import annotations

from apps.catalog.models import Product, ProductListing, StockBalance
from apps.export.models import ExportShipment, ShipmentStatus
from apps.orders.models import OrderStatus
from apps.orders.payment_models import Invoice, InvoiceState, Payment, PaymentState

SETTLED = (PaymentState.PAID, PaymentState.REFUNDED, PaymentState.PARTIALLY_REFUNDED)


def _settled_payment_without_verified_at() -> int:
    return Payment.objects.filter(status__in=SETTLED, verified_at__isnull=True).count()


def _settled_payment_without_amount() -> int:
    return Payment.objects.filter(status__in=SETTLED, verified_amount__isnull=True).count()


def _cancelled_orders_with_captured_money() -> int:
    return (
        Payment.objects.filter(order__status=OrderStatus.CANCELLED, status__in=SETTLED)
        .values("order_id")
        .distinct()
        .count()
    )


def _paid_invoices_without_settled_payment() -> int:
    return (
        Invoice.objects.filter(status=InvoiceState.PAID)
        .exclude(order__payments__status__in=SETTLED)
        .count()
    )


def _negative_stock_balances() -> int:
    return StockBalance.objects.filter(on_hand__lt=0).count()


def _reserved_exceeds_on_hand() -> int:
    from django.db.models import F

    return StockBalance.objects.filter(reserved__gt=F("on_hand")).count()


def _listings_without_package_unit() -> int:
    return ProductListing.objects.filter(package_unit__isnull=True).count()


def _products_without_unit() -> int:
    return Product.objects.filter(unit__isnull=True).count()


def _delivered_shipments_without_arrival() -> int:
    from django.db.models import Q

    return (
        ExportShipment.objects.filter(status=ShipmentStatus.DELIVERED)
        .filter(Q(actual_arrival__isnull=True))
        .count()
    )


def _duplicate_payment_provider_references() -> int:
    from django.db.models import Count as _Count

    duplicates = (
        Payment.objects.exclude(provider_reference="")
        .values("provider_reference")
        .annotate(count=_Count("id"))
        .filter(count__gt=1)
        .count()
    )
    return duplicates


CHECKS: tuple[tuple[str, str, str, str, object], ...] = (
    (
        "settled_payment_without_verified_at",
        "Settled payments missing a verification timestamp",
        (
            "A payment is in a settled state but has no verified_at. Analytics windows "
            "on verified_at, so it would be invisible."
        ),
        "high",
        _settled_payment_without_verified_at,
    ),
    (
        "settled_payment_without_amount",
        "Settled payments missing a verified amount",
        "A settled payment has no verified_amount; it cannot be counted as verified receipts.",
        "high",
        _settled_payment_without_amount,
    ),
    (
        "cancelled_order_with_captured_money",
        "Cancelled orders with captured payments",
        "Money was verified against an order that is now cancelled. Review for a refund.",
        "high",
        _cancelled_orders_with_captured_money,
    ),
    (
        "paid_invoice_without_settled_payment",
        "Paid invoices without a settled payment",
        "An invoice is marked paid but has no settled payment behind it.",
        "high",
        _paid_invoices_without_settled_payment,
    ),
    (
        "negative_stock_balances",
        "Negative stock balances",
        "A stock balance is below zero, which makes availability metrics unreliable.",
        "medium",
        _negative_stock_balances,
    ),
    (
        "reserved_exceeds_on_hand",
        "Reserved stock exceeds on-hand stock",
        "More stock is reserved than physically on hand.",
        "medium",
        _reserved_exceeds_on_hand,
    ),
    (
        "listings_without_package_unit",
        "Listings missing a package unit",
        "A listing has no unit of measure, so its quantities cannot be compared with others.",
        "medium",
        _listings_without_package_unit,
    ),
    (
        "products_without_unit",
        "Products missing a unit of measure",
        "A product has no unit of measure, so its quantities cannot be compared with others.",
        "low",
        _products_without_unit,
    ),
    (
        "delivered_shipments_without_arrival",
        "Delivered shipments missing an arrival date",
        "A shipment is delivered but has no actual arrival date.",
        "medium",
        _delivered_shipments_without_arrival,
    ),
    (
        "duplicate_payment_provider_references",
        "Duplicate provider references",
        "The same provider reference appears on more than one payment, which risks double "
        "counting.",
        "high",
        _duplicate_payment_provider_references,
    ),
)


def run_checks() -> list[dict]:
    """Run every check and return structured results (never raises)."""
    results = []
    for key, label, description, severity, runner in CHECKS:
        try:
            count = runner()
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide the rest
            count = None
            description = f"{description} (check errored: {exc})"
        results.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "severity": severity,
                "count": count,
                "ok": count == 0,
            }
        )
    return results


def summary(results: list[dict]) -> dict:
    total = sum((r["count"] or 0) for r in results)
    failing = [r for r in results if not r["ok"]]
    return {
        "issue_count": total,
        "failing_checks": len(failing),
        "check_count": len(results),
        "healthy": not failing,
    }


__all__ = ["CHECKS", "run_checks", "summary"]
