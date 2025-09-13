# -*- coding: utf-8 -*-
"""
重构后的应用程序主入口
保持功能不变，采用模块化架构
"""
import sys
import os
import logging
from pathlib import Path
from typing import Optional, List

# 将项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 统一：在桌面客户端入口加载 .env，并清理进程内置同名变量，确保仅使用外部文件
# 实现策略：
# - 先清理已知模型/工具相关环境变量（白名单集合）
# - 再从项目根目录读取 .env 并写入 os.environ
# - 若缺少 python-dotenv，则使用简易解析回退
_ENV_KEYS_TO_RESET: List[str] = [
    # 模型/推理平台
    "OPENAI_API_KEY",
    "DASHSCOPE_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    # 检索/搜索工具
    "GOOGLE_API_KEY",
    "GOOGLE_CSE_CX",
    "BING_SEARCH_KEY",
    # 其他常见提供商（可按需扩展）
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
]

def _load_env_file_only(root: Path) -> None:
    """仅使用外部 .env，并清理进程内置相关环境变量。
    - root: 项目根目录（包含 .env）
    """
    # 1) 清理目标变量，避免使用继承进程环境
    for k in list(_ENV_KEYS_TO_RESET):
        if k in os.environ:
            try:
                del os.environ[k]
            except Exception:
                pass
    # 2) 载入 .env（优先 python-dotenv；无则回退简单解析）
    env_path = root / ".env"
    if not env_path.exists():
        return
    try:
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv(dotenv_path=env_path, override=True)
        except Exception:
            # 简易解析：仅处理 KEY=VALUE 行，忽略注释与空行
            for line in env_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if "=" not in s:
                    continue
                key, val = s.split("=", 1)
                key = key.strip()
                # 去掉可能的引号
                val = val.strip().strip('"').strip("'")
                if key:
                    os.environ[key] = val
    except Exception:
        # 环境加载失败不阻塞 UI
        pass

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from config.constants import UIConfig, LogConfig
from utils.error_handler import ErrorHandler
from app.ui.main_window import MainWindow
from services.config_service import ConfigService


def setup_logging() -> str:
    """设置日志记录"""
    try:
        from logs import setup_logging as setup_app_logging
        return setup_app_logging()
    except ImportError:
        # 简单的日志设置
        logging.basicConfig(
            level=getattr(logging, LogConfig.DEFAULT_LEVEL),
            format=LogConfig.DEFAULT_FORMAT
        )
        return "logs/app.log"


def setup_application() -> QApplication:
    """设置应用程序"""
    app = QApplication(sys.argv)
    
    # 设置应用程序属性
    app.setApplicationName(UIConfig.MAIN_WINDOW_TITLE)
    app.setApplicationVersion("0.6.2")
    
    # 设置字体
    font = app.font()
    font.setFamily(UIConfig.DEFAULT_FONT_FAMILY)
    font.setPointSize(UIConfig.DEFAULT_FONT_SIZE)
    app.setFont(font)
    
    return app


def preflight_check() -> bool:
    """启动前检查"""
    try:
        # 检查关键目录
        from config.constants import Paths
        
        # 确保关键目录存在
        Paths.ensure_dir(Paths.CONFIG_DIR)
        Paths.ensure_dir(Paths.LOGS_DIR)
        Paths.ensure_dir(Paths.DATA_DIR)
        Paths.ensure_dir(Paths.OUT_DIR)
        
        return True
        
    except Exception as e:
        print(f"[ERROR] 启动前检查失败: {e}")
        return False


def optimize_window_position(window: MainWindow) -> None:
    """优化窗口位置和大小"""
    try:
        from PySide6.QtGui import QGuiApplication
        
        # 获取屏幕信息
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
            
        avail = screen.availableGeometry()
        frame = window.frameGeometry()
        
        # 限制窗口大小
        margin_w = 100
        margin_h = 100
        max_w = max(800, avail.width() - margin_w)
        max_h = max(600, avail.height() - margin_h)
        
        new_w = min(frame.width(), max_w)
        new_h = min(frame.height(), max_h)
        
        if new_w != frame.width() or new_h != frame.height():
            window.resize(new_w, new_h)
        
        # 居中显示
        new_x = avail.left() + (avail.width() - new_w) // 2
        new_y = avail.top() + (avail.height() - new_h) // 2
        window.move(new_x, new_y)
        
    except Exception as e:
        print(f"[WARNING] 窗口位置优化失败: {e}")


def main():
    """主函数"""
    # 设置日志
    log_file = setup_logging()
    logger = ErrorHandler.setup_logging("main")
    logger.info("应用程序启动")
    # 加载外部 .env，并清理同名内置变量
    try:
        _load_env_file_only(ROOT)
        logger.info("本地 .env 已载入（进程内置变量已清理）")
    except Exception:
        logger.warning("本地 .env 载入失败或未找到，继续启动")
    
    # 启动前检查
    if not preflight_check():
        print("[ERROR] 启动前检查失败，应用程序退出")
        sys.exit(1)
    
    try:
        # 初始化本地配置目录（不涉及数据库）
        try:
            cfg_service = ConfigService()
            cfg_service.init_local_config()
            logger.info("本地配置初始化完成")
        except Exception as init_e:
            logger.warning(f"本地配置初始化警告（不阻塞启动）：{init_e}")
        
        # 创建应用程序
        app = setup_application()
        logger.info(f"Qt应用程序创建成功")
        
        # 创建主窗口
        window = MainWindow()
        logger.info("主窗口创建成功")
        
        # 优化窗口位置
        optimize_window_position(window)
        
        # 显示窗口
        window.show()
        logger.info("主窗口显示成功")
        
        # 运行应用程序
        exit_code = app.exec()
        logger.info(f"应用程序退出，退出码: {exit_code}")
        
        return exit_code
        
    except Exception as e:
        logger.exception(f"应用程序运行失败: {e}")
        print(f"[ERROR] 应用程序运行失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
