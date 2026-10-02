"""Gateway wiring for /v1/search and /v1/features/linked (no lifespan: no workers start)."""

from conftest import NOW
from fastapi.testclient import TestClient

from tandem_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"


def client(world):
    world.a.close()
    world.app.unlink()  # the gateway owns app.db; the fixture's plain file would be refused
    gateway = Gateway(world.home, discovery=lambda: [], prewarm_debounce_s=3600.0)
    app = gateway.app(token=TOKEN, port=8765)
    return TestClient(app, base_url="http://127.0.0.1:8765",
                      headers={"Authorization": f"Bearer {TOKEN}"}), gateway


def test_search_and_linked_routes(world):
    world.project("p1", "Tandem 前端")
    world.session("s1", project="p1", title="修复登录页面", started=NOW)
    world.message("s1", "登录页面报错")
    world.call("s1", skill="pdf-tools")
    world.item("cat-1", "skill", "pdf_tools")
    world.inventory("claude_code", [{"inv_id": "s", "type": "skill", "name": "pdf-tools"}])
    http, gateway = client(world)
    try:
        body = http.get("/v1/search", params={"q": "登录页面", "kinds": "session,message"}).json()
        assert body["counts"] == {"session": 1, "message": 1}
        assert body["results"][0]["ref"]["page"] == "session"
        inv = http.get("/v1/search", params={"q": "pdf", "kinds": "inventory,catalog"}).json()
        assert {r["kind"] for r in inv["results"]} == {"inventory", "catalog"}
        assert http.get("/v1/search", params={"q": "  "}).status_code == 400
        assert http.get("/v1/search", params={"q": "x", "kinds": "nope"}).status_code == 400
        linked = http.get("/v1/features/linked").json()
        item = linked["items"][0]
        assert item["catalog"]["item_id"] == "cat-1" and item["usage"]["calls_total"] == 1
        assert linked["coverage"]["catalog"] == "available"
    finally:
        gateway.close()
