"""
表数据向量存储连接器
"""
import os
import json
import hashlib
from typing import Dict, List, Any, Optional
import chromadb
from chromadb.utils import embedding_functions

class TableVectorConnector:
    """表数据向量存储连接器"""
    
    def __init__(self, chroma_db_path: str, collection_prefix: str = "table_"):
        """初始化向量存储连接器
        
        Args:
            chroma_db_path: ChromaDB存储路径
            collection_prefix: 集合名称前缀
        """
        self.chroma_db_path = chroma_db_path
        self.collection_prefix = collection_prefix
        
        # 初始化ChromaDB客户端
        self.client = chromadb.PersistentClient(path=chroma_db_path)
        
        # 使用默认的OpenAI嵌入函数
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
    
    def _get_collection_name(self, table_name: str) -> str:
        """获取表对应的向量集合名称
        
        Args:
            table_name: 表名
            
        Returns:
            向量集合名称
        """
        return f"{self.collection_prefix}{table_name}"
    
    def _generate_vector_id(self, table_name: str, record_id: str) -> str:
        """生成向量ID
        
        Args:
            table_name: 表名
            record_id: 记录ID
            
        Returns:
            向量ID
        """
        # 使用表名和记录ID生成唯一ID
        combined = f"{table_name}_{record_id}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def _prepare_document_text(self, record: Dict[str, Any], 
                             schema: Dict[str, Any]) -> str:
        """准备文档文本用于向量索引
        
        Args:
            record: 记录数据
            schema: 表结构定义
            
        Returns:
            格式化的文档文本
        """
        text_parts = []
        
        # 添加表名和描述
        if "title" in schema:
            text_parts.append(f"表: {schema['title']}")
        if "description" in schema:
            text_parts.append(f"描述: {schema['description']}")
        
        # 添加字段值
        for field, value in record.items():
            # 获取字段标题
            field_title = schema.get("properties", {}).get(field, {}).get("title", field)
            
            # 对于复杂类型的处理
            if isinstance(value, dict):
                value_text = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, list):
                value_text = ", ".join(str(v) for v in value)
            else:
                value_text = str(value)
                
            text_parts.append(f"{field_title}: {value_text}")
        
        return "\n".join(text_parts)
    
    def index_record(self, table_name: str, record: Dict[str, Any], 
                    record_id: str, schema: Dict[str, Any]) -> bool:
        """索引记录到向量库
        
        Args:
            table_name: 表名
            record: 记录数据
            record_id: 记录ID
            schema: 表结构定义
            
        Returns:
            索引是否成功
        """
        try:
            collection_name = self._get_collection_name(table_name)
            
            # 获取或创建集合
            try:
                collection = self.client.get_collection(
                    name=collection_name,
                    embedding_function=self.embedding_function
                )
            except:
                collection = self.client.create_collection(
                    name=collection_name,
                    embedding_function=self.embedding_function
                )
            
            # 准备文档
            vector_id = self._generate_vector_id(table_name, record_id)
            document_text = self._prepare_document_text(record, schema)
            
            # 准备元数据
            metadata = {
                "table_name": table_name,
                "record_id": record_id
            }
            
            # 将记录添加到集合
            collection.upsert(
                ids=[vector_id],
                documents=[document_text],
                metadatas=[metadata]
            )
            
            return True
        except Exception as e:
            print(f"索引记录错误: {e}")
            return False
    
    def delete_record_vector(self, table_name: str, record_id: str) -> bool:
        """从向量库删除记录
        
        Args:
            table_name: 表名
            record_id: 记录ID
            
        Returns:
            删除是否成功
        """
        try:
            collection_name = self._get_collection_name(table_name)
            
            # 获取集合
            try:
                collection = self.client.get_collection(
                    name=collection_name,
                    embedding_function=self.embedding_function
                )
            except:
                return True  # 集合不存在视为删除成功
            
            # 生成向量ID
            vector_id = self._generate_vector_id(table_name, record_id)
            
            # 删除记录
            collection.delete(ids=[vector_id])
            
            return True
        except Exception as e:
            print(f"删除向量记录错误: {e}")
            return False
    
    def search(self, table_names: List[str], query: str, 
              limit: int = 10) -> List[Dict[str, Any]]:
        """搜索表数据
        
        Args:
            table_names: 要搜索的表名列表
            query: 搜索查询
            limit: 返回结果限制
            
        Returns:
            搜索结果列表
        """
        results = []
        
        for table_name in table_names:
            collection_name = self._get_collection_name(table_name)
            
            # 获取集合
            try:
                collection = self.client.get_collection(
                    name=collection_name,
                    embedding_function=self.embedding_function
                )
                
                # 执行搜索
                search_results = collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                
                # 处理结果
                if search_results and search_results.get("ids"):
                    for i, result_id in enumerate(search_results["ids"][0]):
                        distance = search_results["distances"][0][i] if "distances" in search_results else None
                        document = search_results["documents"][0][i] if "documents" in search_results else ""
                        metadata = search_results["metadatas"][0][i] if "metadatas" in search_results else {}
                        
                        results.append({
                            "table_name": metadata.get("table_name", table_name),
                            "record_id": metadata.get("record_id", ""),
                            "document": document,
                            "distance": distance,
                            "id": result_id
                        })
            except Exception as e:
                print(f"搜索表 {table_name} 错误: {e}")
        
        # 按相关性排序
        if results:
            results.sort(key=lambda x: x.get("distance", float('inf')))
            
        return results[:limit]
