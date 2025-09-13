# Web 笔记应用 原生（非 Docker）迁移包使用说明

本目录提供一套在 Linux 服务器上原生部署（无 Docker）的完整迁移包与说明，遵循 AutoGen 0.7.1 框架规范，仅使用框架内生机制运行。

- 目录路径：`migration-package-native/`
- 适用系统：Ubuntu 20.04+/22.04+，CentOS/RHEL 8+/Rocky/AlmaLinux
- 部署方式：Python 虚拟环境 + systemd + Nginx（可选）

---

## 一、目录结构

```
migration-package-native/
├─ app/                     # 客户端/页面与UI相关代码（不参与agent运行，仅外皮）
├─ config/                  # 配置文件（包含agents、models等）
├─ services/                # 后端服务代码（含 services/server/app.py）
├─ tools/                   # 工具集合（全部通过AutoGen内生机制集成）
├─ utils/                   # 工具函数/日志等
├─ web/                     # 静态前端资源（Nginx直接服务）
├─ .env.example             # 环境变量示例（复制为 .env 并填入密钥）
├─ requirements.txt         # 原生部署依赖清单（已清理标准库项）
├─ deploy-native.sh         # 一键原生部署脚本（Linux）
├─ README-Native-Migration.md# 本说明
└─ 服务器环境软件部署清单.md  # 服务器端准备与检查项
```

> 注意：按照项目要求，所有 agent/team 的运行均由外部脚本承载（不在页面内执行）。页面仅作为可视化外皮，通过参数传递给外部脚本运行，严格遵循 AutoGen 0.7.1 内生机制。

---

## 二、服务器准备

- 已开通 80 端口（HTTP）以及内网必要出站访问
- 安装基本系统工具（`curl`, `git` 等）
- 具备 `root` 权限或 `sudo` 提权能力
- 建议：使用全新、干净的云主机环境

参考《服务器环境软件部署清单.md》，逐项完成检查。

---

## 三、上传迁移包

在本地将 `migration-package-native/` 打包为 zip 并上传至服务器（下文提供一键打包命令）。也可以直接通过 VSCode / WinSCP / scp 等方式上传整个目录。

服务器侧操作示例（以 `/root/web-notes/` 为例）：

```bash
mkdir -p /root/web-notes
cd /root/web-notes
# 上传后解压：
unzip migration-package-native.zip -d .
ls -la migration-package-native
```

---

## 四、配置环境变量

复制示例并填入你的密钥与服务器路径：

```bash
cd /root/web-notes/migration-package-native
cp .env.example .env
nano .env  # 修改 DASHSCOPE_API_KEY 等
```

关键变量说明：
- `DASHSCOPE_API_KEY`：通义千问必填
- `DATABASE_URL`：默认 SQLite，可保持不变；生产建议挂载到数据盘
- `CHROMA_PERSIST_DIRECTORY`：ChromaDB 持久化目录

---

## 五、一键部署

执行原生部署脚本（将自动安装系统依赖、创建用户、创建虚拟环境、安装依赖、生成 systemd、配置 Nginx 等）：

```bash
chmod +x deploy-native.sh
sudo ./deploy-native.sh
```

成功后输出访问提示：
- Web 页面：`http://服务器IP/`
- API（示例健康检查）：`http://服务器IP/api/health` 或 `http://服务器IP:3000/health`
- ChromaDB：`http://服务器IP:8001`

---

## 六、服务管理

使用 `systemd` 管理服务：

```bash
# 状态
sudo systemctl status web-notes-api
sudo systemctl status web-notes-chroma
sudo systemctl status web-notes-data

# 重启
sudo systemctl restart web-notes-api

# 日志
sudo journalctl -u web-notes-api -f
```

Nginx 日志：

```bash
sudo tail -f /var/log/web-notes/nginx-error.log
sudo tail -f /var/log/web-notes/nginx-access.log
```

---

## 七、常见问题与排查

- 80 端口无法访问：检查安全组/防火墙（`ufw`/`firewalld`）是否放行 80
- API 500 错误：检查 `.env` 是否填写了 `DASHSCOPE_API_KEY`，并重启 `web-notes-api`
- ChromaDB 无法启动：确认 `chromadb` 目录权限为应用用户，端口 8001 未被占用
- 端口占用：`sudo lsof -i:80 -i:3000 -i:8001 -i:8002`

---

## 八、升级/回滚

- 升级：
  1. 备份数据目录（`.env` 与 `/var/lib/web-notes/`）
  2. 覆盖 `app/`, `services/`, `tools/`, `utils/`, `web/`, `config/`
  3. `sudo systemctl restart web-notes-api`

- 回滚：
  1. 还原备份数据与代码
  2. `sudo systemctl restart web-notes-api`

---

## 九、符合 AutoGen 0.7.1 规范的说明

- 配置、模型客户端、工具、MCP 集成均按 AutoGen 0.7.1 内生机制组织（详见 `config/` 与 `services/server/`）
- 页面/客户端只做“外皮”，通过参数调用外部运行脚本承载 agent/team 的实际运行
- 部署使用 `.env` 注入运行时所需参数，遵循 PowerShell/Linux 环境规范

---

## 十、本地一键打包命令（Windows PowerShell）

在项目根目录执行以下命令，生成迁移包 zip（我也会自动为你执行）：

```powershell
Compress-Archive -Path "migration-package-native/*" -DestinationPath "out/migration-package-native.zip" -Force
```

> 如无 `out/` 目录，将自动创建。

---

完成以上步骤后，你即可将 `migration-package-native.zip` 上传到服务器并按本文档执行一键部署。
