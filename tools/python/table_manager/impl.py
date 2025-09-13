"""
结构化数据表管理工具
"""
from typing import Dict, List, Any, Optional, Union
import os
import json
import pandas as pd
import uuid
from datetime import datetime
import jsonschema
from autogen_ext.tools import PythonToolProvider
from .schema_manager import SchemaManager
from .vector_connector import TableVectorConnector

class TableToolProvider(PythonToolProvider):
    """结构化数据表管理工具提供者"""
    
    def __init__(self, schema_dir: str, data_dir: str):
        """初始化表格管理工具
        
        Args:
            schema_dir: 表结构定义目录
            data_dir: 表数据存储目录
        """
        self.schema_dir = schema_dir
        self.data_dir = data_dir
        os.makedirs(schema_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        self.schema_manager = SchemaManager(schema_dir)
        super().__init__()
    
    def list_tables(self) -> List[Dict[str, Any]]:
        """列出所有可用的数据表"""
        tables = []
        for filename in os.listdir(self.schema_dir):
            if filename.endswith('.json'):
                table_name = os.path.splitext(filename)[0]
                schema_path = os.path.join(self.schema_dir, filename)
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema = json.load(f)
                
                # 获取表数据记录数
                data_path = os.path.join(self.data_dir, f"{table_name}.json")
                record_count = 0
                if os.path.exists(data_path):
                    with open(data_path, 'r', encoding='utf-8') as f:
                        try:
                            data = json.load(f)
                            record_count = len(data)
                        except:
                            record_count = 0
                
                tables.append({
                    "name": table_name,
                    "title": schema.get("title", table_name),
                    "description": schema.get("description", ""),
                    "type": schema.get("metadata", {}).get("table_type", "standard"),
                    "version": schema.get("metadata", {}).get("schema_version", "1.0"),
                    "record_count": record_count
                })
        return tables
    
    def get_schema(self, table_name: str) -> Dict[str, Any]:
        """获取表结构定义
        
        Args:
            table_name: 表名
            
        Returns:
            表结构定义字典
        """
        return self.schema_manager.get_schema(table_name)
    
    def query_table(self, table_name: str, 
                   conditions: Optional[Dict[str, Any]] = None,
                   limit: int = 100,
                   offset: int = 0,
                   sort_by: Optional[str] = None,
                   sort_order: str = "asc") -> Dict[str, Any]:
        """查询表数据
        
        Args:
            table_name: 表名
            conditions: 查询条件，键为字段名，值为查询值
            limit: 返回记录数限制
            offset: 查询偏移量
            sort_by: 排序字段
            sort_order: 排序方向，asc或desc
            
        Returns:
            查询结果，包含总记录数、当前页记录等
        """
        # 检查表是否存在
        schema = self.schema_manager.get_schema(table_name)
        if not schema:
            return {"error": f"表 '{table_name}' 不存在"}
            
        # 读取表数据
        data_path = os.path.join(self.data_dir, f"{table_name}.json")
        if not os.path.exists(data_path):
            return {
                "total": 0,
                "records": [],
                "schema": schema
            }
        
        with open(data_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                return {"error": f"读取表 '{table_name}' 数据失败"}
        
        # 应用过滤条件
        if conditions:
            filtered_data = []
            for record in data:
                match = True
                for field, value in conditions.items():
                    if field not in record or record[field] != value:
                        match = False
                        break
                if match:
                    filtered_data.append(record)
        else:
            filtered_data = data
            
        # 应用排序
        if sort_by and sort_by in schema.get("properties", {}):
            reverse = sort_order.lower() == "desc"
            filtered_data.sort(key=lambda x: x.get(sort_by, ""), reverse=reverse)
            
        # 应用分页
        total = len(filtered_data)
        paged_data = filtered_data[offset:offset+limit]
        
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "records": paged_data,
            "schema": schema
        }
    
    def get_record(self, table_name: str, record_id_field: str, record_id: str) -> Dict[str, Any]:
        """获取单条记录
        
        Args:
            table_name: 表名
            record_id_field: 记录ID字段名
            record_id: 记录ID值
            
        Returns:
            记录数据
        """
        result = self.query_table(
            table_name=table_name,
            conditions={record_id_field: record_id},
            limit=1
        )
        
        if "error" in result:
            return result
            
        if not result["records"]:
            return {"error": f"记录 {record_id} 不存在"}
            
        return {"record": result["records"][0], "schema": result["schema"]}
    
    def update_table(self, table_name: str, record_id_field: str, record_id: str,
                    data: Dict[str, Any], conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """更新表记录
        
        Args:
            table_name: 表名
            record_id_field: 记录ID字段名
            record_id: 记录ID值
            data: 更新数据
            conversation_id: 会话ID，用于审计
            
        Returns:
            更新结果
        """
        # 检查表是否存在
        schema = self.schema_manager.get_schema(table_name)
        if not schema:
            return {"error": f"表 '{table_name}' 不存在"}
            
        # 验证字段是否符合schema
        validation_errors = self.schema_manager.validate_data(table_name, data)
        if validation_errors:
            return {"error": f"数据验证失败", "validation_errors": validation_errors}
        
        # 读取表数据
        data_path = os.path.join(self.data_dir, f"{table_name}.json")
        if not os.path.exists(data_path):
            return {"error": f"表 '{table_name}' 不存在记录"}
        
        with open(data_path, 'r', encoding='utf-8') as f:
            try:
                all_data = json.load(f)
            except:
                return {"error": f"读取表 '{table_name}' 数据失败"}
        
        # 查找并更新记录
        record_found = False
        for i, record in enumerate(all_data):
            if record.get(record_id_field) == record_id:
                # 保存原始记录用于审计
                original_record = record.copy()
                
                # 更新记录
                for field, value in data.items():
                    record[field] = value
                    
                # 添加更新时间
                record['updated_at'] = datetime.now().isoformat()
                if conversation_id:
                    record['updated_by'] = conversation_id
                    
                all_data[i] = record
                record_found = True
                break
        
        if not record_found:
            return {"error": f"记录 {record_id} 不存在"}
            
        # 保存更新后的数据
        try:
            with open(data_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"error": f"保存数据失败: {str(e)}"}
            
        return {
            "success": True,
            "message": f"记录 {record_id} 已更新",
            "record": record
        }
    
    def add_record(self, table_name: str, data: Dict[str, Any],
                  conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """添加新记录
        
        Args:
            table_name: 表名
            data: 记录数据
            conversation_id: 会话ID，用于审计
            
        Returns:
            添加结果
        """
        # 检查表是否存在
        schema = self.schema_manager.get_schema(table_name)
        if not schema:
            return {"error": f"表 '{table_name}' 不存在"}
            
        # 验证字段是否符合schema
        validation_errors = self.schema_manager.validate_data(table_name, data)
        if validation_errors:
            return {"error": f"数据验证失败", "validation_errors": validation_errors}
        
        # 添加创建时间
        data['created_at'] = datetime.now().isoformat()
        if conversation_id:
            data['created_by'] = conversation_id
        
        # 读取现有数据或创建新数组
        data_path = os.path.join(self.data_dir, f"{table_name}.json")
        if os.path.exists(data_path):
            with open(data_path, 'r', encoding='utf-8') as f:
                try:
                    all_data = json.load(f)
                except:
                    all_data = []
        else:
            all_data = []
        
        # 添加新记录
        all_data.append(data)
        
        # 保存数据
        try:
            with open(data_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"error": f"保存数据失败: {str(e)}"}
            
        return {
            "success": True,
            "message": f"已添加新记录",
            "record": data
        }
    
    def delete_record(self, table_name: str, record_id_field: str, record_id: str,
                     conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """删除记录
        
        Args:
            table_name: 表名
            record_id_field: 记录ID字段名
            record_id: 记录ID值
            conversation_id: 会话ID，用于审计
            
        Returns:
            删除结果
        """
        # 检查表是否存在
        schema = self.schema_manager.get_schema(table_name)
        if not schema:
            return {"error": f"表 '{table_name}' 不存在"}
            
        # 读取表数据
        data_path = os.path.join(self.data_dir, f"{table_name}.json")
        if not os.path.exists(data_path):
            return {"error": f"表 '{table_name}' 不存在记录"}
        
        with open(data_path, 'r', encoding='utf-8') as f:
            try:
                all_data = json.load(f)
            except:
                return {"error": f"读取表 '{table_name}' 数据失败"}
        
        # 查找并删除记录
        record_found = False
        deleted_record = None
        new_data = []
        
        for record in all_data:
            if record.get(record_id_field) == record_id:
                deleted_record = record
                record_found = True
            else:
                new_data.append(record)
        
        if not record_found:
            return {"error": f"记录 {record_id} 不存在"}
            
        # 保存更新后的数据
        try:
            with open(data_path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"error": f"保存数据失败: {str(e)}"}
            
        # 记录删除操作到审计日志
        if conversation_id:
            # 此处可添加审计日志记录
            pass
            
        return {
            "success": True,
            "message": f"记录 {record_id} 已删除",
            "deleted_record": deleted_record
        }
    
    def create_table(self, table_name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """创建新表
        
        Args:
            table_name: 表名
            schema: 表结构定义
            
        Returns:
            创建结果
        """
        # 检查表是否已存在
        if self.schema_manager.get_schema(table_name):
            return {"error": f"表 '{table_name}' 已存在"}
            
        # 注册表结构
        success = self.schema_manager.register_schema(table_name, schema)
        if not success:
            return {"error": f"创建表 '{table_name}' 失败"}
            
        return {
            "success": True,
            "message": f"表 '{table_name}' 已创建",
            "schema": schema
        }
