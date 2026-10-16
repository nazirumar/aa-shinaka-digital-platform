"""Support package for the ``seed_data`` management command.

Django only discovers single-file management commands, so the actual
:class:`~django.core.management.base.BaseCommand` lives in
``seed_data.py`` next to this package. This package holds the heavy
lifting: :mod:`.content` (declarative data), :mod:`.media` (image
acquisition) and :mod:`.builders` (domain seeders).
"""
