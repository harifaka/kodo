from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ENTITY_PATH = "src/main/java/com/acme/shop/entity/Order.java"
CUSTOMER_PATH = "src/main/java/com/acme/shop/entity/Customer.java"

JAVA_ENTITY = """package com.acme.shop.entity;

public class Order {
    private String code;

    // Hand-written business rule - must stay verbatim.
    public boolean isPaid() {
        return code != null && !code.isBlank();
    }
}
"""

JAVA_CUSTOMER = """package com.acme.shop.entity;

public class Customer {
    private String name;
}
"""

ADD_FIELD_OP = {
    "op": "add_field",
    "filePath": ENTITY_PATH,
    "typeName": "Order",
    "field": {
        "name": "total",
        "type": "BigDecimal",
        "visibility": "private",
        "annotations": ["@NotNull"],
    },
}

ADD_CUSTOMER_FIELD_OP = {
    "op": "add_field",
    "filePath": CUSTOMER_PATH,
    "typeName": "Customer",
    "field": {"name": "email", "type": "String", "visibility": "private", "annotations": []},
}

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _write_workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "workspace"
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "kodo@example.com")
    _git(root, "config", "user.name", "Kodo Tests")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")


def _dry_run(client: TestClient, root: Path, operations: list[dict]) -> list[dict]:
    response = client.post("/api/v1/dry-run", json={"rootPath": str(root), "operations": operations})
    assert response.status_code == 200, response.text
    return response.json()["patches"]


def _apply_body(root: Path, patches: list[dict], **flags: bool) -> dict:
    return {
        "rootPath": str(root),
        "patches": [
            {
                "filePath": patch["filePath"],
                "expectedSha256": patch["originalSha256"],
                "proposedContent": patch["proposedContent"],
            }
            for patch in patches
        ],
        **flags,
    }


@requires_git
def test_clean_repo_apply_modifies_disk_and_keeps_business_methods(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    _init_repo(root)

    status = client.get("/api/v1/git/status", params={"root": str(root)})
    assert status.status_code == 200
    assert status.json()["isGitRepo"] is True
    assert status.json()["gitAvailable"] is True
    assert status.json()["isDirty"] is False
    assert status.json()["branch"]

    patches = _dry_run(client, root, [ADD_FIELD_OP])
    original_bytes = (root / ENTITY_PATH).read_bytes()
    assert patches[0]["originalSha256"] == hashlib.sha256(original_bytes).hexdigest()

    response = client.post("/api/v1/apply", json=_apply_body(root, patches))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["appliedFiles"] == [ENTITY_PATH]
    assert body["applyId"]
    assert body["gitStatus"]["isDirty"] is True

    saved = (root / ENTITY_PATH).read_text(encoding="utf-8")
    assert "private BigDecimal total;" in saved
    assert "@NotNull" in saved
    assert "// Hand-written business rule - must stay verbatim." in saved
    assert "public boolean isPaid() {" in saved
    assert "return code != null && !code.isBlank();" in saved


@requires_git
def test_apply_preserves_crlf_line_endings_and_rollback_is_byte_exact(
    client: TestClient,
    tmp_path: Path,
) -> None:
    crlf_source = JAVA_ENTITY.replace("\n", "\r\n")
    root = _write_workspace(tmp_path, {ENTITY_PATH: crlf_source})
    _init_repo(root)

    patches = _dry_run(client, root, [ADD_FIELD_OP])
    assert "\r\n" in patches[0]["proposedContent"]

    applied = client.post("/api/v1/apply", json=_apply_body(root, patches))
    assert applied.status_code == 200, applied.text

    saved = (root / ENTITY_PATH).read_bytes()
    assert b"\r\n" in saved
    assert b"\n" not in saved.replace(b"\r\n", b""), "apply must not mix line endings"

    rollback = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": applied.json()["applyId"], "force": False},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["restoredFiles"] == [ENTITY_PATH]
    assert (root / ENTITY_PATH).read_bytes() == crlf_source.encode("utf-8")


@requires_git
def test_dirty_git_tree_is_blocked_until_allowed(client: TestClient, tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    _init_repo(root)

    edited = JAVA_ENTITY + "// uncommitted local edit\n"
    (root / ENTITY_PATH).write_bytes(edited.encode("utf-8"))
    patches = _dry_run(client, root, [ADD_FIELD_OP])

    blocked = client.post("/api/v1/apply", json=_apply_body(root, patches))
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "GIT_DIRTY"
    assert ENTITY_PATH in detail["dirtyFiles"]
    assert (root / ENTITY_PATH).read_text(encoding="utf-8") == edited

    allowed = client.post("/api/v1/apply", json=_apply_body(root, patches, allowDirty=True))
    assert allowed.status_code == 200, allowed.text
    assert "private BigDecimal total;" in (root / ENTITY_PATH).read_text(encoding="utf-8")


def test_non_git_workspace_is_blocked_until_allowed(client: TestClient, tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    patches = _dry_run(client, root, [ADD_FIELD_OP])

    status = client.get("/api/v1/git/status", params={"root": str(root)})
    assert status.status_code == 200
    assert status.json()["isGitRepo"] is False
    assert status.json()["warning"]

    blocked = client.post("/api/v1/apply", json=_apply_body(root, patches))
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "NOT_A_GIT_REPO"
    assert (root / ENTITY_PATH).read_bytes() == JAVA_ENTITY.encode("utf-8")

    allowed = client.post("/api/v1/apply", json=_apply_body(root, patches, allowNonGit=True))
    assert allowed.status_code == 200, allowed.text
    assert "private BigDecimal total;" in (root / ENTITY_PATH).read_text(encoding="utf-8")


@requires_git
def test_externally_modified_file_aborts_the_whole_batch(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY, CUSTOMER_PATH: JAVA_CUSTOMER})
    _init_repo(root)

    patches = _dry_run(client, root, [ADD_FIELD_OP, ADD_CUSTOMER_FIELD_OP])
    assert {patch["filePath"] for patch in patches} == {ENTITY_PATH, CUSTOMER_PATH}

    (root / CUSTOMER_PATH).write_bytes(JAVA_CUSTOMER.replace("name", "displayName").encode("utf-8"))
    before = {path: (root / path).read_bytes() for path in (ENTITY_PATH, CUSTOMER_PATH)}

    response = client.post("/api/v1/apply", json=_apply_body(root, patches, allowDirty=True))

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "STALE_FILE"
    assert detail["paths"] == [CUSTOMER_PATH]
    assert {path: (root / path).read_bytes() for path in before} == before


def test_apply_rejects_path_traversal(client: TestClient, tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    secret = (tmp_path / "secret.java").resolve()
    secret.write_bytes(b"class Secret { }")

    response = client.post(
        "/api/v1/apply",
        json={
            "rootPath": str(root),
            "patches": [
                {
                    "filePath": "../secret.java",
                    "expectedSha256": hashlib.sha256(secret.read_bytes()).hexdigest(),
                    "proposedContent": "leaked",
                }
            ],
            "allowNonGit": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PATH_REJECTED"
    assert secret.read_bytes() == b"class Secret { }"


def test_apply_rejects_absolute_paths(client: TestClient, tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    target = (root / ENTITY_PATH).resolve()

    response = client.post(
        "/api/v1/apply",
        json={
            "rootPath": str(root),
            "patches": [
                {
                    "filePath": target.as_posix(),
                    "expectedSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "proposedContent": "overwritten",
                }
            ],
            "allowNonGit": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PATH_REJECTED"
    assert target.read_bytes() == JAVA_ENTITY.encode("utf-8")


@requires_git
def test_rollback_restores_exact_original_bytes_and_is_single_use(
    client: TestClient,
    tmp_path: Path,
) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    _init_repo(root)
    original = (root / ENTITY_PATH).read_bytes()

    patches = _dry_run(client, root, [ADD_FIELD_OP])
    applied = client.post("/api/v1/apply", json=_apply_body(root, patches))
    assert applied.status_code == 200
    assert (root / ENTITY_PATH).read_bytes() != original

    rollback = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": applied.json()["applyId"], "force": False},
    )
    assert rollback.status_code == 200
    assert rollback.json()["restoredFiles"] == [ENTITY_PATH]
    assert (root / ENTITY_PATH).read_bytes() == original

    again = client.post(
        "/api/v1/apply/rollback",
        json={"applyId": applied.json()["applyId"], "force": False},
    )
    assert again.status_code == 404
    assert again.json()["detail"]["code"] == "UNKNOWN_APPLY"


@requires_git
def test_rollback_refuses_when_file_changed_after_apply(client: TestClient, tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {ENTITY_PATH: JAVA_ENTITY})
    _init_repo(root)
    original = (root / ENTITY_PATH).read_bytes()

    patches = _dry_run(client, root, [ADD_FIELD_OP])
    applied = client.post("/api/v1/apply", json=_apply_body(root, patches))
    assert applied.status_code == 200
    apply_id = applied.json()["applyId"]

    (root / ENTITY_PATH).write_bytes(b"// edited after apply\n")

    blocked = client.post("/api/v1/apply/rollback", json={"applyId": apply_id, "force": False})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "STALE_FILE"
    assert blocked.json()["detail"]["paths"] == [ENTITY_PATH]
    assert (root / ENTITY_PATH).read_bytes() == b"// edited after apply\n"

    forced = client.post("/api/v1/apply/rollback", json={"applyId": apply_id, "force": True})
    assert forced.status_code == 200
    assert (root / ENTITY_PATH).read_bytes() == original
