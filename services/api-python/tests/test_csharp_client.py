from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.analyzers.scanner import collect_files
from app.services import csharp_client
from app.services.csharp_client import MAX_ANALYZER_FILE_BYTES, analyze_workspace

CSHARP_CONTROLLER = """
namespace Shop.Api.Controllers;

public class OrderController
{
    private readonly IOrderService _orders;

    public OrderController(IOrderService orders)
    {
        _orders = orders;
    }
}
"""


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> None:
    real_client = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = handler
        return real_client(*args, **kwargs)

    monkeypatch.setattr(csharp_client.httpx, "AsyncClient", factory)


def test_analyze_workspace_posts_file_contents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "Controllers").mkdir()
    (tmp_path / "Controllers" / "OrderController.cs").write_text(CSHARP_CONTROLLER, encoding="utf-8")
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"nodes": [], "relations": [], "warnings": []})

    _patch_transport(monkeypatch, httpx.MockTransport(handler))

    result = asyncio.run(analyze_workspace(tmp_path, ["Controllers/OrderController.cs"]))

    assert result.reachable is True
    assert sent == [
        {
            "rootPath": str(tmp_path),
            "files": [
                {"path": "Controllers/OrderController.cs", "content": CSHARP_CONTROLLER},
            ],
        }
    ]


def test_analyze_workspace_skips_oversized_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "Small.cs").write_text("public class Small { }", encoding="utf-8")
    (tmp_path / "Huge.cs").write_bytes(b"x" * (MAX_ANALYZER_FILE_BYTES + 1))
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"nodes": [], "relations": [], "warnings": []})

    _patch_transport(monkeypatch, httpx.MockTransport(handler))

    result = asyncio.run(analyze_workspace(tmp_path, ["Small.cs", "Huge.cs"]))

    assert [item["path"] for item in sent[0]["files"]] == ["Small.cs"]
    assert any("oversized" in warning for warning in result.warnings)


def test_analyze_workspace_degrades_when_analyzer_is_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "Small.cs").write_text("public class Small { }", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_transport(monkeypatch, httpx.MockTransport(handler))

    result = asyncio.run(analyze_workspace(tmp_path, ["Small.cs"]))

    assert result.reachable is False
    assert result.nodes == []
    assert any("unreachable" in warning for warning in result.warnings)


def test_scanner_ignores_generated_csharp_files(tmp_path: Path) -> None:
    (tmp_path / "Order.cs").write_text("public class Order { }", encoding="utf-8")
    (tmp_path / "Order.g.cs").write_text("public class Generated { }", encoding="utf-8")
    (tmp_path / "Form1.Designer.cs").write_text("partial class Form1 { }", encoding="utf-8")

    scan = collect_files(tmp_path)

    assert scan.csharp == ["Order.cs"]
