from __future__ import annotations
from typing import Any, Dict, List
from repositories.capabilities_repo import CapabilityRepository

class CapabilityService:
    def __init__(self, repo: CapabilityRepository | None = None):
        self.repo = repo or CapabilityRepository()

    def soft_validate(self, agent_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        warnings: List[Dict[str, Any]] = []
        model = (((agent_cfg.get("model_client") or {}).get("config") or {}).get("model"))
        if not model:
            return warnings
        caps_reg = self.repo.get_registry()
        # 最小实现：若模型不在 registry，提示补充能力信息
        if isinstance(caps_reg, dict) and model not in caps_reg:
            warnings.append({"scope": "capability", "level": "info", "message": f"模型 {model} 不在 capability_registry 中，建议补充"})
        return warnings
