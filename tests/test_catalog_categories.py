"""Phase 4 tests: nested categories, paths, reorder, safe delete, soft delete."""

from __future__ import annotations

import pytest
from catalog_helpers import make_category, make_product
from django.core.exceptions import ValidationError

from apps.catalog import services
from apps.catalog.models import MAX_CATEGORY_DEPTH, Category

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Hierarchy & paths
# ---------------------------------------------------------------------------


def test_root_category_path_is_blank_and_depth_zero():
    root = make_category(name="Grains")

    assert root.path == ""
    assert root.depth == 0
    assert root.slug == "grains"


def test_child_encodes_ancestor_chain_in_path():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)
    grandchild = make_category(name="Local rice", parent=child)

    assert child.path == f"{root.pk}/"
    assert child.depth == 1
    assert grandchild.path == f"{root.pk}/{child.pk}/"
    assert grandchild.depth == 2


def test_ancestors_returns_ordered_chain():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)
    grandchild = make_category(name="Local rice", parent=child)

    assert [c.pk for c in grandchild.ancestors()] == [root.pk, child.pk]
    assert root.ancestors() == []


def test_descendants_and_active_children():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)
    grandchild = make_category(name="Local rice", parent=child)
    inactive = make_category(name="Archived child", parent=root, is_active=False)

    descendant_ids = set(root.descendants().values_list("pk", flat=True))
    assert descendant_ids == {child.pk, grandchild.pk, inactive.pk}
    assert set(root.active_children().values_list("pk", flat=True)) == {child.pk}


def test_breadcrumbs_include_self_last():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)

    crumbs = child.breadcrumbs()

    assert [c["label"] for c in crumbs] == ["Grains", "Rice"]
    assert crumbs[-1]["url"] == child.get_absolute_url()


def test_moving_category_repaths_descendants():
    first = make_category(name="Grains")
    second = make_category(name="Legumes")
    child = make_category(name="Rice", parent=first)
    grandchild = make_category(name="Local rice", parent=child)

    services.update_category(child, parent=second)

    child.refresh_from_db()
    grandchild.refresh_from_db()
    assert child.path == f"{second.pk}/"
    assert grandchild.path == f"{second.pk}/{child.pk}/"
    assert grandchild.ancestors()[0].pk == second.pk


def test_is_leaf_reflects_children():
    root = make_category(name="Grains")
    assert root.is_leaf() is True

    make_category(name="Rice", parent=root)
    assert root.is_leaf() is False


# ---------------------------------------------------------------------------
# Validation: cycles, duplicates, depth
# ---------------------------------------------------------------------------


def test_category_cannot_be_its_own_parent():
    root = make_category(name="Grains")
    root.parent = root

    with pytest.raises(ValidationError):
        root.full_clean()


def test_category_cannot_be_parented_to_its_own_descendant():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)

    with pytest.raises(ValidationError):
        services.update_category(root, parent=child)


def test_duplicate_root_name_is_rejected_case_insensitively():
    make_category(name="Grains")

    with pytest.raises(ValidationError):
        make_category(name="grains")


def test_same_name_is_allowed_under_different_parents():
    first = make_category(name="Grains")
    second = make_category(name="Legumes")

    a = make_category(name="Processed", parent=first)
    b = make_category(name="Processed", parent=second)

    assert a.parent_id == first.pk
    assert b.parent_id == second.pk
    assert b.path == f"{second.pk}/"


def test_nesting_depth_is_limited():
    parent = make_category(name="Level 0")
    for level in range(1, MAX_CATEGORY_DEPTH + 1):
        parent = make_category(name=f"Level {level}", parent=parent)

    with pytest.raises(ValidationError):
        make_category(name="Too deep", parent=parent)


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


def test_slug_collisions_are_suffixed():
    first = make_category(name="Fresh Produce")
    second = make_category(name="Fresh Produce!")

    assert first.slug == "grains" or first.slug == "fresh-produce"
    assert first.slug != second.slug
    assert second.slug.startswith("fresh-produce")


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


def test_reorder_swaps_sort_order_among_siblings():
    first = make_category(name="Grains", sort_order=0)
    second = make_category(name="Legumes", sort_order=1)
    third = make_category(name="Tubers", sort_order=2)

    services.reorder_category(second, step=-1)

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()
    assert [second.sort_order, first.sort_order, third.sort_order] == [0, 1, 2]


def test_reorder_at_edge_is_a_noop():
    first = make_category(name="Grains", sort_order=0)
    second = make_category(name="Legumes", sort_order=1)

    services.reorder_category(first, step=-1)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.sort_order == 0
    assert second.sort_order == 1


# ---------------------------------------------------------------------------
# Delete: safe delete & soft delete
# ---------------------------------------------------------------------------


def test_archive_refuses_category_with_children():
    root = make_category(name="Grains")
    make_category(name="Rice", parent=root)

    with pytest.raises(ValidationError):
        services.archive_category(root)

    assert Category.objects.filter(pk=root.pk).exists()


def test_archive_refuses_category_with_products():
    root = make_category(name="Grains")
    make_product(root)

    with pytest.raises(ValidationError):
        services.archive_category(root)


def test_archive_soft_deletes_empty_category():
    category = make_category(name="Grains")

    services.archive_category(category)

    assert Category.objects.filter(pk=category.pk).count() == 0
    archived = Category.all_objects.get(pk=category.pk)
    assert archived.is_deleted is True
    assert archived.deleted_at is not None


def test_archived_category_hidden_from_public_selector():
    from apps.catalog import selectors

    category = make_category(name="Grains")
    services.archive_category(category)

    assert selectors.category_by_slug("grains") is None


def test_descendants_excludes_archived_children():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)
    services.archive_category(child)

    assert root.descendants().count() == 0
    assert Category.all_objects.filter(parent=root).count() == 1


def test_category_archive_is_refused_while_products_reference_it():
    root = make_category(name="Grains")
    child = make_category(name="Rice", parent=root)
    make_product(child, name="Ofada rice")

    with pytest.raises(ValidationError):
        services.archive_category(child)
    assert Category.objects.filter(pk=child.pk).exists()
