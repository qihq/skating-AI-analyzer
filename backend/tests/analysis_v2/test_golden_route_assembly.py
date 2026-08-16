from app.main import app


def test_g2_status_route_is_registered_in_the_assembled_application() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/golden/v2/g2/status" in paths
    assert "/api/golden/v2/g2/freeze" in paths
