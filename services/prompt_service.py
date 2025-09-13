from __future__ import annotations
from typing import Any, Dict, List
from repositories.prompts_repo import PromptsRepository

class PromptService:
    """
    提示词渲染与插槽校验（阶段一：最小实现）。
    - render: 返回渲染后的多段 SystemMessage 的占位结构（不依赖 autogen_core）。
    - validate_slots: 仅检查必填与默认值占位（类型校验留待后续）。
    """

    def __init__(self, repo: PromptsRepository | None = None):
        self.repo = repo or PromptsRepository()

    def render(self, template_ref: str, locale: str | None, slots: Dict[str, Any]) -> Dict[str, Any]:
        tpl = self.repo.get_template(template_ref, locale)
        if not tpl:
            return {"messages": [], "template_ref": template_ref, "locale": locale, "slots": slots, "version": None}
        contents: List[Dict[str, str]] = []
        for seg in tpl.get("content", []):
            text = seg.get("text", "")
            # 简单占位替换
            for k, v in (slots or {}).items():
                text = text.replace(f"{{{{{k}}}}}", str(v))
            contents.append({"role": seg.get("role", "system"), "text": text})
        return {"messages": contents, "template_ref": template_ref, "locale": tpl.get("locale"), "slots": slots, "version": tpl.get("version")}

    def validate_slots(self, template_ref: str, locale: str | None, slots: Dict[str, Any]) -> List[Dict[str, Any]]:
        warnings: List[Dict[str, Any]] = []
        tpl = self.repo.get_template(template_ref, locale)
        if not tpl:
            warnings.append({"scope": "prompt", "level": "warn", "message": "模板未找到"})
            return warnings
        spec = (tpl.get("slots") or {})
        for name, rule in spec.items():
            required = bool(rule.get("required"))
            if required and (slots is None or name not in slots or slots.get(name) in (None, "")):
                warnings.append({"scope": "prompt", "level": "warn", "message": f"必填插槽缺失: {name}"})
        return warnings
