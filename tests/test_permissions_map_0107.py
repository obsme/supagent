"""(0.10.7) The list of a document's pages (a new endpoint of the admin page) answered "Access is Denied" to every
admin: its method had no entry in the view's method_permission_name, so it asked for a permission no role has.
Every endpoint of supagent's views is mapped to one of its view's permissions (read, write, edit, delete)."""
from __future__ import annotations


def test_every_endpoint_has_a_permission_of_its_view(app):
    from supagent import views as V

    missing = []
    for cls in [c for c in vars(V).values() if isinstance(c, type) and getattr(c, "method_permission_name", None)]:
        mapped = cls.method_permission_name
        for name, fn in vars(cls).items():
            if callable(fn) and getattr(fn, "_urls", None) and name not in mapped:
                missing.append(f"{cls.__name__}.{name}")
    assert missing == []
