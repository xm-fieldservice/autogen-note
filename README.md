# autogen-note

基于 Autogen 0.7.1 的本地项目仓库骨架（非容器化）。

## 特性
- 使用 `requirements.txt` 管理依赖，固定 Autogen 0.7.1 版本。
- 预置 GitHub Actions CI（安装依赖并进行基本校验）。
- 可与现有环境变量文件 `.env` 协同（建议放置于项目根目录或通过 `--env-file` 指定）。

## 快速开始
```bash
# 进入项目目录
cd /home/ecs-assist-user/Projects/autogen-note

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# （可选）将你的 .env 放到项目根目录
# cp /home/ecs-assist-user/Projects/.env ./.env

# 按需创建你的应用入口与代码结构
# 例如：services/server/main.py
```

## 目录结构
- `requirements.txt` 依赖清单
- `.github/workflows/ci.yml` CI 配置
- `.gitignore` 常用忽略规则

## 注意
- 所有代码需优先遵循 Autogen 0.7.1 规范与内生机制。
- 建议以 `main` 为默认分支。
