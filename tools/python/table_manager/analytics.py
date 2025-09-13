"""
表数据分析工具
"""
from typing import Dict, List, Any, Optional, Union
import os
import json
import pandas as pd
from autogen_ext.tools import PythonToolProvider

class TableAnalytics(PythonToolProvider):
    """表数据分析工具"""
    
    def __init__(self, data_dir: str):
        """初始化分析工具
        
        Args:
            data_dir: 表数据存储目录
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        super().__init__()
    
    def _load_table_data(self, table_name: str) -> pd.DataFrame:
        """加载表数据到DataFrame
        
        Args:
            table_name: 表名
            
        Returns:
            包含表数据的DataFrame
        """
        data_path = os.path.join(self.data_dir, f"{table_name}.json")
        if not os.path.exists(data_path):
            return pd.DataFrame()
            
        with open(data_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return pd.DataFrame(data)
            except:
                return pd.DataFrame()
    
    def get_summary_statistics(self, table_name: str) -> Dict[str, Any]:
        """获取表数据统计摘要
        
        Args:
            table_name: 表名
            
        Returns:
            数据统计摘要
        """
        df = self._load_table_data(table_name)
        
        if df.empty:
            return {
                "error": f"表 '{table_name}' 不存在或为空"
            }
            
        # 基本统计信息
        result = {
            "table_name": table_name,
            "record_count": len(df),
            "column_count": len(df.columns),
            "columns": df.columns.tolist()
        }
        
        # 数值列统计
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        if numeric_cols:
            numeric_stats = {}
            for col in numeric_cols:
                numeric_stats[col] = {
                    "mean": float(df[col].mean()) if not df[col].isna().all() else None,
                    "median": float(df[col].median()) if not df[col].isna().all() else None,
                    "min": float(df[col].min()) if not df[col].isna().all() else None,
                    "max": float(df[col].max()) if not df[col].isna().all() else None,
                    "std": float(df[col].std()) if len(df) > 1 and not df[col].isna().all() else None,
                    "null_count": int(df[col].isna().sum())
                }
            result["numeric_stats"] = numeric_stats
        
        # 分类列统计
        categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
        if categorical_cols:
            categorical_stats = {}
            for col in categorical_cols:
                if len(df) > 0:
                    value_counts = df[col].value_counts().head(10).to_dict()
                    # 将索引转为字符串，确保JSON序列化成功
                    value_counts_str = {str(k): int(v) for k, v in value_counts.items()}
                    
                    categorical_stats[col] = {
                        "unique_values": int(df[col].nunique()),
                        "top_values": value_counts_str,
                        "null_count": int(df[col].isna().sum())
                    }
            result["categorical_stats"] = categorical_stats
            
        return result
    
    def get_group_statistics(self, table_name: str, group_by: str,
                           measure_columns: Optional[List[str]] = None,
                           aggregations: Optional[List[str]] = None) -> Dict[str, Any]:
        """获取分组统计
        
        Args:
            table_name: 表名
            group_by: 分组列名
            measure_columns: 度量列名列表
            aggregations: 聚合方法列表
            
        Returns:
            分组统计结果
        """
        df = self._load_table_data(table_name)
        
        if df.empty:
            return {
                "error": f"表 '{table_name}' 不存在或为空"
            }
            
        if group_by not in df.columns:
            return {
                "error": f"分组列 '{group_by}' 不存在"
            }
            
        # 默认使用所有数值列作为度量列
        if not measure_columns:
            measure_columns = df.select_dtypes(include=['number']).columns.tolist()
            # 如果没有数值列，则使用计数
            if not measure_columns:
                measure_columns = [df.columns[0]]
                
        # 验证度量列是否存在
        valid_measures = [col for col in measure_columns if col in df.columns]
        if not valid_measures:
            return {
                "error": f"没有有效的度量列"
            }
            
        # 默认聚合方法
        if not aggregations:
            aggregations = ['count', 'mean', 'sum']
            
        # 执行分组聚合
        try:
            agg_dict = {measure: aggregations for measure in valid_measures}
            grouped = df.groupby(group_by).agg(agg_dict)
            
            # 转换结果为可序列化的字典
            result_dict = {}
            for group_val, row in grouped.iterrows():
                group_key = str(group_val)
                result_dict[group_key] = {}
                
                for measure in valid_measures:
                    result_dict[group_key][measure] = {}
                    for agg in aggregations:
                        try:
                            val = row[(measure, agg)]
                            # 确保值是可JSON序列化的
                            if pd.isna(val):
                                result_dict[group_key][measure][agg] = None
                            else:
                                result_dict[group_key][measure][agg] = float(val) if isinstance(val, (int, float)) else str(val)
                        except:
                            result_dict[group_key][measure][agg] = None
            
            return {
                "table_name": table_name,
                "group_by": group_by,
                "measures": valid_measures,
                "aggregations": aggregations,
                "results": result_dict
            }
        except Exception as e:
            return {
                "error": f"分组统计错误: {str(e)}"
            }
    
    def get_correlation_matrix(self, table_name: str, 
                             columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """获取相关性矩阵
        
        Args:
            table_name: 表名
            columns: 要计算相关性的列名列表
            
        Returns:
            相关性矩阵结果
        """
        df = self._load_table_data(table_name)
        
        if df.empty:
            return {
                "error": f"表 '{table_name}' 不存在或为空"
            }
            
        # 默认使用所有数值列
        if not columns:
            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        else:
            numeric_cols = [col for col in columns if col in df.columns and pd.api.types.is_numeric_dtype(df[col])]
            
        if not numeric_cols:
            return {
                "error": f"没有有效的数值列用于计算相关性"
            }
            
        try:
            # 计算相关性矩阵
            corr_matrix = df[numeric_cols].corr().fillna(0).round(3)
            
            # 转换为可序列化的字典
            result_dict = {}
            for col1 in corr_matrix.columns:
                result_dict[col1] = {}
                for col2 in corr_matrix.columns:
                    result_dict[col1][col2] = float(corr_matrix.loc[col1, col2])
            
            return {
                "table_name": table_name,
                "columns": numeric_cols,
                "correlation_matrix": result_dict
            }
        except Exception as e:
            return {
                "error": f"计算相关性错误: {str(e)}"
            }
    
    def get_time_series_analysis(self, table_name: str, 
                               date_column: str,
                               value_column: str,
                               frequency: str = 'M') -> Dict[str, Any]:
        """获取时间序列分析
        
        Args:
            table_name: 表名
            date_column: 日期列名
            value_column: 值列名
            frequency: 重采样频率，默认为月(M)
            
        Returns:
            时间序列分析结果
        """
        df = self._load_table_data(table_name)
        
        if df.empty:
            return {
                "error": f"表 '{table_name}' 不存在或为空"
            }
            
        if date_column not in df.columns:
            return {
                "error": f"日期列 '{date_column}' 不存在"
            }
            
        if value_column not in df.columns:
            return {
                "error": f"值列 '{value_column}' 不存在"
            }
            
        try:
            # 转换日期列
            df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
            df = df.dropna(subset=[date_column])
            
            # 确保值列是数值型
            if not pd.api.types.is_numeric_dtype(df[value_column]):
                try:
                    df[value_column] = pd.to_numeric(df[value_column], errors='coerce')
                except:
                    return {
                        "error": f"值列 '{value_column}' 不能转换为数值类型"
                    }
            
            # 设置日期索引
            df_ts = df.set_index(date_column)
            
            # 按指定频率重采样并计算统计值
            resampled = df_ts[value_column].resample(frequency)
            result_dict = {
                "mean": resampled.mean().to_dict(),
                "sum": resampled.sum().to_dict(),
                "count": resampled.count().to_dict(),
                "min": resampled.min().to_dict(),
                "max": resampled.max().to_dict()
            }
            
            # 确保键是字符串
            for stat, data in result_dict.items():
                result_dict[stat] = {str(k): float(v) if not pd.isna(v) else None for k, v in data.items()}
            
            return {
                "table_name": table_name,
                "date_column": date_column,
                "value_column": value_column,
                "frequency": frequency,
                "time_series_data": result_dict
            }
        except Exception as e:
            return {
                "error": f"时间序列分析错误: {str(e)}"
            }
