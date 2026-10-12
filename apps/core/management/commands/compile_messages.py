"""Compile ``.po`` translation files into ``.mo`` without GNU gettext.

The build environment has no ``msgfmt``/``gettext`` available, so this command
implements the small subset of the GNU MO format the project needs: a flat
msgid → msgstr catalogue (no plural forms). It is intentionally dependency-free.

Usage::

    uv run python manage.py compile_messages
    uv run python manage.py compile_messages --locale ha
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), value)


def _unquote(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def parse_po(text: str) -> list[tuple[str, str]]:
    """Parse a simple ``.po`` file into ``(msgid, msgstr)`` pairs."""
    entries: list[tuple[str, str]] = []
    msgid: str | None = None
    msgstr: str | None = None
    mode: str | None = None

    def flush() -> None:
        nonlocal msgid, msgstr, mode
        if msgid is not None and msgstr is not None:
            entries.append((_unescape(msgid), _unescape(msgstr)))
        msgid = msgstr = None
        mode = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if line == "" and mode is not None:
                flush()
            continue
        if line.startswith("msgid "):
            if msgid is not None:
                flush()
            msgid = _unquote(line[len("msgid ") :])
            mode = "id"
        elif line.startswith("msgstr "):
            msgstr = _unquote(line[len("msgstr ") :])
            mode = "str"
        elif line.startswith("msgid_plural") or line.startswith("msgstr["):
            # Plural forms are not used by this project; ignore them.
            mode = None
        elif line.startswith('"'):
            fragment = _unquote(line)
            if mode == "id" and msgid is not None:
                msgid += fragment
            elif mode == "str" and msgstr is not None:
                msgstr += fragment
    flush()
    return entries


def write_mo(entries: list[tuple[str, str]], destination: Path) -> int:
    """Write ``entries`` to ``destination`` in GNU MO format; return the count."""
    pairs = [(msgid.encode("utf-8"), msgstr.encode("utf-8")) for msgid, msgstr in entries if msgstr]
    pairs.sort(key=lambda pair: pair[0])

    key_start = 7 * 4 + len(pairs) * 8 * 2
    key_offset = key_start
    value_offset = key_start + sum(len(key) + 1 for key, _ in pairs)

    keys = bytearray()
    values = bytearray()
    key_table = bytearray()
    value_table = bytearray()
    for key, value in pairs:
        key_table += struct.pack("<II", len(key), key_offset)
        value_table += struct.pack("<II", len(value), value_offset)
        keys += key + b"\x00"
        values += value + b"\x00"
        key_offset += len(key) + 1
        value_offset += len(value) + 1

    output = struct.pack(
        "<7I",
        0x950412DE,  # magic
        0,  # revision
        len(pairs),
        7 * 4,  # msgid table offset
        7 * 4 + len(pairs) * 8,  # msgstr table offset
        0,  # hash table size
        0,  # hash table offset
    )
    output += bytes(key_table) + bytes(value_table) + bytes(keys) + bytes(values)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output)
    return len(pairs)


class Command(BaseCommand):
    help = "Compile .po files to .mo without requiring GNU gettext."

    def add_arguments(self, parser):
        parser.add_argument(
            "--locale",
            dest="locales",
            action="append",
            help="Locale code to compile (repeatable). Defaults to every locale.",
        )

    def handle(self, *args, **options):
        locale_root = Path(settings.LOCALE_PATHS[0])
        if not locale_root.exists():
            raise CommandError(f"Locale directory not found: {locale_root}")

        selected = options.get("locales") or [
            path.name for path in sorted(locale_root.iterdir()) if path.is_dir()
        ]
        if not selected:
            raise CommandError("No locales found to compile.")

        for code in selected:
            po_path = locale_root / code / "LC_MESSAGES" / "django.po"
            if not po_path.exists():
                self.stderr.write(f"Skipping {code}: no {po_path}")
                continue
            entries = parse_po(po_path.read_text(encoding="utf-8"))
            mo_path = po_path.with_suffix(".mo")
            count = write_mo(entries, mo_path)
            self.stdout.write(self.style.SUCCESS(f"{code}: {count} messages -> {mo_path}"))
