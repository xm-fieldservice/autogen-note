"""
表结构定义管理器
"""
import os
import json
import jsonschema
from typing import Dict, Any, List, Optional

class SchemaManager:
    """表结构定义管理器"""
    
    def __init__(self, schema_dir: str):
        """初始化Schema管理器
        
        Args:
            schema_dir: 表结构定义目录
        """
        self.schema_dir = schema_dir
        os.makedirs(schema_dir, exist_ok=True)
    
    def register_schema(self, name: str, schema: Dict[str, Any]) -> bool:
        """注册新的表结构
        
        Args:
            name: 表名
            schema: 表结构定义
        
        Returns:
            是否注册成功
        """
        try:
            # 校验schema格式
            self._validate_schema_format(schema)
            
            # 添加基本元数据
            if "metadata" not in schema:
                schema["metadata"] = {}
            
            if "schema_version" not in schema["metadata"]:
                schema["metadata"]["schema_version"] = "1.0"
                
            # 保存schema
            schema_path = os.path.join(self.schema_dir, f"{name}.json")
            with open(schema_path, 'w', encoding='utf-8') as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Schema注册错误: {e}")
            return False
    
    def _validate_schema_format(self, schema: Dict[str, Any]) -> None:
        """验证schema格式是否符合JSON Schema规范
        
        Args:
            schema: 表结构定义
            
        Raises:
            ValueError: schema格式错误
        """
        required_keys = ["title", "type", "properties"]
        for key in required_keys:
            if key not in schema:
                raise ValueError(f"Schema缺少必要字段: {key}")
                
        if schema["type"] != "object":
            raise ValueError("Schema类型必须为object")
            
        if not isinstance(schema["properties"], dict) or not schema["properties"]:
            raise ValueError("Schema必须包含至少一个属性定义")
    
    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """获取表结构定义
        
        Args:
            name: 表名
            
        Returns:
            表结构定义，如果不存在则返回None
        """
        schema_path = os.path.join(self.schema_dir, f"{name}.json")
        if not os.path.exists(schema_path):
            return None
        
        with open(schema_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def validate_data(self, name: str, data: Dict[str, Any]) -> List[str]:
        """验证数据是否符合schema
        
        Args:
            name: 表名
            data: 数据记录
            
        Returns:
            验证错误信息列表，如果验证通过则为空列表
        """
        schema = self.get_schema(name)
        if not schema:
            return ["表结构不存在"]
        
        try:
            jsonschema.validate(instance=data, schema=schema)
            return []
        except jsonschema.exceptions.ValidationError as e:
            # 格式化验证错误信息
            error_path = '.'.join(str(p) for p in e.path)
            error_message = e.message
            return [f"字段 '{error_path}': {error_message}"]
            
    def list_schemas(self) -> List[Dict[str, Any]]:
        """列出所有表结构
        
        Returns:
            表结构信息列表
        """
        schemas = []
        for filename in os.listdir(self.schema_dir):
            if filename.endswith('.json'):
                name = os.path.splitext(filename)[0]
                schema = self.get_schema(name)
                if schema:
                    schemas.append({
                        "name": name,
                        "title": schema.get("title", name),
                        "description": schema.get("description", ""),
                        "type": schema.get("metadata", {}).get("table_type", "standard"),
                        "version": schema.get("metadata", {}).get("schema_version", "1.0")
                    })
        return schemas
    
    def update_schema(self, name: str, schema: Dict[str, Any]) -> bool:
        """更新表结构
        
        Args:
            name: 表名
            schema: 新的表结构定义
            
        Returns:
            是否更新成功
        """
        # 检查表是否存在
        if not self.get_schema(name):
            return False
            
        try:
            # 校验schema格式
            self._validate_schema_format(schema)
            
            # 更新版本
            if "metadata" in schema:
                if "schema_version" in schema["metadata"]:
                    # 版本号加0.1
                    try:
                        version = float(schema["metadata"]["schema_version"])
                        schema["metadata"]["schema_version"] = str(version + 0.1)
                    except:
                        schema["metadata"]["schema_version"] = "1.0"
            
            # 保存schema
            schema_path = os.path.join(self.schema_dir, f"{name}.json")
            with open(schema_path, 'w', encoding='utf-8') as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Schema更新错误: {e}")
            return False
