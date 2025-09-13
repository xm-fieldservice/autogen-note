"""
兼容桥接模块：保持原导入路径不变
from services.vectorstores_service import VectorStoresService
=> 现桥接至 modules.vectorstores.service.VectorStoresService
"""

# -*- coding: utf-8 -*-
from __future__ import annotations

# 直接从模块化实现处导入并导出同名类
from modules.vectorstores.service import VectorStoresService  # noqa: F401

# 备注：如需逐步迁移，可在此放置弃用提醒日志，但为减少噪声暂不输出。
