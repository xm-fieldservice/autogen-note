# -*- coding: utf-8 -*-
"""
智能查询策略管理器
根据查询内容和上下文自动选择最适合的抓取策略
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from enum import Enum


class QueryLevel(Enum):
    """查询级别枚举"""
    BASIC = "basic"          # 基础查询：静态内容足够
    ADVANCED = "advanced"    # 高级查询：需要动态渲染
    FORCE_BASIC = "force_basic"      # 强制基础模式
    FORCE_ADVANCED = "force_advanced" # 强制高级模式


@dataclass
class QueryAnalysis:
    """查询分析结果"""
    level: QueryLevel
    confidence: float  # 0-1，判断置信度
    reasons: List[str]  # 判断理由
    browser_needed: bool  # 是否需要启动浏览器
    estimated_complexity: int  # 1-5，预估复杂度


class QueryStrategyManager:
    """查询策略管理器"""
    
    def __init__(self):
        # 需要高级查询的关键词
        self.advanced_keywords = {
            # 技术相关
            "实时", "最新", "动态", "交互", "在线工具", "计算器", "转换器",
            # 社交媒体和现代网站
            "微博", "知乎", "github", "stackoverflow", "reddit", "twitter",
            # 电商和动态内容
            "价格", "库存", "评价", "商品", "购买", "下单",
            # 需要JS的内容
            "图表", "可视化", "dashboard", "控制台", "管理后台",
            # 时效性内容
            "今天", "昨天", "本周", "最近", "刚刚", "现在"
        }
        
        # 基础查询足够的关键词
        self.basic_keywords = {
            "定义", "概念", "历史", "介绍", "原理", "基础", "入门",
            "文档", "教程", "指南", "手册", "说明", "规范",
            "新闻", "报道", "文章", "博客", "论文", "研究"
        }
        
        # 明确需要浏览器的网站模式
        self.browser_required_patterns = [
            r".*github\.com.*",
            r".*stackoverflow\.com.*", 
            r".*zhihu\.com.*",
            r".*weibo\.com.*",
            r".*twitter\.com.*",
            r".*reddit\.com.*",
            r".*app\..*",  # 大多数app子域名
            r".*admin\..*",  # 管理后台
            r".*dashboard\..*"  # 仪表板
        ]
    
    def analyze_query(self, query: str, context: Dict[str, Any] = None) -> QueryAnalysis:
        """
        分析查询内容，决定使用哪种策略
        
        Args:
            query: 用户查询内容
            context: 上下文信息（可选）
        
        Returns:
            QueryAnalysis: 分析结果
        """
        query_lower = query.lower()
        reasons = []
        confidence = 0.5
        
        # 检查强制模式标记
        if "[[force_basic]]" in query_lower:
            return QueryAnalysis(
                level=QueryLevel.FORCE_BASIC,
                confidence=1.0,
                reasons=["用户强制指定基础模式"],
                browser_needed=False,
                estimated_complexity=1
            )
        
        if "[[force_advanced]]" in query_lower:
            return QueryAnalysis(
                level=QueryLevel.FORCE_ADVANCED,
                confidence=1.0,
                reasons=["用户强制指定高级模式"],
                browser_needed=True,
                estimated_complexity=5
            )
        
        # 分析查询内容特征
        advanced_score = 0
        basic_score = 0
        
        # 1. 关键词匹配
        for keyword in self.advanced_keywords:
            if keyword in query_lower:
                advanced_score += 1
                reasons.append(f"包含高级查询关键词: {keyword}")
        
        for keyword in self.basic_keywords:
            if keyword in query_lower:
                basic_score += 1
                reasons.append(f"包含基础查询关键词: {keyword}")
        
        # 2. 时效性检测
        time_patterns = [
            r"最新|latest|newest|recent",
            r"今天|today|现在|now|当前|current",
            r"实时|real.?time|live",
            r"\d+年\d+月|\d{4}-\d{2}|202[0-9]"
        ]
        
        for pattern in time_patterns:
            if re.search(pattern, query_lower):
                advanced_score += 2
                reasons.append(f"检测到时效性需求: {pattern}")
        
        # 3. 技术复杂度检测
        tech_patterns = [
            r"api|接口|调用",
            r"代码|code|编程|programming",
            r"配置|config|设置|setting",
            r"工具|tool|软件|software"
        ]
        
        for pattern in tech_patterns:
            if re.search(pattern, query_lower):
                advanced_score += 1
                reasons.append(f"检测到技术内容: {pattern}")
        
        # 4. 交互性检测
        interactive_patterns = [
            r"如何使用|怎么用|操作步骤",
            r"登录|注册|下载|安装",
            r"在线|online|web版"
        ]
        
        for pattern in interactive_patterns:
            if re.search(pattern, query_lower):
                advanced_score += 1.5
                reasons.append(f"检测到交互需求: {pattern}")
        
        # 5. 上下文分析
        if context:
            # 如果之前的查询失败了，提升级别
            if context.get("previous_failed", False):
                advanced_score += 2
                reasons.append("前次查询失败，提升查询级别")
            
            # 如果用户明确要求详细信息
            if context.get("detailed_request", False):
                advanced_score += 1
                reasons.append("用户要求详细信息")
        
        # 计算最终得分和置信度
        total_score = advanced_score - basic_score
        confidence = min(0.9, 0.5 + abs(total_score) * 0.1)
        
        # 决定查询级别
        if total_score >= 2:
            level = QueryLevel.ADVANCED
            browser_needed = True
            complexity = min(5, 2 + advanced_score)
        elif total_score <= -1:
            level = QueryLevel.BASIC
            browser_needed = False
            complexity = max(1, 3 - basic_score)
        else:
            # 边界情况，倾向于基础查询（性能优先）
            level = QueryLevel.BASIC
            browser_needed = False
            complexity = 2
            reasons.append("得分接近，选择性能优先的基础模式")
        
        return QueryAnalysis(
            level=level,
            confidence=confidence,
            reasons=reasons,
            browser_needed=browser_needed,
            estimated_complexity=complexity
        )
    
    def should_use_browser_for_url(self, url: str) -> bool:
        """
        判断特定URL是否需要浏览器渲染
        
        Args:
            url: 目标URL
            
        Returns:
            bool: 是否需要浏览器
        """
        for pattern in self.browser_required_patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True
        return False
    
    def get_strategy_config(self, analysis: QueryAnalysis) -> Dict[str, Any]:
        """
        根据分析结果生成策略配置
        
        Args:
            analysis: 查询分析结果
            
        Returns:
            Dict: 策略配置参数
        """
        if analysis.level in [QueryLevel.ADVANCED, QueryLevel.FORCE_ADVANCED]:
            return {
                "max_content_sources": 5,
                "force_playwright": analysis.level == QueryLevel.FORCE_ADVANCED,
                "timeout": 60,
                "enable_screenshots": True,
                "wait_for_dynamic": True
            }
        else:
            return {
                "max_content_sources": 3,
                "force_playwright": False,
                "timeout": 30,
                "enable_screenshots": False,
                "wait_for_dynamic": False
            }


# 全局实例
query_strategy = QueryStrategyManager()
