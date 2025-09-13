# -*- coding: utf-8 -*-
"""
配置常量管理模块
统一管理应用程序中的路径、消息和配置项
"""
import os
from pathlib import Path

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

class Paths:
    """路径配置"""
    # 配置目录
    CONFIG_DIR = "config"
    AGENTS_DIR = "config/agents"
    MODELS_DIR = "config/models"
    PROMPTS_DIR = "config/prompts"
    MCP_DIR = "config/mcp"
    
    # 数据目录
    DATA_DIR = "data"
    CHROMA_DIR = "data/chroma"
    QA_HISTORY_DIR = "data/qa_history"
    AUTOGEN_MEMORY_DIR = "data/autogen_official_memory"
    
    # 日志目录
    LOGS_DIR = "logs"
    AGENT_LOGS_DIR = "logs/agent"
    
    # 输出目录
    OUT_DIR = "out"
    
    # 工具目录
    TOOLS_DIR = "tools"
    PYTHON_TOOLS_DIR = "tools/python"
    
    # UI页面目录
    UI_PAGES_DIR = "ui/pages"
    
    # 脚本目录
    SCRIPTS_DIR = "scripts"
    
    # 临时目录
    TEMP_DIR = "temp"
    
    @classmethod
    def get_absolute_path(cls, relative_path: str) -> Path:
        """获取绝对路径"""
        return PROJECT_ROOT / relative_path
    
    @classmethod
    def ensure_dir(cls, relative_path: str) -> Path:
        """确保目录存在，如不存在则创建"""
        abs_path = cls.get_absolute_path(relative_path)
        abs_path.mkdir(parents=True, exist_ok=True)
        return abs_path

class Files:
    """文件名配置"""
    # 配置文件
    CAPABILITY_REGISTRY = "capability_registry.json"
    MCP_SERVERS = "servers.json"
    PROMPTS_REGISTRY = "prompts_registry.json"
    
    # 日志文件
    APP_LOG = "app.log"
    EVENTS_LOG = "events.log"
    TOOLS_LOG = "tools.log"
    HISTORY_JSONL = "history.jsonl"
    HISTORY_AGENT_JSONL = "history_agent.jsonl"
    
    # 数据库文件
    CHROMA_DB = "chroma.sqlite3"
    QA_HISTORY_DB = "qa_history.sqlite3"
    
    # 输出文件
    AGENT_EXPORT_PARAMS = "agent_export_params.json"
    AGENT_SCRIPT_GOOGLE = "agent_script_google.json"
    CLIENT_RUN_LOG = "client_run.log"
    
    # 环境文件
    ENV_EXAMPLE = ".env.example"
    REQUIREMENTS = "requirements.txt"

class Messages:
    """UI消息配置"""
    # 成功消息
    IMPORT_SUCCESS = "配置已导入并规范化"
    SAVE_SUCCESS = "配置已保存"
    EXPORT_SUCCESS = "配置已导出"
    DELETE_SUCCESS = "删除成功"
    
    # 错误消息
    IMPORT_ERROR = "导入失败"
    SAVE_ERROR = "保存失败"
    EXPORT_ERROR = "导出失败"
    DELETE_ERROR = "删除失败"
    VALIDATION_ERROR = "验证失败"
    
    # 警告消息
    UNSAVED_CHANGES = "有未保存的更改，是否继续？"
    DELETE_CONFIRM = "确认删除此项？"
    OVERWRITE_CONFIRM = "文件已存在，是否覆盖？"
    
    # 信息消息
    NO_SELECTION = "请先选择一项"
    OPERATION_CANCELLED = "操作已取消"
    LOADING = "加载中..."
    PROCESSING = "处理中..."

class UIConfig:
    """UI配置"""
    # 窗口配置
    MAIN_WINDOW_TITLE = "AutoGen Desktop Client"
    MAIN_WINDOW_SIZE = (1200, 800)
    MAIN_WINDOW_MIN_SIZE = (800, 600)
    
    # 字体配置
    DEFAULT_FONT_FAMILY = "Microsoft YaHei UI"
    DEFAULT_FONT_SIZE = 9
    CODE_FONT_FAMILY = "Consolas"
    CODE_FONT_SIZE = 10
    
    # 颜色配置
    PRIMARY_COLOR = "#2196F3"
    SUCCESS_COLOR = "#4CAF50"
    WARNING_COLOR = "#FF9800"
    ERROR_COLOR = "#F44336"
    
    # 间距配置
    DEFAULT_MARGIN = 10
    DEFAULT_SPACING = 5
    LARGE_SPACING = 15

class AgentConfig:
    """Agent配置"""
    # 默认配置
    DEFAULT_MODEL = "gpt-4"
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 2000
    
    # 系统消息约束
    TOOL_CONSTRAINT = "\n\n【重要约束】你必须调用工具或使用结构化输出格式回答。"
    
    # 运行配置
    MAX_CONSECUTIVE_AUTO_REPLY = 10
    TIMEOUT_SECONDS = 300

class LogConfig:
    """日志配置"""
    # 日志级别
    DEFAULT_LEVEL = "INFO"
    DEBUG_LEVEL = "DEBUG"
    
    # 日志格式
    DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    DETAILED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    
    # 日志文件配置
    MAX_BYTES = 10 * 1024 * 1024  # 10MB
    BACKUP_COUNT = 5

class ToolConfig:
    """工具配置"""
    # Google搜索配置
    GOOGLE_SEARCH_DEFAULT_RESULTS = 10
    
    # 向量库配置
    CHROMA_COLLECTION_PREFIX = "autogen_"
    DEFAULT_CHUNK_SIZE = 1000
    DEFAULT_CHUNK_OVERLAP = 200
    
    # MCP配置
    MCP_TIMEOUT_SECONDS = 30

# 环境变量配置
class EnvVars:
    """环境变量名称"""
    GOOGLE_API_KEY = "GOOGLE_API_KEY"
    GOOGLE_CSE_ID = "GOOGLE_CSE_ID"
    OPENAI_API_KEY = "OPENAI_API_KEY"
    ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
