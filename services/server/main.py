#!/usr/bin/env python3
"""
AutoGen 0.7.1 服务器启动入口
支持Docker容器化部署和本地开发环境
"""
import argparse
import uvicorn
import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

def load_env_file(env_file_path: str = None):
    """加载环境变量文件"""
    if env_file_path and Path(env_file_path).exists():
        with open(env_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

def main():
    parser = argparse.ArgumentParser(description='AutoGen 0.7.1 Notes Backend Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    parser.add_argument('--env-file', help='Path to .env file')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload for development')
    parser.add_argument('--log-level', default='info', choices=['debug', 'info', 'warning', 'error'])
    
    args = parser.parse_args()
    
    # 加载环境变量
    if args.env_file:
        load_env_file(args.env_file)
    else:
        # 尝试加载项目根目录的.env文件
        root_env = Path(__file__).resolve().parents[2] / '.env'
        if root_env.exists():
            load_env_file(str(root_env))
    
    # 检查必要的环境变量
    required_env_vars = ['DASHSCOPE_API_KEY']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ 缺少必要的环境变量: {', '.join(missing_vars)}")
        print("请确保在.env文件中设置了这些变量")
        sys.exit(1)
    
    print(f"🚀 启动AutoGen 0.7.1 Notes Backend")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Environment: {'Development' if args.reload else 'Production'}")
    
    # 启动服务器
    uvicorn.run(
        "services.server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        access_log=True
    )

if __name__ == "__main__":
    main()
