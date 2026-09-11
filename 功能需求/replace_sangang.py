# -*- coding: utf-8 -*-
"""把 Excel(.xls) 文件中的“三钢”全部替换为“某钢”。

用法：
    python replace_sangang.py [输入文件]

默认处理“功能需求/智能问答场景与应用.xls”，原地替换前会先生成 .bak 备份。
依赖：xlrd、xlwt、xlutils（pip install xlrd xlwt xlutils）
"""

import os
import shutil
import sys

import xlrd
import xlutils.copy

OLD = "三钢"
NEW = "某钢"


def replace_in_xls(path: str) -> None:
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在：{path}")

    # 备份原文件
    backup = path + ".bak"
    shutil.copy2(path, backup)
    print(f"已备份原文件到：{backup}")

    # 打开（带格式信息，保证复制时保留样式）
    book = xlrd.open_workbook(path, formatting_info=True)

    # 复制成可写的 workbook
    writable = xlutils.copy.copy(book)

    total = 0
    for sheet_index, src_sheet in enumerate(book.sheets()):
        dst_sheet = writable.get_sheet(sheet_index)
        for row in range(src_sheet.nrows):
            for col in range(src_sheet.ncols):
                cell = src_sheet.cell(row, col)
                # 只处理文本类型单元格（ctype == 1）
                if cell.ctype == xlrd.XL_CELL_TEXT and OLD in cell.value:
                    new_value = cell.value.replace(OLD, NEW)
                    dst_sheet.write(row, col, new_value)
                    total += 1
                    print(f"替换 [{src_sheet.name}] 行{row + 1} 列{col + 1}: "
                          f"{cell.value!r} -> {new_value!r}")

    # 先写到临时文件，成功后再覆盖原文件
    tmp_path = path + ".tmp"
    writable.save(tmp_path)
    os.replace(tmp_path, path)
    print(f"完成，共替换 {total} 处，已写回：{path}")


if __name__ == "__main__":
    default = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "功能需求", "智能问答场景与应用.xls",
    )
    target = sys.argv[1] if len(sys.argv) > 1 else default
    replace_in_xls(target)
