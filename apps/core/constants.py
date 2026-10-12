"""Cross-cutting constants.

Business divisions are part of the fixed company structure (not user-editable
product categories, which live in the database under ``apps.catalog``).
"""

from django.db import models


class BusinessDivision(models.TextChoices):
    CONSULTANCY = "consultancy", "Agricultural Consultancy"
    FARMING_SERVICES = "farming_services", "Farming Services"
    MARKETING = "marketing", "Agricultural Marketing"
    STORAGE = "storage", "Storage and Warehousing"
    EXPORT = "export", "Agricultural Export"
    PRODUCT_SALES = "product_sales", "Agricultural Product Sales"
    TRAINING = "training", "Training and Academy"


# Oil and Gas is explicitly out of scope for this platform.
EXCLUDED_DIVISIONS = ("oil_gas",)
