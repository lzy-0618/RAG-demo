"""全局常量定义。"""

# 统一响应业务码
CODE_OK = 0
CODE_BIZ_ERROR = 1

# 知识库文档状态
DOC_STATUS_UPLOADED = "uploaded"
DOC_STATUS_PARSING = "parsing"
DOC_STATUS_READY = "ready"
DOC_STATUS_FAILED = "failed"

# 审查任务状态（需求 ②③）
REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_RUNNING = "running"
REVIEW_STATUS_COMPLETED = "completed"
REVIEW_STATUS_FAILED = "failed"

# 审查类型：合同审查 / 规章制度审查
REVIEW_TYPE_CONTRACT = "contract"
REVIEW_TYPE_REGULATION = "regulation"

# 风险等级排序（合并结果时按此排序）
RISK_LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}

# 角色（RBAC）：普通用户可正常使用各功能；专家额外拥有「内容纠错/标注」权限
ROLE_USER = "user"
ROLE_EXPERT = "expert"
