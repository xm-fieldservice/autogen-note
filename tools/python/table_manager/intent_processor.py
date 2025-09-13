"""
结构化数据表意图处理工具
"""
from typing import Dict, List, Any, Optional, Union
import re
import json
from autogen_ext.tools import PythonToolProvider

class IntentProcessorTool(PythonToolProvider):
    """结构化数据表意图处理工具"""
    
    def __init__(self):
        """初始化意图处理工具"""
        super().__init__()
        
        # 意图模式匹配
        self.intent_patterns = {
            "查询": r"(?:查询|搜索|查找|获取|列出|显示).*?(?:表格|表|数据)?",
            "添加": r"(?:添加|新增|创建|插入).*?(?:记录|数据|行|条目)?",
            "更新": r"(?:更新|修改|编辑|变更).*?(?:记录|数据|行|条目)?",
            "删除": r"(?:删除|移除|撤销).*?(?:记录|数据|行|条目)?",
            "分析": r"(?:分析|统计|计算|汇总).*?(?:数据|表格|表)?",
            "创建表": r"(?:创建|新建|生成).*?(?:表格|表|数据表)",
            "列表": r"(?:列出|列举|显示).*?(?:所有|全部)?.*?(?:表格|表)"
        }
    
    def extract_intent(self, query: str) -> Dict[str, Any]:
        """从用户查询中提取意图
        
        Args:
            query: 用户查询文本
            
        Returns:
            提取的意图信息
        """
        query = query.strip()
        
        # 默认意图为查询
        intent_type = "查询"
        confidence = 0.5
        
        # 匹配意图模式
        for intent, pattern in self.intent_patterns.items():
            if re.search(pattern, query):
                intent_type = intent
                confidence = 0.8
                break
        
        # 提取表名
        table_name = self._extract_table_name(query)
        
        # 提取条件
        conditions = self._extract_conditions(query)
        
        return {
            "intent_type": intent_type,
            "table_name": table_name,
            "conditions": conditions,
            "raw_query": query,
            "confidence": confidence
        }
    
    def _extract_table_name(self, query: str) -> Optional[str]:
        """从查询中提取表名
        
        Args:
            query: 用户查询文本
            
        Returns:
            提取的表名，如果未找到则为None
        """
        # 表名模式匹配
        table_patterns = [
            r"(?:表格|表|数据表)[：:]*\s*([^\s,，.。]+)",
            r"([^\s,，.。]+?)(?:表格|表)",
            r"在\s*([^\s,，.。]+)\s*中"
        ]
        
        for pattern in table_patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_conditions(self, query: str) -> Dict[str, Any]:
        """从查询中提取条件
        
        Args:
            query: 用户查询文本
            
        Returns:
            提取的条件字典
        """
        conditions = {}
        
        # 提取键值对条件，如"字段=值"
        kv_pattern = r"([^\s=:：]+)\s*[=:：]\s*([^\s,，;；]+)"
        for match in re.finditer(kv_pattern, query):
            field = match.group(1)
            value = match.group(2)
            
            # 处理引号包裹的值
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
                
            conditions[field] = value
        
        # 提取ID条件
        id_pattern = r"ID\s*[为是:：=]\s*([^\s,，;；]+)"
        id_match = re.search(id_pattern, query)
        if id_match:
            conditions["id"] = id_match.group(1)
        
        return conditions
    
    def analyze_structured_command(self, command: str) -> Dict[str, Any]:
        """分析结构化命令
        
        Args:
            command: 结构化命令字符串，通常是JSON格式
            
        Returns:
            解析后的命令结构
        """
        try:
            # 尝试解析为JSON
            cmd = json.loads(command)
            
            # 验证必要字段
            if "action" not in cmd:
                return {"error": "命令缺少action字段"}
                
            # 标准化字段
            if "table" in cmd and "table_name" not in cmd:
                cmd["table_name"] = cmd["table"]
                
            return {
                "success": True,
                "parsed_command": cmd,
                "format": "json"
            }
        except json.JSONDecodeError:
            # 非JSON格式，使用常规意图提取
            intent = self.extract_intent(command)
            return {
                "success": True,
                "parsed_command": {
                    "action": intent["intent_type"],
                    "table_name": intent["table_name"],
                    "conditions": intent["conditions"]
                },
                "format": "natural_language",
                "confidence": intent["confidence"]
            }
    
    def generate_structured_command(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """根据意图生成结构化命令
        
        Args:
            intent: 意图信息
            
        Returns:
            生成的结构化命令
        """
        command = {
            "action": intent["intent_type"]
        }
        
        if intent["table_name"]:
            command["table_name"] = intent["table_name"]
            
        if intent["conditions"]:
            command["conditions"] = intent["conditions"]
            
        # 根据不同意图类型添加特定字段
        if intent["intent_type"] == "查询":
            command["limit"] = 10
            command["offset"] = 0
            
        elif intent["intent_type"] in ["添加", "更新"]:
            command["data"] = {}  # 待填充的数据
            
        return {
            "structured_command": command,
            "sql_equivalent": self._generate_sql_equivalent(intent),
            "confidence": intent["confidence"]
        }
    
    def _generate_sql_equivalent(self, intent: Dict[str, Any]) -> str:
        """生成等效的SQL语句
        
        Args:
            intent: 意图信息
            
        Returns:
            SQL语句
        """
        if not intent["table_name"]:
            return ""
            
        table_name = intent["table_name"]
        
        if intent["intent_type"] == "查询":
            # 构建WHERE子句
            where_clause = ""
            if intent["conditions"]:
                conditions = []
                for field, value in intent["conditions"].items():
                    conditions.append(f"{field} = '{value}'")
                if conditions:
                    where_clause = " WHERE " + " AND ".join(conditions)
            
            return f"SELECT * FROM {table_name}{where_clause} LIMIT 10"
            
        elif intent["intent_type"] == "添加":
            return f"INSERT INTO {table_name} (...) VALUES (...)"
            
        elif intent["intent_type"] == "更新":
            where_clause = ""
            if intent["conditions"]:
                conditions = []
                for field, value in intent["conditions"].items():
                    conditions.append(f"{field} = '{value}'")
                if conditions:
                    where_clause = " WHERE " + " AND ".join(conditions)
            
            return f"UPDATE {table_name} SET ... {where_clause}"
            
        elif intent["intent_type"] == "删除":
            where_clause = ""
            if intent["conditions"]:
                conditions = []
                for field, value in intent["conditions"].items():
                    conditions.append(f"{field} = '{value}'")
                if conditions:
                    where_clause = " WHERE " + " AND ".join(conditions)
            
            return f"DELETE FROM {table_name} {where_clause}"
            
        elif intent["intent_type"] == "列表":
            return "SHOW TABLES"
            
        elif intent["intent_type"] == "创建表":
            return f"CREATE TABLE {table_name} (...)"
            
        else:
            return ""
