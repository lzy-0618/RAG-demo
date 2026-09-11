"""文档解析服务：复杂法务文档按需接 unstructured/MinerU，默认走 Dify 内置解析。"""


async def parse_document(file_path: str) -> str:
    """解析文档为纯文本。

    当前为占位实现；后续复杂文档（PDF 扫描件等）在此接入 unstructured/MinerU。
    """
    raise NotImplementedError("文档解析尚未接入，默认使用 Dify 内置解析")
