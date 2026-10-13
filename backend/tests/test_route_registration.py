"""Catch duplicate HTTP routes that silently shadow a different implementation."""

from collections import Counter


def _http_routes(router, prefix=""):
    for route in router.routes:
        # Recent FastAPI versions keep include_router() as a nested route;
        # older versions flatten it into the parent router.
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _http_routes(included, prefix + route.include_context.prefix)
        else:
            for method in getattr(route, "methods", ()):
                yield method, prefix + route.path


def test_api_routes_have_unique_method_and_path(test_app):
    # The fixture supplies a simplified root health endpoint; audit API routes
    # shared with the production app rather than that fixture-only override.
    routes = Counter(route for route in _http_routes(test_app) if route[1].startswith("/api/"))
    duplicates = {route: count for route, count in routes.items() if count > 1}
    assert not duplicates, f"HTTP handlers shadow one another: {duplicates}"
