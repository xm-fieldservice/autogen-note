#!/bin/bash

# Web笔记应用原生部署脚本
# 适用于Ubuntu/CentOS/RHEL系统的无Docker部署方案
# 版本: 1.0
# 更新时间: 2025-09-13

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
APP_NAME="web-notes"
APP_USER="webnotes"
APP_DIR="/opt/web-notes"
DATA_DIR="/var/lib/web-notes"
LOG_DIR="/var/log/web-notes"
VENV_PATH="$APP_DIR/venv"
SERVICE_PREFIX="web-notes"

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 检查是否为root用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要root权限运行"
        exit 1
    fi
}

# 检测操作系统
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
    else
        log_error "无法检测操作系统版本"
        exit 1
    fi
    
    log_info "检测到操作系统: $OS $VER"
}

# 安装系统依赖
install_system_deps() {
    log_step "安装系统依赖包..."
    
    case $OS in
        ubuntu|debian)
            apt-get update
            apt-get install -y \
                python3 python3-pip python3-venv python3-dev \
                nginx sqlite3 git curl wget \
                build-essential libssl-dev libffi-dev \
                supervisor htop tree
            ;;
        centos|rhel|rocky|almalinux)
            if command -v dnf &> /dev/null; then
                dnf update -y
                dnf install -y \
                    python3 python3-pip python3-devel \
                    nginx sqlite git curl wget \
                    gcc gcc-c++ openssl-devel libffi-devel \
                    supervisor htop tree
            else
                yum update -y
                yum install -y \
                    python3 python3-pip python3-devel \
                    nginx sqlite git curl wget \
                    gcc gcc-c++ openssl-devel libffi-devel \
                    supervisor htop tree
            fi
            ;;
        *)
            log_error "不支持的操作系统: $OS"
            exit 1
            ;;
    esac
    
    log_info "系统依赖安装完成"
}

# 创建应用用户
create_app_user() {
    log_step "创建应用用户..."
    
    if ! id "$APP_USER" &>/dev/null; then
        useradd -r -s /bin/bash -d "$APP_DIR" -m "$APP_USER"
        log_info "用户 $APP_USER 创建成功"
    else
        log_info "用户 $APP_USER 已存在"
    fi
}

# 创建目录结构
create_directories() {
    log_step "创建目录结构..."
    
    # 创建主要目录
    mkdir -p "$APP_DIR"/{app,config,scripts}
    mkdir -p "$DATA_DIR"/{sqlite,chroma,uploads,logs}
    mkdir -p "$LOG_DIR"
    
    # 设置权限
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
    chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
    chown -R "$APP_USER:$APP_USER" "$LOG_DIR"
    
    log_info "目录结构创建完成"
}

# 复制应用文件
copy_app_files() {
    log_step "复制应用文件..."
    
    # 复制核心应用文件
    cp -r app/ "$APP_DIR/"
    cp -r config/ "$APP_DIR/"
    cp -r services/ "$APP_DIR/"
    cp -r web/ "$APP_DIR/"
    cp -r tools/ "$APP_DIR/"
    cp -r utils/ "$APP_DIR/"
    
    # 复制配置文件
    cp .env.example "$APP_DIR/.env.example"
    cp requirements.txt "$APP_DIR/"
    
    # 设置权限
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
    
    log_info "应用文件复制完成"
}

# 创建Python虚拟环境
create_venv() {
    log_step "创建Python虚拟环境..."
    
    sudo -u "$APP_USER" python3 -m venv "$VENV_PATH"
    sudo -u "$APP_USER" "$VENV_PATH/bin/pip" install --upgrade pip setuptools wheel
    
    log_info "Python虚拟环境创建完成"
}

# 安装Python依赖
install_python_deps() {
    log_step "安装Python依赖包..."
    
    sudo -u "$APP_USER" "$VENV_PATH/bin/pip" install -r "$APP_DIR/requirements.txt"
    
    log_info "Python依赖安装完成"
}

# 配置环境变量
setup_env() {
    log_step "配置环境变量..."
    
    if [[ ! -f "$APP_DIR/.env" ]]; then
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        
        # 更新配置文件中的路径
        sed -i "s|DATABASE_URL=.*|DATABASE_URL=sqlite:///$DATA_DIR/sqlite/config.sqlite3|g" "$APP_DIR/.env"
        sed -i "s|CHROMA_PERSIST_DIRECTORY=.*|CHROMA_PERSIST_DIRECTORY=$DATA_DIR/chroma|g" "$APP_DIR/.env"
        
        chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
        chmod 600 "$APP_DIR/.env"
        
        log_warn "请编辑 $APP_DIR/.env 文件，设置你的API密钥"
    else
        log_info "环境配置文件已存在"
    fi
}

# 配置Nginx
setup_nginx() {
    log_step "配置Nginx..."
    
    cat > /etc/nginx/sites-available/web-notes << 'EOF'
server {
    listen 80;
    server_name _;
    
    # 静态文件服务
    location /static/ {
        alias /opt/web-notes/web/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # API代理
    location /api/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_timeout 30s;
    }
    
    # ChromaDB代理
    location /chroma/ {
        proxy_pass http://127.0.0.1:8001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    
    # 主页面
    location / {
        root /opt/web-notes/web;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
    
    # 日志配置
    access_log /var/log/web-notes/nginx-access.log;
    error_log /var/log/web-notes/nginx-error.log;
}
EOF
    
    # 启用站点
    if [[ -d /etc/nginx/sites-enabled ]]; then
        ln -sf /etc/nginx/sites-available/web-notes /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
    else
        # CentOS/RHEL风格配置
        cp /etc/nginx/sites-available/web-notes /etc/nginx/conf.d/web-notes.conf
    fi
    
    # 测试Nginx配置
    nginx -t
    
    log_info "Nginx配置完成"
}

# 创建systemd服务
create_systemd_services() {
    log_step "创建systemd服务..."
    
    # API服务
    cat > /etc/systemd/system/web-notes-api.service << EOF
[Unit]
Description=Web Notes API Service
After=network.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_PATH/bin
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_PATH/bin/gunicorn -c gunicorn.conf.py services.server.app:app
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # ChromaDB服务
    cat > /etc/systemd/system/web-notes-chroma.service << EOF
[Unit]
Description=Web Notes ChromaDB Service
After=network.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_PATH/bin
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_PATH/bin/python -m chromadb.cli run --host 0.0.0.0 --port 8001 --path $DATA_DIR/chroma
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # 数据服务
    cat > /etc/systemd/system/web-notes-data.service << EOF
[Unit]
Description=Web Notes Data Service
After=network.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_PATH/bin
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_PATH/bin/python services/data_service.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # 创建Gunicorn配置
    cat > "$APP_DIR/gunicorn.conf.py" << EOF
# Gunicorn配置文件
bind = "0.0.0.0:3000"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 30
keepalive = 2
preload_app = True
accesslog = "/var/log/web-notes/gunicorn-access.log"
errorlog = "/var/log/web-notes/gunicorn-error.log"
loglevel = "info"
EOF

    chown "$APP_USER:$APP_USER" "$APP_DIR/gunicorn.conf.py"
    
    # 重新加载systemd
    systemctl daemon-reload
    
    log_info "systemd服务创建完成"
}

# 启动服务
start_services() {
    log_step "启动服务..."
    
    # 启用并启动服务
    systemctl enable web-notes-api web-notes-chroma web-notes-data nginx
    systemctl start web-notes-chroma
    sleep 3
    systemctl start web-notes-data
    sleep 3
    systemctl start web-notes-api
    systemctl start nginx
    
    log_info "服务启动完成"
}

# 验证部署
verify_deployment() {
    log_step "验证部署状态..."
    
    # 检查服务状态
    services=("web-notes-api" "web-notes-chroma" "web-notes-data" "nginx")
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet "$service"; then
            log_info "✓ $service 运行正常"
        else
            log_error "✗ $service 运行异常"
            systemctl status "$service" --no-pager
        fi
    done
    
    # 检查端口
    log_info "检查服务端口:"
    netstat -tlnp | grep -E ':(80|3000|8001|8002)\s'
    
    # 测试API连接
    if curl -s http://localhost:3000/health > /dev/null; then
        log_info "✓ API服务连接正常"
    else
        log_warn "✗ API服务连接异常"
    fi
}

# 显示部署信息
show_deployment_info() {
    log_step "部署完成信息"
    
    cat << EOF

${GREEN}========================================${NC}
${GREEN}    Web笔记应用部署完成!${NC}
${GREEN}========================================${NC}

${BLUE}应用信息:${NC}
  - 应用目录: $APP_DIR
  - 数据目录: $DATA_DIR
  - 日志目录: $LOG_DIR
  - 应用用户: $APP_USER

${BLUE}服务管理:${NC}
  - 查看状态: systemctl status web-notes-api
  - 重启服务: systemctl restart web-notes-api
  - 查看日志: journalctl -u web-notes-api -f

${BLUE}访问地址:${NC}
  - Web界面: http://服务器IP
  - API文档: http://服务器IP/api/docs
  - ChromaDB: http://服务器IP:8001

${YELLOW}重要提醒:${NC}
  1. 请编辑 $APP_DIR/.env 文件设置API密钥
  2. 重启API服务使配置生效: systemctl restart web-notes-api
  3. 检查防火墙设置，确保端口80可访问
  4. 定期备份数据目录: $DATA_DIR

${BLUE}故障排查:${NC}
  - 服务日志: journalctl -u web-notes-api -f
  - Nginx日志: tail -f /var/log/web-notes/nginx-error.log
  - 应用日志: tail -f $LOG_DIR/app.log

EOF
}

# 主函数
main() {
    log_info "开始Web笔记应用原生部署..."
    
    check_root
    detect_os
    install_system_deps
    create_app_user
    create_directories
    copy_app_files
    create_venv
    install_python_deps
    setup_env
    setup_nginx
    create_systemd_services
    start_services
    verify_deployment
    show_deployment_info
    
    log_info "部署脚本执行完成!"
}

# 执行主函数
main "$@"
