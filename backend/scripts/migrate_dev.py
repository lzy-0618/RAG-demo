"""开发库结构同步（无 Alembic 时的轻量迁移）。

`Base.metadata.create_all()` 只会**建表**，不会给已有表补列——新增字段在既有开发库上
不会生效。本脚本按模型定义补齐缺失的列（SQLite 支持 `ALTER TABLE ADD COLUMN`），
可重复执行，已存在的列会被跳过。

用法（在 backend/ 下执行）：
    .venv/bin/python scripts/migrate_dev.py

生产环境请迁移到 Alembic（见 AGENTS.md 第 7 节）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.models.base import Base, engine  # noqa: E402
import app.models  # noqa: F401,E402  确保所有模型都已注册到 metadata


def migrate() -> int:
    Base.metadata.create_all(bind=engine)  # 先补缺失的表
    inspector = inspect(engine)
    added = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                column_type = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))
                print(f"  + {table.name}.{column.name} {column_type}")
                added += 1
    print(f"完成：新增 {added} 列。现有表：{', '.join(sorted(inspector.get_table_names()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(migrate())
