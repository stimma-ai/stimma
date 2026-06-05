"""Tests for request metrics collection and admin routes."""

from core.request_metrics import RequestMetricsCollector


def test_request_metrics_collector_window_rollover():
    collector = RequestMetricsCollector(window_size=3)

    collector.record("GET", "/api/test", 200, 10.0)
    collector.record("GET", "/api/test", 200, 20.0)
    collector.record("GET", "/api/test", 500, 30.0)
    collector.record("GET", "/api/test", 404, 40.0)

    snapshot = collector.snapshot(sort_by="count", limit=10)
    row = snapshot["endpoints"][0]

    # First sample (10ms, 200) should be evicted by the 4th insert.
    assert row["count"] == 3
    assert row["avg_ms"] == 30.0
    assert row["max_ms"] == 40.0
    assert row["status_2xx"] == 1
    assert row["status_4xx"] == 1
    assert row["status_5xx"] == 1


def test_request_metrics_percentiles():
    collector = RequestMetricsCollector(window_size=500)
    for value in [10, 20, 30, 40, 50]:
        collector.record("GET", "/api/test", 200, float(value))

    snapshot = collector.snapshot(sort_by="p95_ms", limit=10)
    row = snapshot["endpoints"][0]
    assert row["p50_ms"] == 30.0
    assert row["p90_ms"] == 46.0
    assert row["p95_ms"] == 48.0
    assert row["p99_ms"] == 49.6


async def test_admin_request_metrics_endpoints(test_app, client):
    # Include admin routes in this test module.
    from routes import admin

    if not any(getattr(route, "path", "").startswith("/api/admin") for route in test_app.routes):
        test_app.include_router(admin.router)

    # Reset first so prior tests in the suite don't push /api/profiles
    # samples out of the 500-entry rolling window before we can observe them.
    await client.post("/api/admin/request-metrics/reset")

    # Generate a couple of requests first.
    await client.get("/api/profiles")
    await client.get("/api/markers")

    response = await client.get("/api/admin/request-metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "endpoints" in payload
    assert payload["window_size"] == 500
    assert payload["endpoint_count"] >= 1

    endpoints = payload["endpoints"]
    assert any(row["path"] == "/api/profiles" for row in endpoints)

    reset = await client.post("/api/admin/request-metrics/reset")
    assert reset.status_code == 200
    assert reset.json()["status"] == "success"

    response_after = await client.get("/api/admin/request-metrics")
    assert response_after.status_code == 200
    after_payload = response_after.json()
    # The GET call itself should now be the only sample (or one of very few),
    # but all previous endpoint history should be cleared.
    assert not any(row["path"] == "/api/profiles" for row in after_payload["endpoints"])
