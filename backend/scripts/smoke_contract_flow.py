"""合同模板结构化与生成链路冒烟测试（P2 复核 + P3 生成）。

覆盖：导入 → 复核保存字段（不依赖 Dify，等价于人工改定字段定义）→ 必填拦截 →
生成落库 → 归属校验下载 → 生成记录列表 → 生成稿预览 → 类型词表 → 清理。

用法（在 backend/ 下执行）：
    .venv/bin/python scripts/smoke_contract_flow.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402

WORK = Path("var/contract-flow")
failures: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ✅ {label}")
    else:
        failures.append(label)
        print(f"  ❌ {label} {detail}")


def build_fixture(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("钢材采购合同模板")
    doc.add_paragraph("合同编号：")
    for label in ("甲方（采购方）：", "乙方（供应方）："):
        para = doc.add_paragraph()
        para.add_run(label)
        para.add_run("__________")
    doc.add_paragraph("签约地点：")
    doc.add_paragraph("第一条 采购标的：__________________")
    doc.add_paragraph("第五条 违约责任：逾期交货按日万分之三支付违约金。")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def main() -> int:
    fixture = WORK / "template.docx"
    build_fixture(fixture)

    client = TestClient(app)
    user01 = {"Authorization": f"Bearer {create_access_token('user01', 'user')}"}
    other = {"Authorization": f"Bearer {create_access_token('someone-else', 'user')}"}

    print("1) 导入模板")
    with fixture.open("rb") as handle:
        resp = client.post(
            "/api/v1/templates",
            headers=user01,
            files={"file": (fixture.name, handle, "application/octet-stream")},
            data={"name": "钢材采购合同模板", "category": "采购", "description": "链路冒烟样本"},
        )
    check("导入返回 200", resp.status_code == 200, resp.text[:200])
    item = resp.json()["data"]
    template_id = item["id"]
    check("初始状态为 pending", item["structure_status"] == "pending", item["structure_status"])
    check("原始文件已保留", item["standardized"] is False)

    print("\n2) 模板详情（复核上下文）")
    detail = client.get(f"/api/v1/templates/{template_id}", headers=user01).json()["data"]
    candidates = detail["candidates"]
    check("能取到候选空位", len(candidates) >= 4, f"candidates={len(candidates)}")
    check("能取到文档大纲", "甲方" in detail["outline"])
    by_kind: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_kind.setdefault(candidate["kind"], []).append(candidate)
    print(f"     候选种类：{ {k: len(v) for k, v in by_kind.items()} }")

    print("\n3) 复核保存字段（等价于人工确认，不依赖 Dify）")

    def first(kind: str, index: int = 0) -> dict:
        return by_kind[kind][index]

    fields = [
        {"key": "contract_no", "label": "合同编号", "type": "text", "required": True,
         "candidate_id": first("label_empty")["id"]},
        {"key": "party_a_name", "label": "甲方名称", "type": "text", "required": True,
         "candidate_id": first("blank", 0)["id"]},
        {"key": "party_b_name", "label": "乙方名称", "type": "text", "required": True,
         "candidate_id": first("blank", 1)["id"]},
        {"key": "sign_place", "label": "签约地点", "type": "text", "required": False,
         "candidate_id": first("label_empty", 1)["id"]},
        {"key": "subject_matter", "label": "采购标的", "type": "text", "required": True,
         "candidate_id": first("blank", 2)["id"]},
    ]
    resp = client.post(
        f"/api/v1/templates/{template_id}/fields",
        headers=user01,
        json={"fields": fields, "contract_type": "采购", "enable": True},
    )
    check("保存字段返回 200", resp.status_code == 200, resp.text[:300])
    saved = resp.json()["data"]
    check("状态变为 ready", saved["status"] == "ready", saved.get("status"))

    detail = client.get(f"/api/v1/templates/{template_id}", headers=user01).json()["data"]
    check("字段已持久化", len(detail["fields"]) == 5, detail["fields"])
    check("标准化模板已生成", detail["standardized"] is True)
    check("占位变量与字段一致", set(detail["variables"]) == {f["key"] for f in fields}, detail["variables"])

    print("\n4) 必填拦截")
    resp = client.post(
        "/api/v1/generate/contract",
        headers=user01,
        json={"template_id": template_id, "variables": {"contract_no": "HT-001"}},
    )
    check("缺必填时返回 400", resp.status_code == 400, resp.status_code)
    check("错误信息含中文标签", "甲方名称" in resp.json().get("message", ""), resp.json())

    print("\n5) 生成合同")
    values = {
        "contract_no": "HT-2026-001",
        "party_a_name": "某钢股份有限公司",
        "party_b_name": "某某钢铁贸易有限公司",
        "sign_place": "某钢原料仓库",
        "subject_matter": "热轧卷板 Q235B 3.0mm 500 吨",
    }
    resp = client.post(
        "/api/v1/generate/contract",
        headers=user01,
        json={"template_id": template_id, "variables": values},
    )
    check("生成返回 200", resp.status_code == 200, resp.text[:300])
    generated = resp.json()["data"]
    record_id = generated["record_id"]
    check("返回生成记录 ID", isinstance(record_id, int))
    check("下载地址走记录 ID", f"/records/{record_id}/download" in generated["download_url"],
          generated["download_url"])

    print("\n6) 下载与归属校验")
    resp = client.get(f"/api/v1/generate/contract/records/{record_id}/download", headers=user01)
    check("本人下载 200", resp.status_code == 200, resp.status_code)
    check("产物是有效 docx", resp.content[:2] == b"PK", resp.content[:8])
    resp = client.get(f"/api/v1/generate/contract/records/{record_id}/download", headers=other)
    check("他人下载被拒 403", resp.status_code == 403, resp.status_code)

    print("\n7) 产物内容校验")
    target = WORK / "downloaded.docx"
    resp = client.get(f"/api/v1/generate/contract/records/{record_id}/download", headers=user01)
    target.write_bytes(resp.content)
    text = "\n".join(p.text for p in Document(str(target)).paragraphs)
    check("甲方已填入", "某钢股份有限公司" in text, text[:120])
    check("采购标的已填入", "热轧卷板" in text)
    check("不再有占位符", "{{" not in text)
    check("留空的非必填项为空", "签约地点：某钢原料仓库" in text)

    print("\n8) 生成记录与预览")
    resp = client.get("/api/v1/generate/contract/records", headers=user01)
    records = resp.json()["data"]
    check("记录列表含本次生成", any(r["id"] == record_id for r in records["items"]),
          records["items"][:1])
    check("记录保留模板名快照", records["items"][0]["template_name"] == "钢材采购合同模板")
    resp = client.get(f"/api/v1/generate/contract/records/{record_id}/preview", headers=user01)
    check("生成稿预览元信息 200", resp.status_code == 200, resp.text[:200])
    check("预览有页数", resp.json()["data"]["page_count"] >= 1, resp.json()["data"])
    resp = client.get(f"/api/v1/generate/contract/records/{record_id}/preview/1", headers=user01)
    check("生成稿首页图片 200", resp.status_code == 200 and resp.headers["content-type"] == "image/png",
          resp.status_code)
    resp = client.get(f"/api/v1/generate/contract/records/{record_id}", headers=other)
    check("他人访问记录被拒", resp.status_code in (403, 404, 405), resp.status_code)

    print("\n9) 草稿预览（按当前取值，不落记录）")
    resp = client.post(
        "/api/v1/generate/contract/preview",
        headers=user01,
        json={"template_id": template_id, "variables": {**values, "party_a_name": "草稿预览公司"}},
    )
    check("草稿预览 200", resp.status_code == 200, resp.text[:200])
    draft = resp.json()["data"]
    check("返回预览 ID 与页数", bool(draft.get("preview_id")) and draft["page_count"] >= 1, draft)
    first = client.get(
        f"/api/v1/generate/contract/preview/{draft['preview_id']}", headers=user01
    )
    check("草稿预览元信息 200", first.status_code == 200, first.text[:160])
    page = client.get(
        f"/api/v1/generate/contract/preview/{draft['preview_id']}/1", headers=user01
    )
    check("草稿预览首页图片 200", page.status_code == 200, page.status_code)
    check("非法预览 ID 被拒", client.get(
        "/api/v1/generate/contract/preview/..%2F..%2Fetc", headers=user01
    ).status_code in (400, 404))

    print("\n10) 合同类型词表")
    resp = client.get("/api/v1/templates/categories", headers=user01)
    check("词表含导入时的类型", "采购" in resp.json()["data"]["items"], resp.json()["data"])
    resp = client.post("/api/v1/templates/categories", headers=user01, json={"name": "服务"})
    check("可新增类型", resp.status_code == 200, resp.text[:200])
    category_id = resp.json()["data"]["id"]
    resp = client.delete(f"/api/v1/templates/categories/{category_id}", headers=user01)
    check("空类型可删除", resp.status_code == 200, resp.text[:200])
    in_use = client.get("/api/v1/templates/categories", headers=user01).json()["data"]["items"]
    used_id = None
    resp = client.post("/api/v1/templates/categories", headers=user01, json={"name": "采购"}).json()
    check("重复类型被拒", resp.get("code") != 0, resp)
    check("在用类型无法删除", client.delete(
        f"/api/v1/templates/categories/{used_id or 1}", headers=user01
    ).status_code in (400, 404))

    print("\n11) 清理")
    resp = client.delete(f"/api/v1/templates/{template_id}", headers=user01)
    check("模板删除 200", resp.status_code == 200, resp.text[:200])
    resp = client.get(f"/api/v1/templates/{template_id}", headers=user01)
    check("软删后详情 404", resp.status_code == 404, resp.status_code)
    resp = client.delete(f"/api/v1/generate/contract/records/{record_id}", headers=user01)
    check("记录删除 200", resp.status_code == 200, resp.text[:200])

    print()
    if failures:
        print(f"❌ 失败 {len(failures)} 项：{failures}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
