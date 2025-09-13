# -*- coding: utf-8 -*-
"""
重构后的主窗口
从app.py中提取的MainWindow类，采用模块化架构
"""
import sys
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import json
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QPushButton, 
    QLineEdit, QTextEdit, QMessageBox, QSizePolicy, QGroupBox, QFormLayout,
    QListWidget, QComboBox, QScrollArea, QListWidgetItem, QSplitter,
    QInputDialog, QDoubleSpinBox, QSpinBox, QCheckBox, QApplication, QFileDialog
)
from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt, QEvent, QSettings
from PySide6.QtGui import QFont, QShortcut, QKeySequence

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.constants import UIConfig, AgentConfig, Paths
from utils.error_handler import ErrorHandler, ProgressHandler
from app.services.model_service import ModelService
from app.services.agent_service import AgentService
from app.services.notes_agent_service import NotesAgentService
from app.ui.dialogs.advanced_settings_dialog import AdvancedSettingsDialog
from app.ui.dialogs.advanced_json_dialog import AdvancedJsonDialog
from app.ui.dialogs.history_dialog import HistoryDialog
from app.ui.widgets.collapsible_panel import CollapsiblePanel
from ui.pages.team_management import TeamManagementPage
from app.ui.pages.config_explorer import ConfigExplorerPage
from ui.pages.warehouse_vectorstores import WarehouseVectorStoresDialog
from ui.pages.warehouse_dual_library import WarehouseDualLibraryDialog
from app.ui.pages.project_page import ProjectPage
from app.ui.pages.vector_memory_debug import VectorMemoryDebugPage
from app.ui.pages.project_config_generator import ProjectConfigGeneratorPage

# 导入原有的后端类
try:
    from autogen_client.agents import AgentBackend
    from autogen_client.autogen_backends import AutogenAgentBackend, AutogenTeamBackend
    from autogen_client.config_loader import load_agent_json, load_team_json, save_json
    from autogen_client.agents import AgentScriptIntegrator
except ImportError as e:
    print(f"[WARNING] 导入后端模块失败: {e}")

# 配置服务（已移除数据库依赖）
ConfigService = None  # 明确禁止使用数据库


class AgentInferWorker(QObject):
    """Agent推理工作线程"""
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, backend: 'AutogenAgentBackend', prompt: str):
        super().__init__()
        self._backend = backend
        self._prompt = prompt

    @Slot()
    def run(self):
        try:
            if self._backend is None:
                raise ValueError("后端对象未初始化，请先加载Agent配置文件")
            
            if not self._prompt or not isinstance(self._prompt, str):
                raise ValueError("输入提示为空或格式不正确")
            
            if not hasattr(self._backend, "infer_once") or not callable(getattr(self._backend, "infer_once", None)):
                raise ValueError("后端对象缺少 infer_once 方法")
            
            result = self._backend.infer_once(self._prompt)
            
            if result is None:
                raise ValueError("Agent推理返回空结果")
            
            self.finished.emit(str(result))
            
        except Exception as e:
            try:
                friendly_error = "Agent推理失败，可能的原因：\n"
                friendly_error += "1. 模型配置错误或API密钥无效\n"
                friendly_error += "2. 网络连接问题\n"
                friendly_error += "3. 输入内容格式不正确\n"
                friendly_error += "4. Agent配置文件损坏"
                
                error_str = str(e)
                if len(error_str) > 150:
                    error_str = error_str[:147] + "..."
                friendly_error += f"\n原始错误: {error_str}"
                
                self.failed.emit(friendly_error)
            except Exception:
                self.failed.emit(f"Agent推理失败: {str(e)[:100]}")


class ScriptInferWorker(QObject):
    """脚本推理工作线程"""
    finished = Signal(str)
    failed = Signal(str)
    
    def __init__(self, config_path: str, prompt: str, memory_policy: str = None, verbose: bool = False, timeout: int = 300):
        super().__init__()
        self._config_path = config_path
        self._prompt = prompt
        self._memory_policy = memory_policy
        self._verbose = verbose
        self._timeout = timeout  # 可配置的超时时间，默认5分钟
        # 改为外部脚本执行，不再使用内部集成器
        self._integrator = None
        
    @Slot()
    def run(self):
        try:
            if not self._config_path or not os.path.exists(self._config_path):
                raise ValueError(f"配置文件不存在: {self._config_path}")

            # 解析模型信息并打印到终端（不进入UI）：模型名 / base_url / api_key
            try:
                with open(self._config_path, 'r', encoding='utf-8') as _f:
                    _data = json.load(_f) if _f else {}
            except Exception:
                _data = {}
            # 只读提取：同时支持顶层与 config.* 两种布局
            _cfg = dict((_data or {}).get('config') or {})
            def _get(key, default=None):
                v = _cfg.get(key) if isinstance(_cfg, dict) else None
                if v is None:
                    v = (_data or {}).get(key, default)
                return v
            _name = str(_get('name') or _get('model') or '')
            _base_url = str(_get('base_url') or '')
            _api_key_env = str(_get('api_key_env') or '')
            # 深层兼容：从 config.model_client.config 读取 base_url / api_key_env；若仅有 api_key=${ENV} 则提取 ENV
            try:
                _mc = ((_data or {}).get('config') or {}).get('model_client') or {}
                _mcc = _mc.get('config') or {}
                if not _base_url:
                    _base_url = str(_mcc.get('base_url') or '')
                if not _api_key_env:
                    _api_key_env = str(_mcc.get('api_key_env') or '')
                if (not _api_key_env) and isinstance(_mcc.get('api_key'), str):
                    import re as __re
                    m = __re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$", _mcc.get('api_key').strip())
                    if m:
                        _api_key_env = m.group(1)
            except Exception:
                pass
            _timeout = _get('timeout')
            _params = _cfg.get('parameters') if isinstance(_cfg, dict) else None
            if not isinstance(_params, dict):
                _params = dict((_data or {}).get('parameters') or {})
            _api_key_val = os.environ.get(_api_key_env, '') if _api_key_env else ''
            # 默认做掩码，若需明文可改此处
            _masked = (_api_key_val[:4] + '...' + _api_key_val[-3:]) if _api_key_val else ''
            try:
                print(f"[MODEL_INFO] name={_name or '-'} | base_url={_base_url or '-'} | {(_api_key_env or 'API_KEY') }={_masked or '未设置'}")
            except Exception:
                pass
            # 运行现成外部脚本 scripts/run_agent.py 执行一次推理
            try:
                import sys, subprocess, time
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                script = os.path.join(base_dir, 'scripts', 'run_agent.py')
                if not os.path.exists(script):
                    raise FileNotFoundError(f"脚本不存在: {script}")
                cmd = [
                    sys.executable,
                    '-X', 'utf8', '-u',
                    script,
                    '-c', self._config_path,
                    '--input', self._prompt or ''
                ]
                # 诊断打印（控制台）
                try:
                    print(f"[SCRIPT] run_agent start | cwd={base_dir}")
                    print(f"[SCRIPT] cmd={' '.join(cmd)}")
                except Exception:
                    pass
                # 环境：强制 UTF-8，无缓冲
                env = dict(os.environ)
                env.setdefault('PYTHONIOENCODING', 'utf-8')
                env.setdefault('PYTHONUNBUFFERED', '1')
                start = time.time()
                # 通过 stdin 提供一轮输入并退出，模拟交互式单轮（可扩展为多轮）
                stdin_text = (self._prompt or '').replace('\r\n','\n').strip() + "\n:quit\n"
                res = subprocess.run(
                    cmd,
                    cwd=base_dir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=self._timeout,
                    env=env,
                    input=stdin_text,
                )
                dur = time.time() - start
                out = res.stdout or ''
                try:
                    err = res.stderr or ''
                    if err.strip():
                        lines = [l for l in err.splitlines() if l.strip()]
                        tail = "\n".join(lines[-30:]) if lines else err
                        print(f"[SCRIPT][stderr-tail]\n{tail}")
                    print(f"[SCRIPT] run_agent done | rc={res.returncode} | dur={dur:.2f}s")
                except Exception:
                    pass
                # 解析并回传
                try:
                    parsed = self._parse_output(out)
                    if isinstance(parsed, str) and parsed.strip():
                        self.finished.emit(parsed)
                        return
                except Exception:
                    pass
                # 兜底：直接回传原始输出
                self.finished.emit(out or '')
                return
            except Exception as ex:
                self.failed.emit(f"脚本运行失败: {ex}")
                return
        except Exception as e:
            # 兜底：外层 try 必须有 except/finally；此处上报初始化错误
            self.failed.emit(f"脚本推理初始化失败: {e}")

    # 注意：默认Tab相关逻辑属于 MainWindow，这里移除误放的方法，避免混淆。

    
            
        except Exception as e:
            self.failed.emit(f"脚本推理失败: {e}")
    
    def _parse_output(self, output: str):
        """解析脚本输出"""
        try:
            lines = output.strip().split('\n')
            assistant_prefix = "Assistant: "
            zh_assistant_prefix = "[助手-"
            
            for line in lines:
                if line.startswith(assistant_prefix):
                    response = line[len(assistant_prefix):].strip()
                    self.finished.emit(response)
                    return
                # 兼容外部脚本格式：[助手-1] <content>
                if line.startswith(zh_assistant_prefix):
                    # 寻找右括号后的内容
                    try:
                        # 形如：[助手-1] 回复...  [来源:xxx]
                        right = line.split('] ', 1)
                        if len(right) == 2:
                            response = right[1].strip()
                            # 去掉尾部来源标记
                            if '  [来源:' in response:
                                response = response.split('  [来源:', 1)[0].rstrip()
                            self.finished.emit(response)
                            return
                    except Exception:
                        pass
            
            self.finished.emit(output)
            
        except Exception as e:
            print(f"[UI_SCRIPT_ERROR] 解析输出失败: {e}")
            self.finished.emit(output)


class EnterToSendFilter(QObject):
    """QTextEdit 过滤器：Enter 发送；Shift/Ctrl+Enter 换行。"""
    def __init__(self, sender_callback):
        super().__init__()
        self._callback = sender_callback

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                mods = event.modifiers()
                # 仅当无修饰键时触发发送
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (mods == Qt.KeyboardModifier.NoModifier):
                    # 调用发送回调并吞掉事件（不插入换行）
                    if callable(self._callback):
                        try:
                            self._callback()
                        except Exception as e:
                            print(f"[DEBUG] EnterToSendFilter callback failed: {e}")
                    return True
            return False  # 不拦截其他事件，让QTextEdit正常处理
        except Exception as e:
            print(f"[DEBUG] EnterToSendFilter eventFilter failed: {e}")
            # 出错时不拦截，维持默认行为
            return False

class NotesAskWorker(QObject):
    """笔记问答工作线程"""
    finished = Signal(str)
    failed = Signal(str)
    
    def __init__(self, service: 'NotesAgentService', prompt: str, system_message: str = ""):
        super().__init__()
        self._service = service
        self._prompt = prompt
        self._system_message = system_message or ""

    @Slot()
    def run(self):
        try:
            if not self._prompt or not isinstance(self._prompt, str):
                raise ValueError("输入提示为空或格式不正确")
            
            # 设置运行时 system_message 并调用问答
            if self._service is None:
                raise ValueError("笔记问答服务未初始化")
            if self._system_message:
                try:
                    self._service.set_system_message(self._system_message)
                except Exception:
                    pass
            result = self._service.ask(self._prompt)
            
            if result is None:
                raise ValueError("笔记问答返回空结果")
            
            self.finished.emit(str(result))
            
        except Exception as e:
            try:
                friendly_error = "笔记问答失败，可能的原因：\n"
                friendly_error += "1. 输入内容格式不正确\n"
                friendly_error += "2. 笔记问答服务不可用"
                
                error_str = str(e)
                if len(error_str) > 150:
                    error_str = error_str[:147] + "..."
                friendly_error += f"\n原始错误: {error_str}"
                
                self.failed.emit(friendly_error)
            except Exception:
                self.failed.emit(f"笔记问答失败: {str(e)[:100]}")


class NotesRecordWorker(QObject):
    """笔记记录工作线程"""
    finished = Signal(str)
    failed = Signal(str)
    
    def __init__(self, service: NotesAgentService, prompt: str, tags: List[str] | None = None):
        super().__init__()
        self._service = service
        self._prompt = prompt
        self._tags = list(tags) if tags else None

    @Slot()
    def run(self):
        try:
            if not self._prompt or not isinstance(self._prompt, str):
                raise ValueError("输入提示为空或格式不正确")
            
            # 调用 NotesAgentService 进行记录
            if self._service is None:
                raise ValueError("笔记记录服务未初始化")
            res = self._service.record_only(self._prompt, tags=self._tags)
            result = f"已写入 {res.get('written', 0)} 条到 {res.get('memories', 0)} 个集合"
            
            if result is None:
                raise ValueError("笔记记录返回空结果")
            
            self.finished.emit(str(result))
            
        except Exception as e:
            try:
                friendly_error = "笔记记录失败，可能的原因：\n"
                friendly_error += "1. 输入内容格式不正确\n"
                friendly_error += "2. 笔记记录服务不可用"
                
                error_str = str(e)
                if len(error_str) > 150:
                    error_str = error_str[:147] + "..."
                friendly_error += f"\n原始错误: {error_str}"
                
                self.failed.emit(friendly_error)
            except Exception:
                self.failed.emit(f"笔记记录失败: {str(e)[:100]}")


class NotesRecallWorker(QObject):
    """笔记回忆工作线程"""
    finished = Signal(list)
    failed = Signal(str)
    
    def __init__(self, service: 'NotesAgentService', query: str, k: int = 5):
        super().__init__()
        self._service = service
        self._query = query
        self._k = int(k or 5)

    @Slot()
    def run(self):
        try:
            if not self._query or not isinstance(self._query, str):
                raise ValueError("查询为空或格式不正确")
            if self._service is None:
                raise ValueError("笔记回忆服务未初始化")
            items = self._service.direct_recall(self._query, k=self._k)
            self.finished.emit(items or [])
        except Exception as e:
            self.failed.emit(f"笔记回忆失败: {str(e)[:160]}")

class NotesScriptWorker(QObject):
    """通过外部脚本 run_team_interactive.py 进行一次性处理（输入后立即退出）。"""
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, root_dir: str, config_path: str, prompt: str,
                 force_policy: str = "qa_both", ui_mode: str = "note",
                 topic_id: str | None = None, topic_name: str | None = None,
                 attachments: list[str] | None = None):
        super().__init__()
        self._root = root_dir
        self._cfg = config_path
        self._prompt = prompt or ""
        self._policy = force_policy
        self._ui_mode = ui_mode or "note"
        self._topic_id = topic_id
        self._topic_name = topic_name
        self._attachments = list(attachments) if attachments else []

    def _strip_ansi(self, s: str) -> str:
        try:
            import re
            ansi_re = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
            return ansi_re.sub("", s or "")
        except Exception:
            return s

    def _parse_output(self, output: str) -> str:
        try:
            clean = self._strip_ansi(output or "")
            lines = clean.splitlines()
            assistant_prefix = "Assistant: "
            zh_assistant_prefix = "[助手-"
            script_prefix = "[SCRIPT] "
            route_prefix = "[ROUTE] "
            # 优先规则：严格对齐脚本输出，仅呈现由分隔线（--- 或 ——）包裹的正文内容。
            # 若存在多个分隔区块，按出现顺序收集并以空行拼接；若不存在则走后续兼容逻辑。
            try:
                blocks: list[str] = []
                cur: list[str] = []
                inside = False
                def _is_sep(s: str) -> bool:
                    t = s.strip().replace('—', '-')
                    return t and set(t) == {'-'} and len(t) >= 3
                for raw in lines:
                    if _is_sep(raw):
                        if inside:
                            # 结束一个块
                            if cur and any(x.strip() for x in cur):
                                blocks.append("\n".join(cur).strip())
                            cur = []
                            inside = False
                        else:
                            # 开始一个块
                            inside = True
                            cur = []
                        continue
                    if inside:
                        cur.append(raw)
                if blocks:
                    body = "\n\n".join([b for b in blocks if b.strip()])
                    if body.strip():
                        return body.strip()
            except Exception:
                pass
            # 1) 聚合中文 [助手-*] 段落，兼容以 "[SCRIPT] [助手-*]" 开头的行
            agg = []
            capturing = False
            for i, raw in enumerate(lines):
                line = raw.strip()
                # 兼容 [SCRIPT] 前缀
                l = line
                if l.startswith(script_prefix):
                    l = l[len(script_prefix):].lstrip()
                if not capturing:
                    if l.startswith(zh_assistant_prefix):
                        # 当前行内容
                        try:
                            right = l.split('] ', 1)
                            if len(right) == 2:
                                first = right[1].rstrip()
                                agg.append(first)
                                capturing = True
                                continue
                        except Exception:
                            pass
                else:
                    # 结束条件：遇到下一个事件块
                    # 例如 [用户- / [向量库] / [环境] / [配置] / [查询] 等
                    end_markers = ("[用户-", "[向量库]", "[环境]", "[配置]", "[查询]", "[MODEL_INFO]", "=== 欢迎使用")
                    l2 = l
                    if l2.startswith(script_prefix):
                        l2 = l2[len(script_prefix):].lstrip()
                    if l2.startswith('[') and (l2.startswith(zh_assistant_prefix) is False):
                        if l2.startswith(end_markers):
                            break
                    # 普通内容行，加入聚合
                    agg.append(l)
            if agg:
                resp = "\n".join([self._strip_ansi(x) for x in agg]).strip()
                if '  [来源:' in resp:
                    resp = resp.split('  [来源:', 1)[0].rstrip()
                return resp
            # 2) 其次匹配英文 Assistant: 
            for line in lines:
                l = line.strip()
                if l.startswith(assistant_prefix):
                    return self._strip_ansi(l[len(assistant_prefix):].strip())
            # 2.5) 优先匹配 [ROUTE] 诊断头 + 紧随其后的正文（适配 team runner 的输出形态）
            try:
                acc = []
                capturing = False
                for raw in lines:
                    l0 = raw.strip()
                    # 跳过 [SCRIPT] 前缀壳
                    if l0.startswith(script_prefix):
                        l0 = l0[len(script_prefix):].lstrip()
                    if not capturing and l0.startswith(route_prefix):
                        capturing = True
                        acc.append(l0)
                        continue
                    if capturing:
                        # 截止条件：遇到下一次输入提示或空到仅调试行（防止过度捕获）
                        if l0.startswith("[用户-"):
                            break
                        acc.append(l0)
                if capturing and acc:
                    resp = "\n".join([self._strip_ansi(x) for x in acc]).strip()
                    return resp
            except Exception:
                pass
            # 3) 兜底：返回尾部非空文本
            tail = [l for l in lines if l.strip()]
            return tail[-1].strip() if tail else clean.strip()
        except Exception:
            return output

    @Slot()
    def run(self):
        try:
            if not self._cfg or not os.path.exists(self._cfg):
                raise ValueError(f"配置文件不存在: {self._cfg}")
            import subprocess, sys, time
            # 切换为团队运行器：统一入口由 Router 决策并分发到 NoteWriter/QARAG
            script = os.path.join(self._root, 'scripts', 'run_team_interactive.py')
            if not os.path.exists(script):
                raise ValueError(f"脚本不存在: {script}")
            # 选择 Team 配置：优先使用传入的 _cfg 若位于 teams 目录，否则回退到默认 team_notes_master.json
            team_cfg = self._cfg
            try:
                if not team_cfg or ('/teams/' not in team_cfg.replace('\\', '/')):
                    team_cfg = os.path.join(self._root, 'config', 'teams', 'team_notes_master.json')
            except Exception:
                team_cfg = os.path.join(self._root, 'config', 'teams', 'team_notes_master.json')
            if not os.path.exists(team_cfg):
                raise ValueError(f"团队配置不存在: {team_cfg}")
            # 基础命令：单轮、超时、加载 .env（对齐终端：强制 UTF-8 无缓冲）
            cmd = [
                sys.executable,
                '-X', 'utf8', '-u',
                script,
                '--team-json', team_cfg,
                '--max-rounds', '1',
                '--timeout', '180',
                '--env-file', os.path.join(self._root, '.env'),
            ]
            # 透传议题ID/名称与附件（从构造参数获取）
            try:
                if isinstance(self._topic_id, str) and self._topic_id.strip():
                    cmd += ['--topic-id', self._topic_id.strip()]
                if isinstance(self._topic_name, str) and self._topic_name.strip():
                    cmd += ['--topic-name', self._topic_name.strip()]
                if isinstance(self._attachments, list) and self._attachments:
                    joined = ";".join([str(p) for p in self._attachments if isinstance(p, str) and p.strip()])
                    if joined:
                        cmd += ['--attachments', joined]
            except Exception:
                pass
            # 终端诊断（模块前缀为 NOTES 表示来源于笔记页，不代表“笔记模式”）
            try:
                print(f"[NOTES] external run start | cwd={self._root}")
                print(f"[NOTES] cmd={' '.join(cmd)}")
                # 输出当前 UI 模式，避免误解（使用构造时捕获的 ui_mode）
                print(f"[NOTES] prompt_len={len(self._prompt)} policy={self._policy} ui_mode={self._ui_mode}")
            except Exception:
                pass
            # 强制子进程使用 UTF-8，避免 Windows 控制台 GBK 编码错误
            env = dict(os.environ)
            env.setdefault('PYTHONIOENCODING', 'utf-8')
            env.setdefault('PYTHONUNBUFFERED', '1')
            # 议题信息也写入环境变量，便于问答路径在后端统一注入 note_topic_* 元数据
            try:
                if isinstance(self._topic_id, str) and self._topic_id.strip():
                    env['NOTE_TOPIC_ID'] = self._topic_id.strip()
                if isinstance(self._topic_name, str) and self._topic_name.strip():
                    env['NOTE_TOPIC_NAME'] = self._topic_name.strip()
            except Exception:
                pass
            # 使用 subprocess.run 简化交互，避免管道读阻塞；一次性输入并获取输出
            start_ts = time.time()
            try:
                single_line = " ".join((self._prompt or "").split())
                stdin_text = single_line + "\n:quit\n"
                result = subprocess.run(
                    cmd,
                    cwd=self._root,
                    input=stdin_text,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=180,
                    env=env,
                )
                out = (result.stdout or "")
                rc = result.returncode
                # 打印 stderr 末尾若干行，便于诊断（仅日志，不影响展示）
                try:
                    err = result.stderr or ""
                    if err.strip():
                        lines = [l for l in err.splitlines() if l.strip()]
                        tail = "\n".join(lines[-30:]) if lines else err
                        print(f"[NOTES][DIAG][stderr-tail]\n{tail}")
                except Exception:
                    pass
            except subprocess.TimeoutExpired:
                rc = None
                out = "执行超时：外部脚本在 120 秒内无完整输出，已终止。\n- 请检查模型/网络/向量召回耗时\n- 或提高超时阈值"
            except Exception as e:
                rc = -1
                out = f"运行失败：{e}"
            dur = time.time() - start_ts
            try:
                print(f"[NOTES] external run done | rc={rc} | dur={dur:.2f}s")
            except Exception:
                pass
            content = self._strip_ansi(self._parse_output(out))
            self.finished.emit(content)
        except Exception as e:
            try:
                print(f"[NOTES] external run failed: {e}")
            except Exception:
                pass
            self.failed.emit(f"外部脚本运行失败: {e}")

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget,
    QTextBrowser, QCheckBox, QDialog, QComboBox, QLabel
)


class _ReturnableTextEdit(QTextEdit):
    """多行文本框：
    - Enter 提交（发出 returnPressed 信号）
    - Shift+Enter 插入换行
    - 自动换行启用
    """
    returnPressed = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # 自动换行
            self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.setWordWrapMode(self.wordWrapMode())
        except Exception:
            pass

    def keyPressEvent(self, e: QKeyEvent):
        try:
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                if e.modifiers() & Qt.ShiftModifier:
                    # Shift+Enter -> 换行
                    self.insertPlainText("\n")
                    return
                # Enter -> 提交
                self.returnPressed.emit()
                return
        except Exception:
            pass
        return super().keyPressEvent(e)


class MarkdownEditor(QWidget):
    """带工具栏的 Markdown 编辑器：
    - 上方工具栏：加粗/斜体/标题/列表/代码/链接/预览
    - 中部堆叠：编辑区(_ReturnableTextEdit) 与 预览区(QTextBrowser)
    - 暴露 returnPressed 信号（来自编辑区）
    """
    returnPressed = Signal()

    def __init__(self, placeholder: str = ""):
        super().__init__()
        self._stack = QStackedWidget()
        self.editor = _ReturnableTextEdit()
        self.preview = QTextBrowser()
        try:
            self.editor.setPlaceholderText(placeholder)
        except Exception:
            pass
        self._stack.addWidget(self.editor)
        self._stack.addWidget(self.preview)

        # 工具栏（精简图标按钮）
        from PySide6.QtWidgets import QToolButton
        bar = QWidget(); bar_l = QHBoxLayout(bar); bar_l.setContentsMargins(0,0,0,0)
        def _btn(txt: str, tip: str, cb):
            b = QToolButton(); b.setText(txt); b.setToolTip(tip); b.setAutoRaise(True)
            b.setFixedSize(26, 26); b.clicked.connect(cb); return b
        bar_l.addWidget(_btn("𝐁", "加粗", lambda: self._wrap('**','**')))
        bar_l.addWidget(_btn("𝑰", "斜体", lambda: self._wrap('*','*')))
        bar_l.addWidget(_btn("#", "H1", lambda: self._prefix('# ')))
        bar_l.addWidget(_btn("##", "H2", lambda: self._prefix('## ')))
        bar_l.addWidget(_btn("•", "列表", lambda: self._prefix('- ')))
        bar_l.addWidget(_btn("</>", "代码块", lambda: self._wrap('```\n','\n```')))
        bar_l.addWidget(_btn("🔗", "链接", lambda: self._insert('[text](url)')))
        self._btn_preview = _btn("👁", "预览/编辑切换", self._toggle_preview)
        bar_l.addStretch(1)
        bar_l.addWidget(self._btn_preview)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lay.addWidget(bar)
        lay.addWidget(self._stack)

        # 转发回车信号
        try:
            self.editor.returnPressed.connect(self.returnPressed.emit)
        except Exception:
            pass

    def _toggle_preview(self):
        try:
            if self._stack.currentWidget() is self.editor:
                self.preview.setMarkdown(self.editor.toPlainText())
                self._stack.setCurrentWidget(self.preview)
                self._btn_preview.setText('编辑')
            else:
                self._stack.setCurrentWidget(self.editor)
                self._btn_preview.setText('预览')
        except Exception:
            pass

    def _wrap(self, left: str, right: str):
        c = self.editor.textCursor();
        if c.hasSelection():
            sel = c.selectedText().replace('\u2029', '\n')
            c.insertText(f"{left}{sel}{right}")
        else:
            c.insertText(f"{left}{right}");
            c.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, len(right))
            self.editor.setTextCursor(c)

    def _prefix(self, prefix: str):
        c = self.editor.textCursor();
        c.movePosition(QTextCursor.StartOfLine)
        c.insertText(prefix)

    def _insert(self, text: str):
        self.editor.insertPlainText(text)

    # 对外方法
    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, s: str):
        self.editor.setPlainText(s or '')

    def insert_text(self, s: str):
        self.editor.insertPlainText(s or '')

    def clear(self):
        self.editor.clear()

    def focus_editor(self):
        try:
            self.editor.setFocus()
        except Exception:
            pass

    # 兼容外部调用：转发占位符设置
    def setPlaceholderText(self, text: str):
        try:
            self.editor.setPlaceholderText(text or '')
        except Exception:
            pass


class MainWindow(QWidget):
    """重构后的主窗口类"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(UIConfig.MAIN_WINDOW_TITLE)
        self.resize(*UIConfig.MAIN_WINDOW_SIZE)
        self.setMinimumSize(*UIConfig.MAIN_WINDOW_MIN_SIZE)
        # 默认最大化打开主窗口
        try:
            self.setWindowState(Qt.WindowState.WindowMaximized)
        except Exception:
            pass
        # 设置全局字体为支持中文的字体
        try:
            QApplication.setFont(QFont("Microsoft YaHei UI", 9))
        except Exception:
            pass
        # 初始化服务与日志器
        self.model_service = ModelService()
        self.agent_service = AgentService()
        self.logger = ErrorHandler.setup_logging("main_window")
        # 配置服务（DB已禁用）
        self.config_service = None
        # 初始化状态并构建UI
        self._init_state()
        self._setup_ui()
        try:
            self.logger.info("主窗口初始化完成")
        except Exception:
            pass

    def _toggle_notes_mode(self):
        """快捷切换模式：note -> qa -> debug -> note"""
        try:
            cur = getattr(self, "_notes_mode", "note")
            nxt = "qa" if cur == "note" else ("debug" if cur == "qa" else "note")
            self._set_notes_mode(nxt)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            # 仅拦截“笔记”编辑器内的 Shift+Enter/Return
            if obj is getattr(self, "_notes_editor", None) and event.type() == QEvent.Type.KeyPress:
                key = event.key()
                mods = event.modifiers()
                if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)) and (mods & Qt.KeyboardModifier.ShiftModifier):
                    self._on_notes_execute()
                    return True
            return super().eventFilter(obj, event)
        except Exception:
            return super().eventFilter(obj, event)
    
    def _init_state(self):
        """初始化状态变量"""
        # 运行状态
        self._agent_running: bool = False
        self._agent_thread: Optional[QThread] = None
        self._agent_worker: Optional[AgentInferWorker] = None
        self._script_thread: Optional[QThread] = None
        self._script_worker: Optional[ScriptInferWorker] = None
        
        # 数据状态
        self.model_data: Optional[Dict[str, Any]] = None
        self.backend: Optional[AgentBackend] = None
        self._model_saved_system_prompt: str = ""
        
        self.agent_cfg: Optional[Dict[str, Any]] = None
        self.agent_backend: Optional[AutogenAgentBackend] = None
        self._agent_saved_system_message: str = ""
        
        self.team_cfg: Optional[Dict[str, Any]] = None
        self.team_backend: Optional[AutogenTeamBackend] = None
        
        # UI状态
        self._agent_tools_mode: str = "mounted"
        self._agent_tools_type: str = "tool"
        # 运行期配置来源：local=本地Agent配置，memory=内存生成配置
        try:
            self._exec_config_source: str = 'local'
            # 约定的内存配置产物路径（若 on_generate_mem_agent_config 内已有设置将覆盖）
            temp_dir = Paths.get_absolute_path('temp') if hasattr(Paths, 'get_absolute_path') else ROOT / 'temp'
            self._mem_agent_config_path: str = str((temp_dir / 'agent_mem_config.json') if hasattr(temp_dir, 'joinpath') else os.path.join(temp_dir, 'agent_mem_config.json'))
        except Exception:
            self._exec_config_source = 'local'
            self._mem_agent_config_path = os.path.join(os.getcwd(), 'temp', 'agent_mem_config.json')
        # 笔记附件列表（UI 维护，提交时透传给脚本）
        try:
            self._notes_attachments: list[str] = []
        except Exception:
            self._notes_attachments = []

    def _get_runtime_agent_cfg(self):
        """根据 _exec_config_source 返回运行期 Agent 配置（dict）。
        - memory 且文件存在：读取 temp/agent_mem_config.json
        - 否则：返回 self.agent_data 的深拷贝
        失败时回退到 local。
        """
        try:
            import copy
            src = getattr(self, '_exec_config_source', 'local')
            mem_path = getattr(self, '_mem_agent_config_path', '')
            
            # 调试输出当前配置来源
            try:
                print(f"[DEBUG] 当前配置来源: {src}, 内存路径存在: {os.path.exists(mem_path) if mem_path else False}")
            except Exception:
                pass
                
            if src == 'memory' and mem_path and os.path.exists(mem_path):
                try:
                    with open(mem_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # 输出调试信息
                    try:
                        print(f"[DEBUG] 已读取内存配置: {mem_path}")
                        self.logger.info(f"已读取内存配置: {mem_path}")
                    except Exception:
                        pass
                    # 仅返回内存文件内容，不写回 self.agent_data
                    return data if isinstance(data, dict) else {}
                except Exception as e:
                    try:
                        self.logger.warning(f"读取内存配置失败，回退本地: {e}")
                    except Exception:
                        pass
                    self._exec_config_source = 'local'
            # 回退本地
            base_cfg = getattr(self, 'agent_data', None)
            if isinstance(base_cfg, dict):
                # 输出调试信息
                try:
                    print(f"[DEBUG] 使用本地Agent配置: {base_cfg.get('name', '未命名')}")
                    self.logger.info(f"使用本地Agent配置: {base_cfg.get('name', '未命名')}")
                except Exception:
                    pass
                try:
                    return copy.deepcopy(base_cfg)
                except Exception:
                    return json.loads(json.dumps(base_cfg, ensure_ascii=False))
            return {}
        except Exception as e:
            try:
                self.logger.warning(f"_get_runtime_agent_cfg 失败: {e}")
            except Exception:
                pass
            return {}
    
    def _setup_ui(self):
        """设置用户界面"""
        layout = QVBoxLayout(self)
        
        # 创建选项卡
        self.tabs = QTabWidget()
        
        # Model页面
        self._create_model_tab()
        
        # Agent页面  
        self._create_agent_tab()
        
        # Team页面
        self._create_team_tab()
        
        # Warehouse页面
        self._create_warehouse_tab()

        # 向量库（顶级）页面
        self._create_vectorstores_top_tab()

        # 新增：设置页面（系统设置占位）
        self._create_settings_tab()

        # 新增：Project 页面（项目管理占位）
        self._create_project_tab()
        
        # 新增：配置浏览器页面
        self._create_config_explorer_tab()

        # 新增：笔记页面（简单文本笔记）
        self._create_notes_tab()

        # 新增：配置生成器页面（配置即功能）
        self._create_project_config_generator_tab()

        # 新增：向量内存调试页面
        self._create_vector_memory_debug_tab()
        
        layout.addWidget(self.tabs)

    def _on_notes_add_attachments(self):
        try:
            from PySide6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(self, "选择附件（多选）", "", "Documents (*.txt *.md *.pdf *.docx);;All Files (*.*)")
            if not files:
                return
            if not hasattr(self, '_notes_attachments'):
                self._notes_attachments = []
            added = 0
            for f in files:
                fp = str(f).strip()
                if not fp:
                    continue
                if fp not in self._notes_attachments:
                    self._notes_attachments.append(fp)
                    added += 1
                    try:
                        self._attachments_list.addItem(fp)
                    except Exception:
                        pass
            try:
                print(f"[NOTES][UI] 附件添加: {added} 新增, 总数={len(self._notes_attachments)}")
            except Exception:
                pass
        except Exception as e:
            try:
                print(f"[NOTES][UI] 添加附件失败: {e}")
            except Exception:
                pass

    def _on_notes_remove_selected_attachment(self):
        try:
            if not hasattr(self, '_attachments_list') or self._attachments_list is None:
                return
            items = self._attachments_list.selectedItems()
            if not items:
                return
            removed = 0
            for it in items:
                path = it.text()
                try:
                    row = self._attachments_list.row(it)
                    self._attachments_list.takeItem(row)
                except Exception:
                    pass
                try:
                    if hasattr(self, '_notes_attachments') and path in self._notes_attachments:
                        self._notes_attachments.remove(path)
                        removed += 1
                except Exception:
                    pass
            try:
                print(f"[NOTES][UI] 附件移除: {removed} 项, 剩余={len(getattr(self, '_notes_attachments', []))}")
            except Exception:
                pass
        except Exception:
            pass

        # 顶部右上角：设置“默认一级标签”开关（采用头部行，确保可见）
        try:
            self.chk_default_top = QCheckBox("默认")
            self.chk_default_top.setToolTip("将当前一级选项卡设为下次启动默认打开")
            self.chk_default_top.stateChanged.connect(self._on_top_default_toggled)
            # 显式头部栏：将复选框放入 tabs 上方一行
            header_row = QHBoxLayout()
            header_row.addStretch(1)
            # 新增：笔记/问答按钮，位于“默认”开关左侧
            self.btn_notes = QPushButton("笔记")
            self.btn_notes.setToolTip("进入『笔记』模式并打开『笔记』选项卡")
            header_row.addWidget(self.btn_notes)
            self.btn_notes_qa = QPushButton("问答")
            self.btn_notes_qa.setToolTip("进入『问答』模式并打开『笔记』选项卡")
            header_row.addWidget(self.btn_notes_qa)
            header_row.addWidget(self.chk_default_top)
            # 插入到 tabs 之前
            try:
                idx = layout.indexOf(self.tabs)
                if idx >= 0:
                    layout.insertLayout(idx, header_row)
                else:
                    layout.insertLayout(0, header_row)
            except Exception:
                layout.insertLayout(0, header_row)
            # 切换一级Tab时：若已勾选默认，则持久化当前索引；同时同步开关状态
            self.tabs.currentChanged.connect(self._on_top_tab_changed)
            # 点击“笔记/问答”按钮 -> 激活“笔记”选项卡并切换模式
            try:
                self.btn_notes.clicked.connect(self._activate_notes_tab)
                self.btn_notes_qa.clicked.connect(self._activate_notes_tab_qa)
            except Exception:
                pass
        except Exception:
            pass

    def _create_project_config_generator_tab(self):
        """创建“配置生成器”选项卡：可视化生成/编辑项目配置。"""
        try:
            page = ProjectConfigGeneratorPage(self)
            self.tabs.addTab(page, "向量库")
        except Exception as e:
            try:
                self._diag_log(f"创建配置生成器页失败: {e}")
            except Exception:
                pass

        # 恢复默认一级Tab
        try:
            self._restore_default_top_tab()
        except Exception:
            pass

        # 诊断：记录窗口初始化完成
        try:
            self._diag_log("MainWindow initialized")
        except Exception:
            pass

    def _create_vector_memory_debug_tab(self):
        """创建“向量内存调试”选项卡。
        仅做UI与配置预检，不引入自定义检索管线；后续将接入 Autogen 内生 Memory 冒烟测试。
        """
        try:
            page = VectorMemoryDebugPage(self)
            self.tabs.addTab(page, "向量内存")
        except Exception as e:
            try:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.warning(f"[VectorMemoryDebug] 初始化失败: {e}")
            except Exception:
                pass

    def _create_notes_tab(self):
        """（已下线）不再创建『笔记』选项卡。"""
        try:
            # 明确不创建“笔记”页，保持静默以兼容现有调用链。
            self._notes_tab_index = -1
            if hasattr(self, 'logger') and self.logger:
                self.logger.info("[NotesUI] 笔记页面已下线（未创建Tab）")
        except Exception:
            pass

    def _activate_notes_tab(self):
        """（已下线）笔记页不再可用。"""
        try:
            if hasattr(self, 'logger') and self.logger:
                self.logger.info("[NotesUI] _activate_notes_tab 调用被忽略（页面已下线）")
        except Exception:
            pass

    def _activate_notes_tab_qa(self):
        """（已下线）笔记页不再可用。"""
        try:
            if hasattr(self, 'logger') and self.logger:
                self.logger.info("[NotesUI] _activate_notes_tab_qa 调用被忽略（页面已下线）")
        except Exception:
            pass

    def _set_notes_mode(self, mode: str):
        """设置笔记页模式："note" | "qa" | "debug"，并更新标题/按钮样式。"""
        try:
            if mode not in ("note", "qa", "debug"):
                mode = "note"
            self._notes_mode = mode
            # 更新标题
            try:
                if hasattr(self, "_notes_title_label") and self._notes_title_label is not None:
                    if mode == "qa":
                        txt = "笔记（问答模式）"
                    elif mode == "debug":
                        txt = "笔记（调试模式）"
                    else:
                        txt = "笔记（笔记模式）"
                    self._notes_title_label.setText(txt)
            except Exception:
                pass
            # 更新三枚模式徽标的样式
            try:
                def _style(active_bg, active_bd, active_fg):
                    return (
                        "border-radius:6px;padding:2px 10px;font-size:11px;"
                        f"color:{active_fg};background:{active_bg};border:1px solid {active_bd};"
                    )
                def _style_inactive():
                    return (
                        "border-radius:6px;padding:2px 10px;font-size:11px;"
                        "color:#6b7280;background:#f3f4f6;border:1px dashed #d1d5db;"
                    )
                if hasattr(self, "_badge_note"):
                    self._badge_note.setStyleSheet(_style("#bcd8cc", "#8fc2ad", "#0f5132") if mode=="note" else _style_inactive())
                if hasattr(self, "_badge_qa"):
                    self._badge_qa.setStyleSheet(_style("#b7e4c7", "#95d5b2", "#0f5132") if mode=="qa" else _style_inactive())
                if hasattr(self, "_badge_debug"):
                    self._badge_debug.setStyleSheet(_style("#b6d4fe", "#9ec5fe", "#084298") if mode=="debug" else _style_inactive())
            except Exception:
                pass
            # 更新按钮视觉（高亮当前模式）
            try:
                if hasattr(self, "btn_notes") and self.btn_notes is not None:
                    self.btn_notes.setStyleSheet("font-weight:{};".format("700" if mode == "note" else "400"))
                if hasattr(self, "btn_notes_qa") and self.btn_notes_qa is not None:
                    self.btn_notes_qa.setStyleSheet("font-weight:{};".format("700" if mode == "qa" else "400"))
            except Exception:
                pass
        except Exception:
            pass

    def _toggle_notes_polling(self):
        try:
            self._notes_polling_enabled = not getattr(self, "_notes_polling_enabled", False)
            if hasattr(self, "_badge_poll") and self._badge_poll is not None:
                if self._notes_polling_enabled:
                    self._badge_poll.setText("轮训:开")
                    self._badge_poll.setStyleSheet(
                        "border-radius:6px;padding:2px 8px;font-size:11px;"
                        "color:#0f5132;background:#ffe69c;border:1px solid #ffda6a;"
                    )
                else:
                    self._badge_poll.setText("轮训:关")
                    self._badge_poll.setStyleSheet(
                        "border-radius:6px;padding:2px 8px;font-size:11px;"
                        "color:#6b7280;background:#f3f4f6;border:1px dashed #d1d5db;"
                    )
            try:
                print(f"[NOTES][UI] polling_toggle -> {self._notes_polling_enabled}")
            except Exception:
                pass
        except Exception:
            pass

    def _on_notes_save_local(self):
        """将『笔记』编辑区内容保存到本地文件。"""
        try:
            text = ""
            try:
                if hasattr(self, "_notes_editor") and self._notes_editor is not None:
                    text = self._notes_editor.toPlainText() or ""
            except Exception:
                text = ""
            if not text:
                QMessageBox.information(self, "提示", "没有可保存的内容。")
                return
            path, _ = QFileDialog.getSaveFileName(self, "保存笔记到本地", "", "Text/Markdown (*.txt *.md);;All Files (*.*)")
            if not path:
                return
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            QMessageBox.information(self, "完成", f"已保存：{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")

    # ---------- 笔记页：执行与快捷键 ----------
    def _on_notes_execute(self):
        try:
            ed = getattr(self, "_notes_editor", None)
            sys_ed = getattr(self, "_notes_sys_editor", None)
            if ed is None:
                return
            text = ed.toPlainText() or ""
            sys_msg = sys_ed.toPlainText() if sys_ed is not None else ""
            if not text.strip():
                QMessageBox.information(self, "提示", "请输入内容后再执行。")
                return
            mode = getattr(self, "_notes_mode", "note")
            # 统一：所有模式均走外部脚本；仅通过 policy 控制是否写库
            # - note: qa_user_only（只写用户，不要回答也允许回答，但UI以保存提示为主）
            # - qa:   qa_both（问答都写库）
            # - debug: qa_none（不写库）
            if mode == "qa":
                policy = "qa_both"
            elif mode == "debug":
                policy = "qa_none"
            else:
                policy = "qa_user_only"
            # 将系统提示词并入首行（外部脚本不支持额外传参，采用内容前缀注入）
            payload = text
            # 方案A：在“笔记模式”下，若未显式以“#笔记”开头，则自动加上前缀以命中路由规则
            try:
                if mode == "note":
                    _t = (payload or "").lstrip()
                    if not _t.startswith("#笔记"):
                        payload = "#笔记 " + (payload or "").lstrip()
            except Exception:
                pass
            # 若为问答模式且没有填写系统提示词，注入一个默认的记忆优先指令
            if mode == "qa" and not (sys_msg or "").strip():
                sys_msg = (
                    "你是一个严格遵循指令的助手。\n"
                    "【回答目标】必须直接回答用户当前问题本身，不要偏题或仅复述不相关记忆。\n"
                    "【记忆使用准则】仅当召回片段与问题高度相关时才使用（例如语义相似、或明显包含所问概念/定义/实体）；"
                    "若召回内容与问题相关性不足或不能直接支持作答，请忽略召回，转为常规推理作答。\n"
                    "【综合策略】优先利用高相关记忆作答；必要时可补充常识/工具结果，但最终必须围绕问题给出明确、完整的答案。\n"
                    "【输出要求】用简洁的中文直接回答；如有引用的记忆要点，可自然融合在答案中，不必原样逐条罗列。"
                )
            if (sys_msg or "").strip():
                payload = f"[系统提示]\n{sys_msg.strip()}\n\n{payload}"
            root_dir = str(ROOT)
            cfg_path = getattr(self, "_notes_agent_cfg_path", "")
            if not cfg_path:
                cfg_path = str(ROOT / 'config' / 'agents' / '笔记助理.json')
            # UI提示：执行中
            try:
                viewer = getattr(self, "_notes_viewer", None)
                if viewer is not None:
                    mode_label = "问答" if mode=="qa" else ("调试" if mode=="debug" else "笔记")
                    viewer.setMarkdown("⌛ 正在执行外部脚本…请稍候\n\n- 模式: {}\n- 策略: {}".format(mode_label, policy))
            except Exception:
                pass
            # 锁定预览，防止编辑器 textChanged 覆盖右侧
            try:
                self._notes_preview_locked = True
            except Exception:
                pass
            try:
                print(f"[NOTES][UI] dispatch external worker | mode={mode} policy={policy}")
                print(f"[NOTES][UI] cfg={cfg_path}")
            except Exception:
                pass
            self._notes_script_thread = QThread(self)
            _cur_mode = mode
            # 收集上下文信息，避免在 worker 内部访问 parent()
            _topic_id = getattr(self, '_note_topic_id', None)
            _topic_name = getattr(self, '_note_topic_name', None)
            _attachments = getattr(self, '_notes_attachments', [])
            self._notes_script_worker = NotesScriptWorker(
                root_dir, cfg_path, payload,
                force_policy=policy, ui_mode=_cur_mode,
                topic_id=_topic_id, topic_name=_topic_name, attachments=_attachments,
            )
            self._notes_script_worker.moveToThread(self._notes_script_thread)
            self._notes_script_thread.started.connect(self._notes_script_worker.run)
            self._notes_script_worker.finished.connect(self._on_notes_script_finished)
            self._notes_script_worker.failed.connect(self._on_notes_failed)
            # 清理
            self._notes_script_worker.finished.connect(self._notes_script_thread.quit)
            self._notes_script_worker.finished.connect(self._notes_script_worker.deleteLater)
            self._notes_script_thread.finished.connect(self._notes_script_thread.deleteLater)
            self._notes_script_thread.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行失败：{e}")

    def _on_notes_shortcut(self):
        # Ctrl+Enter：按当前模式执行
        self._on_notes_execute()

    def _on_notes_shortcut_qa(self):
        # Alt+Enter：切到问答并执行
        try:
            self._set_notes_mode("qa")
        except Exception:
            pass
        self._on_notes_execute()

    @Slot(str)
    def _on_notes_ask_finished(self, reply: str):
        try:
            viewer = getattr(self, "_notes_viewer", None)
            if viewer is not None:
                # 直接展示回答
                viewer.setMarkdown(str(reply or ""))
        except Exception:
            pass

    @Slot(str)
    def _on_notes_script_finished(self, reply: str):
        try:
            try:
                print(f"[NOTES][UI] finished | reply_len={len(reply or '')}")
            except Exception:
                pass
            # 解锁预览
            try:
                self._notes_preview_locked = False
            except Exception:
                pass
            viewer = getattr(self, "_notes_viewer", None)
            if viewer is not None:
                viewer.setMarkdown(str(reply or ""))
        except Exception:
            pass

    @Slot(str)
    def _on_notes_record_finished(self, summary: str):
        try:
            viewer = getattr(self, "_notes_viewer", None)
            if viewer is not None:
                viewer.setMarkdown(f"**已保存到向量库**\n\n{summary}")
        except Exception:
            pass

    @Slot(str)
    def _on_notes_failed(self, err: str):
        try:
            try:
                print(f"[NOTES][UI] failed: {err}")
            except Exception:
                pass
            try:
                self._notes_preview_locked = False
            except Exception:
                pass
            QMessageBox.critical(self, "错误", err)
        except Exception:
            pass

    def _on_notes_recall(self):
        try:
            ed = getattr(self, "_notes_editor", None)
            if ed is None:
                return
            query = ed.toPlainText() or ""
            if not query.strip():
                QMessageBox.information(self, "提示", "请输入查询内容后再回忆。")
                return
            self._notes_recall_thread = QThread(self)
            self._notes_recall_worker = NotesRecallWorker(self._notes_service, query, k=8)
            self._notes_recall_worker.moveToThread(self._notes_recall_thread)
            self._notes_recall_thread.started.connect(self._notes_recall_worker.run)
            self._notes_recall_worker.finished.connect(self._on_notes_recall_finished)
            self._notes_recall_worker.failed.connect(self._on_notes_failed)
            # 清理
            self._notes_recall_worker.finished.connect(self._notes_recall_thread.quit)
            self._notes_recall_worker.finished.connect(self._notes_recall_worker.deleteLater)
            self._notes_recall_thread.finished.connect(self._notes_recall_thread.deleteLater)
            self._notes_recall_thread.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"回忆失败：{e}")

    @Slot(list)
    def _on_notes_recall_finished(self, items: List[dict]):
        try:
            viewer = getattr(self, "_notes_viewer", None)
            if viewer is None:
                return
            lines: List[str] = ["**召回片段（按相似度）**\n"]
            if not items:
                lines.append("_无结果_\n")
            else:
                for it in items:
                    content = str(it.get("content", ""))
                    score = it.get("score")
                    md = it.get("metadata") or {}
                    score_part = f" (score={score:.3f})" if isinstance(score, (int, float)) else ""
                    # 元数据简要
                    scene = md.get("scene") if isinstance(md, dict) else None
                    role = md.get("role") if isinstance(md, dict) else None
                    meta_part = []
                    if scene: meta_part.append(f"scene={scene}")
                    if role: meta_part.append(f"role={role}")
                    meta_str = f" [{' ,'.join(meta_part)}]" if meta_part else ""
                    snippet = content.strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "..."
                    lines.append(f"- {snippet}{score_part}{meta_str}")
            viewer.setMarkdown("\n".join(lines))
        except Exception:
            pass

    # ---------- 笔记页：Markdown 编辑辅助与预览 ----------
    def _notes_wrap_selection(self, prefix: str, suffix: str):
        try:
            ed = getattr(self, "_notes_editor", None)
            if ed is None:
                return
            cursor = ed.textCursor()
            if not cursor.hasSelection():
                cursor.insertText(prefix + suffix)
                cursor.movePosition(cursor.Left, cursor.MoveAnchor, len(suffix))
                ed.setTextCursor(cursor)
                return
            selected = cursor.selectedText()
            cursor.insertText(prefix + selected + suffix)
        except Exception:
            pass

    def _notes_prefix_line(self, prefix: str):
        try:
            ed = getattr(self, "_notes_editor", None)
            if ed is None:
                return
            cursor = ed.textCursor()
            cursor.movePosition(cursor.StartOfLine)
            cursor.insertText(prefix)
        except Exception:
            pass

    def _notes_render_preview(self):
        try:
            # 执行期间不更新预览，避免覆盖问答结果/脚本输出
            if getattr(self, "_notes_preview_locked", False):
                return
            viewer = getattr(self, "_notes_viewer", None)
            ed = getattr(self, "_notes_editor", None)
            if viewer is None or ed is None:
                return
            md = ed.toPlainText() or ""
            # QTextBrowser/QTextEdit 支持简化 Markdown；作为占位预览
            try:
                viewer.setMarkdown(md)
            except Exception:
                viewer.setPlainText(md)
        except Exception:
            pass

    def _on_notes_upload_file(self):
        """从本地选择文件并写入当前向量库集合（使用 Autogen 内生 Memory）。"""
        try:
            # 选择文件
            src, _ = QFileDialog.getOpenFileName(self, "选择要上传的文本文件", "", "Text Files (*.txt *.md *.rst *.py *.json *.log);;All Files (*.*)")
            if not src:
                return
            # 目标向量库参数（交互式获取，提供默认值）
            persistence_path, ok1 = QInputDialog.getText(self, "向量库根目录", "persistence_path:", text="./data/autogen_official_memory/vector_demo/")
            if not ok1 or not persistence_path:
                return
            collection_name, ok2 = QInputDialog.getText(self, "集合名称", "collection_name:", text="vector_demo_assistant")
            if not ok2 or not collection_name:
                return
            # 读文件
            try:
                with open(src, 'r', encoding='utf-8') as f:
                    text = f.read()
            except Exception:
                with open(src, 'r', encoding='gbk', errors='ignore') as f:
                    text = f.read()
            if not text.strip():
                QMessageBox.information(self, "提示", "文件为空或无法读取有效文本。")
                return
            # 惰性导入 Autogen 内存组件，避免顶层触发 onnxruntime
            try:
                from autogen_core.memory import MemoryContent, MemoryMimeType  # type: ignore
                from autogen_ext.memory.chromadb import (  # type: ignore
                    ChromaDBVectorMemory,
                    PersistentChromaDBVectorMemoryConfig,
                    SentenceTransformerEmbeddingFunctionConfig,
                    DefaultEmbeddingFunctionConfig,
                )
            except Exception as e:
                QMessageBox.warning(self, "提示", f"Autogen Memory 组件不可用：{e}")
                return
            # 构建默认嵌入
            ef_cfg = SentenceTransformerEmbeddingFunctionConfig(model_name="all-MiniLM-L6-v2")
            mem = ChromaDBVectorMemory(
                config=PersistentChromaDBVectorMemoryConfig(
                    collection_name=collection_name,
                    persistence_path=persistence_path,
                    k=8,
                    score_threshold=0.25,
                    allow_reset=False,
                    tenant="default_tenant",
                    database="default_database",
                    distance_metric="cosine",
                    embedding_function_config=ef_cfg,
                )
            )
            # 切块 + 写入
            def _chunks(s: str, size: int = 800, overlap: int = 80):
                if size <= 0:
                    yield s
                    return
                i, n = 0, len(s)
                while i < n:
                    end = min(i + size, n)
                    yield s[i:end]
                    if end >= n:
                        break
                    i = max(0, end - overlap)
            import asyncio
            async def _run():
                added = 0
                for j, blk in enumerate(_chunks(text)):
                    content = MemoryContent(
                        content=blk,
                        mime_type=MemoryMimeType.TEXT,
                        metadata={"source": src, "chunk": j, "category": "kb_doc"},
                    )
                    await mem.add(content)
                    added += 1
                await mem.close()
                return added
            added = asyncio.run(_run())
            QMessageBox.information(self, "完成", f"已上传到集合：{collection_name}，新增块数：{added}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"上传失败：{e}")

    def _create_vectorstores_top_tab(self):
        """创建顶级“向量库”页面（三栏结构，对齐 Agent 页样式）。"""
        try:
            # 延迟导入，避免模块加载次序问题
            from ui.pages.vectorstores.top_level import VectorStoresTopLevelPage
            page = VectorStoresTopLevelPage(self)
            self.tabs.addTab(page, "向量库")
        except Exception as e:
            # 兜底：显示错误占位，不影响其他页面
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.addWidget(QLabel(f"向量库 页面加载失败：{str(e)[:200]}"))
            self.tabs.addTab(widget, "向量库")

    # 诊断辅助：统一打印与记录
    def _diag_log(self, msg: str):
        try:
            text = f"[DIAG] {msg}"
            try:
                print(text)
            except Exception:
                pass
            try:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.info(text)
            except Exception:
                pass
        except Exception:
            pass

    # 诊断辅助：线程状态快照
    def _log_thread_states(self, context: str):
        try:
            at = getattr(self, '_agent_thread', None)
            st = getattr(self, '_script_thread', None)
            a_state = f"exists={bool(at)} running={(at.isRunning() if at else False)}" if at is not None else "exists=False"
            s_state = f"exists={bool(st)} running={(st.isRunning() if st else False)}" if st is not None else "exists=False"
            self._diag_log(f"ThreadStates@{context}: agent_thread[{a_state}] | script_thread[{s_state}]")
        except Exception:
            pass

    # ---------- 一级Tab默认开关/持久化（MainWindow） ----------
    def _settings(self) -> QSettings:
        try:
            return QSettings("NeuralAgent", "DesktopApp")
        except Exception:
            return QSettings()

    def _restore_default_top_tab(self):
        """恢复一级Tab：优先 default → 其次 last → 否则第一个。
        仅设置UI状态，不写入设置。
        """
        try:
            s = self._settings()
            idx = s.value("main_window/default_top_tab_index")
            if isinstance(idx, str) and idx.isdigit():
                idx = int(idx)
            # 1) 首选默认索引
            if isinstance(idx, int) and 0 <= idx < self.tabs.count():
                self.tabs.setCurrentIndex(int(idx))
            else:
                # 2) 回退最近一次索引
                last = s.value("main_window/last_top_tab_index")
                if isinstance(last, str) and last.isdigit():
                    last = int(last)
                if isinstance(last, int) and 0 <= last < self.tabs.count():
                    self.tabs.setCurrentIndex(int(last))
                else:
                    # 3) 最后回退第一个
                    if self.tabs.count() > 0:
                        self.tabs.setCurrentIndex(0)
            # 恢复后同步勾选状态
            self._sync_top_default_checkbox()
        except Exception:
            pass

    def _on_top_default_toggled(self, state: int):
        """勾选“默认”时保存当前索引为 default；取消时移除 default。"""
        try:
            s = self._settings()
            if state == Qt.CheckState.Checked:
                cur = self.tabs.currentIndex()
                s.setValue("main_window/default_top_tab_index", int(cur))
            else:
                # 取消默认：清除配置键
                try:
                    s.remove("main_window/default_top_tab_index")
                except Exception:
                    # 兼容性回退：写入 -1
                    s.setValue("main_window/default_top_tab_index", -1)
            try:
                s.sync()
            except Exception:
                pass
            self._sync_top_default_checkbox()
        except Exception:
            pass

    def _sync_top_default_checkbox(self):
        """根据当前索引与保存的 default 同步复选框状态。"""
        try:
            s = self._settings()
            idx = s.value("main_window/default_top_tab_index")
            if isinstance(idx, str) and idx.isdigit():
                idx = int(idx)
            cur = self.tabs.currentIndex()
            if hasattr(self, 'chk_default_top'):
                try:
                    self.chk_default_top.blockSignals(True)
                    self.chk_default_top.setChecked(isinstance(idx, int) and idx == cur)
                finally:
                    try:
                        self.chk_default_top.blockSignals(False)
                    except Exception:
                        pass
        except Exception:
            try:
                if hasattr(self, 'chk_default_top'):
                    try:
                        self.chk_default_top.blockSignals(True)
                        self.chk_default_top.setChecked(False)
                    finally:
                        try:
                            self.chk_default_top.blockSignals(False)
                        except Exception:
                            pass
            except Exception:
                pass

    def _on_top_tab_changed(self, index: int):
        """当一级Tab变化时：总是记录 last；如勾选默认则写 default；最后同步勾选状态。"""
        try:
            s = self._settings()
            # 记录最近一次索引
            s.setValue("main_window/last_top_tab_index", int(index))
            try:
                s.sync()
            except Exception:
                pass
            # 如勾选默认，则写默认索引
            if hasattr(self, 'chk_default_top') and self.chk_default_top.isChecked():
                s.setValue("main_window/default_top_tab_index", int(index))
                try:
                    s.sync()
                except Exception:
                    pass
            self._sync_top_default_checkbox()
        except Exception:
            pass

    def _enable_enter_to_send(self, text_edit: QTextEdit, sender):
        """为 QTextEdit 安装 Enter 发送过滤器。"""
        try:
            if isinstance(text_edit, QTextEdit):
                filt = EnterToSendFilter(sender)
                # 保存引用避免被GC
                if not hasattr(self, '_enter_filters'):
                    self._enter_filters = []
                self._enter_filters.append(filt)
                # 安装事件过滤器
                text_edit.installEventFilter(filt)
                print(f"[DEBUG] 已为 {text_edit.__class__.__name__} 安装回车发送过滤器")
        except Exception as e:
            # 记录但不阻断主流程
            print(f"[DEBUG] 安装 Enter 事件过滤器失败: {e}")
            self.logger.warning(f"安装 Enter 事件过滤器失败: {e}")


    def _create_chat_area(self, parent_layout: QVBoxLayout):
        """在Model页左栏创建最小可用的对话区域（输入/输出/发送）。
        与 Agent 页分离，使用独立的控件避免相互覆盖。
        """
        try:
            if not isinstance(parent_layout, QVBoxLayout):
                return
            parent_layout.addWidget(QLabel("对话："))
            # 输出窗口（只读，置顶）
            self.model_chat_output = QTextEdit()
            self.model_chat_output.setReadOnly(True)
            self.model_chat_output.setMinimumHeight(140)
            parent_layout.addWidget(self.model_chat_output)

            # 输入窗口（置底）
            self.model_chat_input = QTextEdit()
            self.model_chat_input.setPlaceholderText("输入内容，Enter 发送，Shift+Enter 换行…")
            self.model_chat_input.setMinimumHeight(80)
            parent_layout.addWidget(self.model_chat_input)

            # 发送按钮行（保留Model页发送按钮）
            row = QHBoxLayout()
            btn_send = QPushButton("发送")
            try:
                btn_send.clicked.connect(self._on_model_send)
            except Exception:
                pass
            row.addStretch(1)
            row.addWidget(btn_send)
            parent_layout.addLayout(row)

            # 安装回车发送
            try:
                self._enable_enter_to_send(self.model_chat_input, self._on_model_send)
            except Exception:
                pass
        except Exception as e:
            self.logger.warning(f"创建对话区域失败: {e}")

    def _create_agent_chat_area(self, parent_layout: QVBoxLayout):
        """在Agent页左栏创建最小可用的对话区域（输入/输出/发送）。
        与 Model 页分离，使用独立的控件避免相互覆盖。
        """
        try:
            if not isinstance(parent_layout, QVBoxLayout):
                return
            parent_layout.addWidget(QLabel("对话："))
            
            # 输入窗口（置顶）- 使用支持回车发送的文本框
            self.agent_chat_input = _ReturnableTextEdit()
            self.agent_chat_input.setPlaceholderText("输入内容，Enter 发送，Shift+Enter 换行…")
            self.agent_chat_input.setMinimumHeight(80)
            # 连接回车发送信号
            self.agent_chat_input.returnPressed.connect(self._on_agent_send)
            parent_layout.addWidget(self.agent_chat_input)
            
            # 输出窗口（只读）
            self.agent_chat_output = QTextEdit()
            self.agent_chat_output.setReadOnly(True)
            self.agent_chat_output.setMinimumHeight(140)
            parent_layout.addWidget(self.agent_chat_output)
            
            # 复制按钮
            copy_btn_layout = QHBoxLayout()
            copy_btn_layout.addStretch()
            self.agent_copy_btn = QPushButton("复制输出")
            self.agent_copy_btn.clicked.connect(self._on_agent_copy_output)
            copy_btn_layout.addWidget(self.agent_copy_btn)
            parent_layout.addLayout(copy_btn_layout)

            # 回车发送已通过 _ReturnableTextEdit 的 returnPressed 信号连接，无需额外安装过滤器
        except Exception as e:
            self.logger.warning(f"Agent发送处理失败: {e}")

    def _on_agent_copy_output(self):
        """复制Agent输出框内容到剪贴板"""
        try:
            if hasattr(self, 'agent_chat_output') and self.agent_chat_output is not None:
                content = self.agent_chat_output.toPlainText()
                if content.strip():
                    from PySide6.QtWidgets import QApplication
                    clipboard = QApplication.clipboard()
                    clipboard.setText(content)
                    try:
                        from app.utils.error_handler import ErrorHandler
                        ErrorHandler.handle_success(self, "复制成功", "输出内容已复制到剪贴板")
                    except Exception:
                        pass
                else:
                    try:
                        from app.utils.error_handler import ErrorHandler
                        ErrorHandler.handle_warning(self, "提示", "输出框为空，无内容可复制")
                    except Exception:
                        pass
        except Exception as e:
            try:
                self.logger.warning(f"复制输出失败: {e}")
            except Exception:
                pass

    def _on_agent_send(self):
        """Agent页：发送一次对话，支持回车触发与按钮触发。"""
        try:
            # 读取输入
            if not hasattr(self, 'agent_chat_input') or not hasattr(self, 'agent_chat_output'):
                return
            user_text = self.agent_chat_input.toPlainText().strip()
            if not user_text:
                return
            
            # 清空输入框和输出框
            self.agent_chat_input.clear()
            self.agent_chat_output.clear()

            # 调试：记录当前配置源
            src = getattr(self, '_exec_config_source', 'local')
            try:
                print(f"[DEBUG] _on_agent_send: 当前配置来源={src}")
                self.logger.info(f"_on_agent_send: 当前配置来源={src}")
            except Exception:
                pass

            # 选择配置文件路径：优先运行“内存配置”，否则使用左侧浏览的本地文件；都没有时将当前运行期配置写入临时文件
            cfg_path = None
            try:
                if src == 'memory':
                    mem_path = getattr(self, '_mem_agent_config_path', None)
                    if mem_path and os.path.exists(mem_path):
                        cfg_path = mem_path
            except Exception:
                cfg_path = None
            if not cfg_path:
                try:
                    if hasattr(self, 'agent_path') and self.agent_path is not None:
                        _p = (self.agent_path.text() or '').strip()
                        if _p and os.path.exists(_p):
                            cfg_path = _p
                except Exception:
                    cfg_path = None
            if not cfg_path:
                # 若仍无有效路径，则基于当前运行期配置写入一个临时文件供脚本读取（不做结构归一化）
                try:
                    base_cfg = self._get_runtime_agent_cfg()
                    if not isinstance(base_cfg, dict) or not base_cfg:
                        ErrorHandler.handle_warning(self, "提示", "当前没有可用的Agent配置，请先在右侧生成或加载配置。")
                        return
                    import tempfile
                    _tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
                    _tmp.close()
                    cfg_path = _tmp.name
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        json.dump(base_cfg, f, ensure_ascii=False, indent=2)
                except Exception:
                    ErrorHandler.handle_warning(self, "提示", "无法创建运行期配置，请检查配置来源。")
                    return

            # 在输出框提示当前将使用的配置与来源
            try:
                self.agent_chat_output.append(f"[信息] 使用配置文件: {cfg_path} (来源: {src})\n")
            except Exception:
                pass

            # 启动脚本推理线程（与 on_run_agent_script 保持一致的外部脚本机制）
            from PySide6.QtCore import QThread
            self._script_thread = QThread()
            # 传入 memory_policy（若 agent_data 提供）
            mem_policy = None
            try:
                if isinstance(getattr(self, 'agent_data', None), dict):
                    mem_policy = self.agent_data.get('memory_write_policy')
            except Exception:
                mem_policy = None
            self._script_worker = ScriptInferWorker(config_path=cfg_path, prompt=user_text, memory_policy=mem_policy, verbose=False, timeout=300)
            self._script_worker.moveToThread(self._script_thread)
            self._script_thread.started.connect(self._script_worker.run)
            # 复用脚本模式的回调
            self._script_worker.finished.connect(self._on_script_finished)
            self._script_worker.failed.connect(self._on_script_failed)
            # 统一清理
            self._script_worker.finished.connect(self._finalize_script_thread)
            self._script_worker.failed.connect(self._finalize_script_thread)
            self._script_thread.start()
        except Exception as e:
            self.logger.warning(f"Agent发送处理失败: {e}")

    def on_run_agent_script(self):
        """脚本模式运行Agent（使用 ScriptInferWorker）"""
        if not hasattr(self, 'agent_data') or not self.agent_data:
            ErrorHandler.handle_warning(self, "提示", "请先导入Agent配置")
            return
        prompt = None
        try:
            if hasattr(self, 'agent_input_box') and self.agent_input_box is not None:
                prompt = self.agent_input_box.toPlainText().strip()
        except Exception:
            prompt = ''
        if not prompt:
            ErrorHandler.handle_warning(self, "提示", "请输入内容")
            return
        try:
            # 运行前预检（与普通运行一致）
            ok, msg = self.agent_service.preflight_check(self.agent_data)
            if not ok:
                ErrorHandler.handle_warning(self, "预检失败", msg or "配置不完整")
                return
            # 选择配置路径：若来源为 memory 且文件存在则优先使用
            cfg_path = None
            try:
                if getattr(self, '_exec_config_source', 'local') == 'memory':
                    mem_path = getattr(self, '_mem_agent_config_path', None)
                    if mem_path and os.path.exists(mem_path):
                        cfg_path = mem_path
            except Exception:
                cfg_path = None
            if not cfg_path:
                # 回退到当前本地配置文件路径
                try:
                    if hasattr(self, 'agent_path') and self.agent_path is not None:
                        _p = self.agent_path.text().strip()
                        if _p:
                            cfg_path = _p
                except Exception:
                    pass
            if not cfg_path:
                # 若没有路径，则临时写入一个文件供脚本读取（不归一化）
                try:
                    import tempfile
                    _tmpdir = tempfile.gettempdir()
                    cfg_path = os.path.join(_tmpdir, 'agent_run_tmp.json')
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        json.dump(self._get_runtime_agent_cfg(), f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            # 创建工作线程
            self._script_thread = QThread()
            self._script_worker = ScriptInferWorker(cfg_path, prompt, memory_policy=self.agent_data.get('memory_write_policy'), timeout=300)
            self._script_worker.moveToThread(self._script_thread)
            self._script_thread.started.connect(self._script_worker.run)
            self._script_worker.finished.connect(self._on_script_finished)
            self._script_worker.failed.connect(self._on_script_failed)
            self._script_worker.finished.connect(self._finalize_script_thread)
            self._script_worker.failed.connect(self._finalize_script_thread)
            self._script_thread.start()
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "脚本运行失败", e)

    def _on_script_finished(self, output: str):
        try:
            if hasattr(self, 'agent_chat_output') and self.agent_chat_output is not None:
                self.agent_chat_output.append(f"[Script] Agent: {output}")
                self.agent_chat_output.append("---")
            try:
                print(f"[SCRIPT_RUN] 输出: {str(output)[:400]}")
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"写入脚本输出失败: {e}")
            except Exception:
                pass

    def _on_script_failed(self, friendly_error: str):
        ErrorHandler.handle_warning(self, "脚本运行失败", friendly_error)
        try:
            self._log_thread_states("_on_script_failed")
        except Exception:
            pass
        try:
            print(f"[SCRIPT_RUN] 失败: {str(friendly_error)[:400]}")
        except Exception:
            pass

    def _finalize_script_thread(self):
        try:
            if getattr(self, '_script_worker', None):
                try:
                    self._script_worker.deleteLater()
                except Exception:
                    pass
                self._script_worker = None
            if getattr(self, '_script_thread', None):
                try:
                    self._script_thread.quit()
                    self._script_thread.wait(3000)
                except Exception:
                    pass
            self._script_thread = None
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "生成内存配置失败", e)

    def _cancel_agent_detail_edit(self):
        """取消右侧表单编辑：恢复为内存中的 agent_data，仅刷新UI，不写盘。"""
        try:
            self._refresh_right_agent_detail_tab()
            ErrorHandler.handle_success(self, "已取消", "已恢复为当前内存中的Agent数据")
        except Exception as e:
            try:
                self.logger.warning(f"取消编辑失败: {e}")
            except Exception:
                pass

    def _get_current_model_env_from_ui(self):
        """从右上角模型区域提取当前模型名、base_url、api_key_env（仅用于显式保存/导出）。"""
        model_name = ''
        base_url = ''
        api_key_env = ''
        try:
            if hasattr(self, 'det_model') and self.det_model is not None:
                model_name = (self.det_model.currentText() or '').strip()
        except Exception:
            pass
        try:
            if hasattr(self, 'asst_model_env_info') and self.asst_model_env_info is not None:
                txt = self.asst_model_env_info.toPlainText() or ''
                for line in txt.splitlines():
                    s = line.strip()
                    if s.lower().startswith('base_url:'):
                        base_url = s.split(':', 1)[1].strip()
                    elif s.lower().startswith('api_key_env:'):
                        api_key_env = s.split(':', 1)[1].strip()
        except Exception:
            pass
        return model_name, base_url, api_key_env

    def _apply_model_to_agent_safely(self):
        """将右上角模型选择及环境信息应用到 self.agent_data.model_client（内存中）。
        - 仅在显式保存/导出时调用。
        - 不做隐式归一化；尽量在 config 字段内补齐 model/base_url/api_key_env。
        """
        try:
            if not isinstance(getattr(self, 'agent_data', None), dict):
                return
            name, base_url, api_key_env = self._get_current_model_env_from_ui()
            if not name and not base_url and not api_key_env:
                return
            mc = self.agent_data.get('model_client') or {}
            if not isinstance(mc, dict):
                mc = {}
            cfg = mc.get('config') or {}
            if not isinstance(cfg, dict):
                cfg = {}
            if name:
                cfg['model'] = name
            if base_url and base_url != '-':
                cfg['base_url'] = base_url
            if api_key_env and api_key_env != '-':
                cfg['api_key_env'] = api_key_env
            mc['config'] = cfg
            self.agent_data['model_client'] = mc
        except Exception as e:
            try:
                self.logger.warning(f"应用模型到Agent失败: {e}")
            except Exception:
                pass

    def on_generate_mem_agent_config(self):
        """生成一次性内存版Agent配置到 temp/agent_mem_config.json，并打印 [MEMCFG] 日志。"""
        try:
            # 0-) UI 就绪：切换到 AssistantAgent 页并展开预览抽屉
            try:
                if hasattr(self, 'agent_right_tabs') and self.agent_right_tabs is not None:
                    self.agent_right_tabs.setCurrentIndex(0)
                if hasattr(self, 'config_panel') and self.config_panel is not None:
                    self.config_panel.setTitle("配置文件预览 - (生成中)")
                    self.config_panel.expand()
                if hasattr(self, 'asst_mem_config_preview') and self.asst_mem_config_preview is not None:
                    self.asst_mem_config_preview.blockSignals(True)
                    self.asst_mem_config_preview.clear()
                    self.asst_mem_config_preview.blockSignals(False)
                    try:
                        self.asst_mem_config_preview.setFocus()
                    except Exception:
                        pass
            except Exception:
                pass
            # 0) 入口调试
            try:
                print("[MEMCFG] click: on_generate_mem_agent_config")
                try:
                    self.logger.info("[MEMCFG] click: on_generate_mem_agent_config")
                except Exception:
                    pass
                # 可视化调试：确认槽函数已被触发
                try:
                    ErrorHandler.handle_success(self, "调试", "已进入生成内存配置槽函数")
                except Exception:
                    pass
            except Exception:
                pass

            # 0.5) 清空左侧本地路径输入，避免与内存配置混淆（不再写入临时路径）
            try:
                if hasattr(self, 'agent_path') and self.agent_path is not None:
                    self.agent_path.setText("")
            except Exception:
                pass

            # 1) 基本校验与兜底：允许在未显式导入/选择的情况下，直接使用右侧表单构造最小可用Agent
            data = getattr(self, 'agent_data', None)
            if not isinstance(data, dict) or not data:
                try:
                    print("[MEMCFG] warn: agent_data 缺失，尝试从右侧表单构造最小Agent")
                    try:
                        self.logger.warning("[MEMCFG] warn: agent_data 缺失，尝试从右侧表单构造最小Agent")
                    except Exception:
                        pass
                except Exception:
                    pass
                # 尝试用右侧表单回写生成最小结构
                try:
                    self._sync_agent_form_to_json()
                except Exception:
                    pass
                data = getattr(self, 'agent_data', None)
                # 若仍然无效，则使用内置默认模板
                if not isinstance(data, dict) or not data:
                    try:
                        self._new_agent_config()
                    except Exception:
                        pass
                    data = getattr(self, 'agent_data', None)
                # 若依然无效，则早退并恢复预览标题
                if not isinstance(data, dict) or not data:
                    try:
                        if hasattr(self, 'config_panel'):
                            self.config_panel.setTitle("配置文件预览 - (无内容)")
                    except Exception:
                        pass
                    try:
                        if hasattr(self, 'asst_mem_config_preview'):
                            self.asst_mem_config_preview.blockSignals(True)
                            self.asst_mem_config_preview.clear()
                            self.asst_mem_config_preview.blockSignals(False)
                    except Exception:
                        pass
                    ErrorHandler.handle_warning(self, "提示", "请先导入或创建Agent配置")
                    return

            # 2) 同步右侧表单到内存对象（不写盘）
            try:
                self._sync_agent_form_to_json()
            except Exception as e:
                try:
                    self.logger.warning(f"生成内存配置前同步右栏失败: {e}")
                except Exception:
                    pass

            # 3) 运行期 system_message：统一使用右侧表单已回写到 self.agent_data 的值
            cfg = dict(self.agent_data)

            # 4) 轻量校验 memory 字段类型；若非法，仅在导出副本中置空 []
            try:
                _mem = cfg.get('memory', [])
                if not isinstance(_mem, list):
                    try:
                        print("[MEMCFG] 修正: memory 非列表，导出副本置空 []")
                    except Exception:
                        pass
                    cfg['memory'] = []
            except Exception:
                pass

            # 5) 仅用“右侧Agent页模型框(det_model)”的 model/base_url/api_key_env 更新导出副本 cfg.model_client.config（禁止回退到Model页选择器，避免干扰）
            try:
                _m_name, _m_base, _m_env = self._get_current_model_env_from_ui()
                if _m_name or _m_base or _m_env:
                    mc = cfg.get('model_client') or {}
                    if not isinstance(mc, dict):
                        mc = {}
                    _mc_cfg = mc.get('config') or {}
                    if not isinstance(_mc_cfg, dict):
                        _mc_cfg = {}
                    if _m_name:
                        _mc_cfg['model'] = _m_name
                    if _m_base and _m_base != '-':
                        _mc_cfg['base_url'] = _m_base
                    if _m_env and _m_env != '-':
                        _mc_cfg['api_key_env'] = _m_env
                    mc['config'] = _mc_cfg
                    cfg['model_client'] = mc
            except Exception:
                pass

            # 6) 解析关键信息用于打印
            name = str(cfg.get('name') or cfg.get('id') or '')
            model = ''
            base_url = ''
            provider = ''
            api_key_env = ''
            base_fields = {}
            mc = cfg.get('model_client') or {}
            if isinstance(mc, dict):
                try:
                    provider = str(mc.get('provider') or '')
                except Exception:
                    provider = ''
                _mc_cfg = mc.get('config') or {}
                if isinstance(_mc_cfg, dict):
                    model = str(_mc_cfg.get('model') or '')
                    # 兼容多种命名：base_url / api_base / openai_api_base / base
                    base_url = str(
                        _mc_cfg.get('base_url')
                        or _mc_cfg.get('api_base')
                        or _mc_cfg.get('openai_api_base')
                        or _mc_cfg.get('base')
                        or ''
                    )
                    # 收集原始端点字段，便于逐项打印
                    try:
                        for _k in ('base_url', 'api_base', 'openai_api_base', 'base'):
                            if _k in _mc_cfg and _mc_cfg.get(_k):
                                base_fields[_k] = str(_mc_cfg.get(_k))
                    except Exception:
                        pass
                    # 读取环境变量键名
                    try:
                        api_key_env = str(_mc_cfg.get('api_key_env') or '')
                    except Exception:
                        api_key_env = ''
            memories = cfg.get('memory') or []
            write_policy = str(cfg.get('memory_write_policy', ''))

            # 6.1) 必填校验：Agent 名称
            try:
                if not name.strip():
                    # 还原/提示并聚焦名称输入
                    try:
                        if hasattr(self, 'config_panel') and self.config_panel is not None:
                            self.config_panel.setTitle("配置文件预览 - (生成中)")
                            self.config_panel.expand()
                    except Exception:
                        pass
                    try:
                        if hasattr(self, 'asst_mem_config_preview') and self.asst_mem_config_preview is not None:
                            self.asst_mem_config_preview.blockSignals(True)
                            self.asst_mem_config_preview.clear()
                            self.asst_mem_config_preview.blockSignals(False)
                    except Exception:
                        pass
                    try:
                        if hasattr(self, 'det_name') and self.det_name is not None:
                            self.det_name.setFocus()
                    except Exception:
                        pass
                    ErrorHandler.handle_warning(self, "缺少名称", "请先在右侧表单填写 Agent 的 name，再点击生成")
                    return
            except Exception:
                pass

            # 7) 规范化（移除UI字段；修复空的 model_client.config；保持合规结构）
            try:
                # 记录源路径用于回退
                _src_path = str((self.agent_data or {}).get('_config_path') or '')
                # 移除 UI/临时字段
                if '_config_path' in cfg:
                    cfg.pop('_config_path', None)
                if 'agent_type' in cfg:
                    cfg.pop('agent_type', None)

                # 确保 model_client.provider/config 合法，必要时回退到原始文件
                mc = cfg.get('model_client') or {}
                if not isinstance(mc, dict):
                    mc = {}
                _mc_cfg = mc.get('config')
                need_fallback = (not isinstance(_mc_cfg, dict)) or (len(_mc_cfg) == 0)
                if need_fallback and _src_path and os.path.exists(_src_path):
                    with open(_src_path, 'r', encoding='utf-8') as _f:
                        _origin = json.load(_f)
                    _omc = (_origin or {}).get('model_client') or {}
                    if isinstance(_omc, dict):
                        if 'provider' in _omc and _omc.get('provider'):
                            mc['provider'] = _omc.get('provider')
                        _omc_cfg = _omc.get('config') or {}
                        if isinstance(_omc_cfg, dict) and _omc_cfg:
                            mc['config'] = _omc_cfg
                            cfg['model_client'] = mc
                            try:
                                print("[MEMCFG] fix: model_client.config 为空，已回退为原始Agent配置")
                                self.logger.warning("[MEMCFG] fix: model_client.config 为空，已回退为原始Agent配置")
                            except Exception:
                                pass
            except Exception:
                pass

            # 7.2) 注入“参与者（导入器）”中的组件到导出副本 cfg
            # - 工具（tool）：并入 cfg['tools'] 列表
            # - 向量库（vectorstore/memory）：并入 cfg['memory'] 列表（若不是列表则包裹为列表）
            # - MCP：并入 cfg['mcp'] 列表（与仓库/运行时注册不冲突，生成期做显式声明）
            # - 模型组件（model）：若存在且未明确设置 model_client，则采用导入的模型组件
            try:
                if hasattr(self, '_agent_import_cache') and isinstance(self._agent_import_cache, dict) and self._agent_import_cache:
                    tools_list = []
                    try:
                        tools_list = list(cfg.get('tools') or []) if isinstance(cfg.get('tools'), list) else []
                    except Exception:
                        tools_list = []
                    # 规范 memory 为列表容器（导出副本层面）
                    mem_list = []
                    _mem_existing = cfg.get('memory')
                    if isinstance(_mem_existing, list):
                        mem_list = list(_mem_existing)
                    elif isinstance(_mem_existing, dict):
                        # 若已有 dict，先保留为单项
                        mem_list = [_mem_existing]
                    elif _mem_existing is None:
                        mem_list = []
                    else:
                        # 标量等，保留为单项字符串
                        mem_list = [_mem_existing]

                    mcp_list = []
                    # 若已存在 mcp 清单，合并之
                    try:
                        if isinstance(cfg.get('mcp'), list):
                            mcp_list = list(cfg.get('mcp'))
                    except Exception:
                        mcp_list = []
                    imported_model_cm = None

                    def _looks_like_vectorstore(obj: dict) -> bool:
                        try:
                            if 'vectorstore' in obj or 'stores' in obj or 'vectorstores' in obj:
                                return True
                            if 'persist_directory' in obj and 'collection_name' in obj:
                                return True
                            cfg1 = obj.get('config') or {}
                            if isinstance(cfg1, dict):
                                inner = cfg1.get('config') or {}
                                if isinstance(inner, dict) and 'persist_directory' in inner and 'collection_name' in inner:
                                    return True
                        except Exception:
                            pass
                        return False

                    def _looks_like_tool(obj: dict) -> bool:
                        try:
                            if 'tool' in obj or 'function' in obj:
                                return True
                            if 'id' in obj or 'name' in obj:
                                # 常见工具配置含 id/name/type/provider 等
                                return True
                        except Exception:
                            pass
                        return False

                    def _looks_like_mcp(obj: dict) -> bool:
                        try:
                            if 'servers' in obj:
                                return True
                            if obj.get('type') in ('proc', 'stdio', 'sse'):
                                return True
                            if 'command' in obj or 'args' in obj:
                                # 单个 server 项
                                return True
                        except Exception:
                            pass
                        return False

                    def _looks_like_model(obj: dict) -> bool:
                        try:
                            if obj.get('component_type') == 'model' and obj.get('provider'):
                                return True
                            # 兼容非组件式模型：包含 config.model
                            c = obj.get('config') if isinstance(obj.get('config'), dict) else None
                            if c and c.get('model'):
                                return True
                        except Exception:
                            pass
                        return False

                    for pth, obj in self._agent_import_cache.items():
                        if not isinstance(obj, dict):
                            continue
                        try:
                            if _looks_like_vectorstore(obj):
                                mem_list.append(obj)
                                try:
                                    self.logger.info(f"[MEMCFG] import: vectorstore <- {os.path.basename(pth)}")
                                except Exception:
                                    pass
                                continue
                            if _looks_like_tool(obj):
                                tools_list.append(obj)
                                try:
                                    self.logger.info(f"[MEMCFG] import: tool <- {os.path.basename(pth)}")
                                except Exception:
                                    pass
                                continue
                            if _looks_like_mcp(obj):
                                mcp_list.append(obj)
                                try:
                                    self.logger.info(f"[MEMCFG] import: MCP <- {os.path.basename(pth)}")
                                except Exception:
                                    pass
                                continue
                            if _looks_like_model(obj) and imported_model_cm is None:
                                # 仅采用第一个有效模型作为导入模型
                                imported_model_cm = obj
                                try:
                                    self.logger.info(f"[MEMCFG] import: model <- {os.path.basename(pth)}")
                                except Exception:
                                    pass
                                continue
                            # 未识别类型：忽略，但记录调试
                            try:
                                self.logger.debug(f"[MEMCFG] import: unknown json type <- {os.path.basename(pth)}")
                            except Exception:
                                pass
                        except Exception:
                            continue

                    if tools_list:
                        cfg['tools'] = tools_list
                    if mem_list:
                        cfg['memory'] = mem_list
                    if mcp_list:
                        cfg['mcp'] = mcp_list
                    # 优先使用导入的模型组件（若用户通过导入提供）
                    if imported_model_cm and not isinstance((cfg.get('model_client') or {}), dict):
                        cfg['model_client'] = imported_model_cm
                    elif imported_model_cm and not (cfg.get('model_client') or {}).get('provider'):
                        cfg['model_client'] = imported_model_cm
            except Exception:
                pass

            # 8) 写入到 temp/agent_mem_config.json
            try:
                # 7.8) 仅当用户通过“参与者（导入器）”显式导入了 MCP 时，才注入 MCP 工作台
                try:
                    def _has_imported_mcp() -> bool:
                        # 判定来源：1) cfg['mcp'] 列表非空；2) 导入缓存中存在 mcp-like 对象
                        try:
                            if isinstance(cfg.get('mcp'), list) and len(cfg.get('mcp')) > 0:
                                return True
                        except Exception:
                            pass
                        try:
                            cache = getattr(self, '_agent_import_cache', {})
                            if isinstance(cache, dict):
                                for _, obj in cache.items():
                                    if isinstance(obj, dict) and ('servers' in obj or obj.get('type') in ('proc','stdio','sse') or 'command' in obj or 'args' in obj):
                                        return True
                        except Exception:
                            pass
                        return False

                    if _has_imported_mcp():
                        # 从本地 servers.json 读取“模板”，仅作为参数补全；若不存在则保持当前 workbench 不动
                        mcp_cfg_path = os.path.join(str(ROOT), 'config', 'mcp', 'servers.json')
                        mcp_wb = None
                        if os.path.exists(mcp_cfg_path):
                            with open(mcp_cfg_path, 'r', encoding='utf-8') as _sf:
                                _servers_obj = json.load(_sf) or {}
                            _servers = list((_servers_obj or {}).get('servers') or [])
                            target = None
                            for s in _servers:
                                try:
                                    if isinstance(s, dict) and not s.get('disabled', False):
                                        target = s
                                        break
                                except Exception:
                                    continue
                            if target:
                                command = target.get('command') or 'python'
                                args = target.get('args') or []
                                env = target.get('env') or {}
                                # 镜像当前 agent 的 model_client 作为 MCP 采样支持
                                mc_for_mcp = None
                                try:
                                    _mc = cfg.get('model_client') or {}
                                    if isinstance(_mc, dict) and _mc:
                                        _prov = _mc.get('provider') or 'autogen_ext.models.openai.OpenAIChatCompletionClient'
                                        _cfg_inner = _mc.get('config') or {}
                                        mc_for_mcp = {
                                            'provider': _prov,
                                            'component_type': 'model',
                                            'version': 1,
                                            'component_version': 1,
                                            'description': 'Chat completion client',
                                            'label': 'ModelForMCP',
                                            'config': _cfg_inner,
                                        }
                                except Exception:
                                    mc_for_mcp = None
                                mcp_wb = [{
                                    'provider': 'autogen_ext.tools.mcp.McpWorkbench',
                                    'component_type': 'workbench',
                                    'version': 1,
                                    'component_version': 1,
                                    'description': 'A workbench that wraps an MCP server via STDIO and exposes its tools.',
                                    'label': 'McpWorkbench',
                                    'config': {
                                        'server_params': {
                                            'type': 'StdioServerParams',
                                            'command': command,
                                            'args': args,
                                            'env': env,
                                            'read_timeout_seconds': 60
                                        },
                                        'tool_overrides': {},
                                        'model_client': mc_for_mcp
                                    }
                                }]
                        # 若用户确实导入了 MCP 且存在模板，则覆盖 workbench；否则保持不改动
                        if mcp_wb:
                            cfg['workbench'] = mcp_wb
                            try:
                                print('[MEMCFG] apply: workbench := MCP(STDIO) (用户导入MCP后注入)')
                                self.logger.info('[MEMCFG] apply: workbench := MCP(STDIO) (用户导入MCP后注入)')
                            except Exception:
                                pass
                    else:
                        # 未导入 MCP：不注入，保持现状（避免无意“泄露”MCP）
                        try:
                            self.logger.info('[MEMCFG] skip: 未导入MCP -> 不注入MCP工作台')
                        except Exception:
                            pass
                except Exception as _mx:
                    try:
                        self.logger.warning(f"[MEMCFG] MCP 注入判定失败（忽略注入，保留默认）: {str(_mx)[:150]}")
                    except Exception:
                        pass
                # 7.5) 标准化前的合规化增强：api_key->api_key_env、清理空值、提高工具迭代、默认摘要模板、MCP路径绝对化
                try:
                    import re as _re
                    def _extract_env_from_dollar(value: str) -> str:
                        try:
                            m = _re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$", str(value).strip())
                            return m.group(1) if m else ''
                        except Exception:
                            return ''

                    def _normalize_model_client_env(mc_obj: dict) -> dict:
                        if not isinstance(mc_obj, dict):
                            return {}
                        cfg_i = mc_obj.get('config') or {}
                        if isinstance(cfg_i, dict):
                            # api_key -> api_key_env
                            if 'api_key' in cfg_i and not cfg_i.get('api_key_env'):
                                env_name = _extract_env_from_dollar(cfg_i.get('api_key'))
                                if env_name:
                                    cfg_i['api_key_env'] = env_name
                                    try:
                                        cfg_i.pop('api_key', None)
                                    except Exception:
                                        pass
                            # 清理空值字段
                            for k in list(cfg_i.keys()):
                                v = cfg_i.get(k)
                                if v in (None, ''):
                                    cfg_i.pop(k, None)
                                elif isinstance(v, (list, dict)) and len(v) == 0:
                                    cfg_i.pop(k, None)
                            mc_obj['config'] = cfg_i
                        return mc_obj

                    # 提升工具调用迭代与默认摘要模板
                    try:
                        v_iter = int(cfg.get('max_tool_iterations', 1) or 1)
                        if v_iter < 2:
                            cfg['max_tool_iterations'] = 2
                    except Exception:
                        cfg['max_tool_iterations'] = 2
                    try:
                        if not str(cfg.get('tool_call_summary_format') or '').strip():
                            cfg['tool_call_summary_format'] = '{result}'
                    except Exception:
                        pass
                    # 仅当未显式设置时，提供更安全的默认：开启工具反思
                    if 'reflect_on_tool_use' not in cfg:
                        cfg['reflect_on_tool_use'] = True

                    # 主模型 client 合规化
                    try:
                        mc0 = cfg.get('model_client') or {}
                        if isinstance(mc0, dict) and mc0:
                            cfg['model_client'] = _normalize_model_client_env(mc0)
                    except Exception:
                        pass

                    # MCP 路径绝对化 + 子模型 client 合规化
                    try:
                        root_path = str(ROOT)
                        wb = cfg.get('workbench') or []
                        if isinstance(wb, list):
                            for item in wb:
                                if not isinstance(item, dict):
                                    continue
                                prov = str(item.get('provider') or '')
                                if 'McpWorkbench' in prov:
                                    cfg_wb = item.get('config') or {}
                                    if isinstance(cfg_wb, dict):
                                        sp = cfg_wb.get('server_params') or {}
                                        if isinstance(sp, dict):
                                            cmd = sp.get('command')
                                            args = sp.get('args') or []
                                            if isinstance(cmd, str) and isinstance(args, list) and len(args) >= 1:
                                                # 将 tools/windsurf_sink_mcp.py 绝对化
                                                try:
                                                    arg0 = str(args[0])
                                                    if arg0.replace('\\', '/').endswith('tools/windsurf_sink_mcp.py') or arg0 == 'tools/windsurf_sink_mcp.py':
                                                        abs_path = os.path.join(root_path, 'tools', 'windsurf_sink_mcp.py')
                                                        args[0] = abs_path
                                                        sp['args'] = args
                                                        cfg_wb['server_params'] = sp
                                                except Exception:
                                                    pass
                                        # 归一 MCP 子模型 client
                                        try:
                                            mc_mcp = cfg_wb.get('model_client') or {}
                                            if isinstance(mc_mcp, dict) and mc_mcp:
                                                cfg_wb['model_client'] = _normalize_model_client_env(mc_mcp)
                                        except Exception:
                                            pass
                                        item['config'] = cfg_wb
                    except Exception:
                        pass
                except Exception:
                    pass

                # 7.6) 生成前的最终兜底：确保关键字段存在并合规
                try:
                    # tools/memory/capabilities 统一为列表（若缺失则置空列表）
                    if not isinstance(cfg.get('tools'), list):
                        cfg['tools'] = []
                    if not isinstance(cfg.get('memory'), list):
                        # 若 memory 为 dict/标量/None -> 置空列表（导出副本层面）
                        cfg['memory'] = []
                    if not isinstance(cfg.get('capabilities'), list):
                        cfg['capabilities'] = []
                    # 默认写入策略（若未显式提供）
                    if not str(cfg.get('memory_write_policy') or '').strip():
                        cfg['memory_write_policy'] = 'qa_both'
                except Exception:
                    pass

                # 7.7) 使用与“配置生成器”一致的惰性导入与标准化流程
                #     若导入或标准化失败，直接提示错误并中止（保持两处一致的行为语义）
                try:
                    try:
                        from scripts.agent_config_gen import standardize  # type: ignore
                    except Exception:
                        import sys
                        from pathlib import Path as _Path
                        root = _Path(__file__).resolve().parents[2]
                        if str(root) not in sys.path:
                            sys.path.insert(0, str(root))
                        from scripts.agent_config_gen import standardize  # type: ignore

                    cfg_to_write = standardize(cfg)
                    if not isinstance(cfg_to_write, dict) or not cfg_to_write:
                        raise ValueError("standardize() 返回空结果")
                    try:
                        print("[MEMCFG] standardize: 使用 scripts.agent_config_gen.standardize 规范化配置")
                        self.logger.info("[MEMCFG] standardize: 使用 scripts.agent_config_gen.standardize 规范化配置")
                    except Exception:
                        pass
                    # Post-fix: 将 standardize 输出中的 api_key 占位恢复为 api_key_env，并补齐缺失的 base_url
                    try:
                        import re as __re
                        def __extract_env(val: str) -> str:
                            try:
                                m = __re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$", str(val).strip())
                                return m.group(1) if m else ''
                            except Exception:
                                return ''
                        def __fix_mc_env(mc_dict: dict) -> dict:
                            if not isinstance(mc_dict, dict):
                                return {}
                            cc = mc_dict.get('config') or {}
                            if isinstance(cc, dict):
                                if 'api_key_env' not in cc and 'api_key' in cc:
                                    envn = __extract_env(cc.get('api_key'))
                                    if envn:
                                        cc['api_key_env'] = envn
                                        try:
                                            cc.pop('api_key', None)
                                        except Exception:
                                            pass
                                # 补齐 base_url（如缺失且 UI 有提供）
                                need_base = not bool(cc.get('base_url'))
                                if need_base:
                                    try:
                                        _m_name, _m_base, _m_env = self._get_current_model_env_from_ui()
                                        if _m_base and _m_base != '-':
                                            cc['base_url'] = _m_base
                                        # 仍缺失则回退到原始 agent_data 的 base_url
                                        if not cc.get('base_url') and isinstance(getattr(self, 'agent_data', None), dict):
                                            try:
                                                _orig_mc = (self.agent_data.get('model_client') or {}).get('config') or {}
                                                if isinstance(_orig_mc, dict) and _orig_mc.get('base_url'):
                                                    cc['base_url'] = _orig_mc.get('base_url')
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                # 若缺少 api_key_env，尝试从原始 agent_data 提取
                                if not cc.get('api_key_env') and isinstance(getattr(self, 'agent_data', None), dict):
                                    try:
                                        _orig_mc = (self.agent_data.get('model_client') or {}).get('config') or {}
                                        if isinstance(_orig_mc, dict):
                                            if _orig_mc.get('api_key_env'):
                                                cc['api_key_env'] = _orig_mc.get('api_key_env')
                                            elif _orig_mc.get('api_key'):
                                                envn2 = __extract_env(_orig_mc.get('api_key'))
                                                if envn2:
                                                    cc['api_key_env'] = envn2
                                    except Exception:
                                        pass
                                mc_dict['config'] = cc
                            return mc_dict
                        # 主模型
                        top = cfg_to_write.get('config') or {}
                        if isinstance(top, dict):
                            mc0 = top.get('model_client') or {}
                            if isinstance(mc0, dict) and mc0:
                                top['model_client'] = __fix_mc_env(mc0)
                            # workbench 内的子模型（如 MCP）
                            wb = top.get('workbench') or []
                            if isinstance(wb, list):
                                for it in wb:
                                    try:
                                        if isinstance(it, dict):
                                            cfg_wb = it.get('config') or {}
                                            if isinstance(cfg_wb, dict):
                                                mc_m = cfg_wb.get('model_client') or {}
                                                if isinstance(mc_m, dict) and mc_m:
                                                    cfg_wb['model_client'] = __fix_mc_env(mc_m)
                                                it['config'] = cfg_wb
                                    except Exception:
                                        continue
                            cfg_to_write['config'] = top
                    except Exception:
                        pass
                    # 先将标准化结果直接渲染到右侧预览（即使随后写文件失败，预览也能看到结果）
                    try:
                        if hasattr(self, 'asst_mem_config_preview') and hasattr(self, 'config_panel'):
                            import json as _json
                            preview_txt = _json.dumps(cfg_to_write, ensure_ascii=False, indent=2)
                            try:
                                self.config_panel.setTitle("配置文件预览 - (未保存)")
                                self.config_panel.expand()
                            except Exception:
                                pass
                            try:
                                self.asst_mem_config_preview.blockSignals(True)
                            except Exception:
                                pass
                            self.asst_mem_config_preview.setPlainText(preview_txt)
                            try:
                                self.asst_mem_config_preview.blockSignals(False)
                            except Exception:
                                pass
                            try:
                                self._adjust_config_preview_height()
                            except Exception:
                                pass
                    except Exception:
                        pass
                except Exception as _se:
                    try:
                        print(f"[MEMCFG] error: 标准化失败 -> {str(_se)[:150]}")
                        self.logger.error(f"[MEMCFG] error: 标准化失败 -> {str(_se)[:150]}")
                    except Exception:
                        pass
                    ErrorHandler.handle_ui_error(self, "生成失败", _se)
                    return

                out_dir = Paths.ensure_dir(Paths.TEMP_DIR)
                out_path = out_dir / 'agent_mem_config.json'
                with out_path.open('w', encoding='utf-8') as f:
                    json.dump(cfg_to_write, f, ensure_ascii=False, indent=2)
                self._mem_agent_config_path = str(out_path)
                try:
                    self.logger.info(f"[MEMCFG] output={self._mem_agent_config_path}")
                except Exception:
                    pass
                # 成功生成内存版配置后，切换运行配置来源为 memory
                try:
                    self._exec_config_source = 'memory'
                    try:
                        print("[MEMCFG] exec_source := memory (优先使用内存配置运行)")
                    except Exception:
                        pass
                    try:
                        self.logger.info("[MEMCFG] exec_source := memory")
                    except Exception:
                        pass
                except Exception:
                    pass
                # 7.9) 生成成功后：将生成的配置覆盖为当前内存配置，并刷新中部表单与右侧列表
                try:
                    # 使用标准化后的 cfg_to_write 覆盖当前内存对象
                    if isinstance(cfg_to_write, dict) and cfg_to_write:
                        self.agent_data = cfg_to_write
                        # 不再把临时路径写入 agent_path，保持为空以指示“内存配置”来源
                        try:
                            if hasattr(self, 'agent_path') and self.agent_path is not None:
                                self.agent_path.setText("")
                        except Exception:
                            pass
                        try:
                            if hasattr(self, 'agent_name_edit'):
                                self.agent_name_edit.setText(self.agent_data.get("name", ""))
                            if hasattr(self, 'agent_role_edit'):
                                self.agent_role_edit.setText(self.agent_data.get("role", ""))
                            if hasattr(self, 'agent_sysmsg_edit'):
                                self.agent_sysmsg_edit.setPlainText(self.agent_data.get("system_message", ""))
                        except Exception:
                            pass
                        # 中部详情表单刷新
                        try:
                            if hasattr(self, '_refresh_right_agent_detail_tab'):
                                self._refresh_right_agent_detail_tab()
                        except Exception:
                            pass
                        # 右侧Tabs刷新（工具/向量库/MCP）
                        try:
                            if hasattr(self, '_refresh_right_tools_tab'):
                                self._refresh_right_tools_tab()
                        except Exception:
                            pass
                        try:
                            if hasattr(self, '_refresh_right_vectorstores_tab'):
                                self._refresh_right_vectorstores_tab()
                        except Exception:
                            pass
                        try:
                            if hasattr(self, '_refresh_right_mcp_tab'):
                                self._refresh_right_mcp_tab()
                        except Exception:
                            pass
                        # 可选：模型右栏刷新，保持与导入逻辑的观感一致
                        try:
                            if hasattr(self, '_refresh_model_right_panel'):
                                self._refresh_model_right_panel()
                        except Exception:
                            pass
                        try:
                            self.logger.info("[MEMCFG] 已将生成的配置覆盖到表单与清单视图")
                        except Exception:
                            pass
                except Exception as _ue:
                    try:
                        self.logger.warning(f"[MEMCFG] 生成后回填表单失败: {str(_ue)[:150]}")
                    except Exception:
                        pass
            except Exception as e:
                try:
                    print(f"[MEMCFG] error: 写入失败 -> {str(e)[:200]}")
                    try:
                        self.logger.error(f"[MEMCFG] error: 写入失败 -> {str(e)[:200]}")
                    except Exception:
                        pass
                except Exception:
                    pass
                ErrorHandler.handle_ui_error(self, "生成失败", e)
                return

            # 9) 控制台输出关键信息
            try:
                print(f"[MEMCFG] output={self._mem_agent_config_path}")
                # 模型与端点
                if base_url:
                    print(f"[MEMCFG] model={model or '-'} | base_url={base_url}")
                    try:
                        self.logger.info(f"[MEMCFG] model={model or '-'} | base_url={base_url}")
                    except Exception:
                        pass
                # provider 与各端点原始字段
                if provider:
                    try:
                        print(f"[MEMCFG] provider={provider}")
                    except Exception:
                        pass
                    try:
                        self.logger.info(f"[MEMCFG] provider={provider}")
                    except Exception:
                        pass
                if isinstance(base_fields, dict) and base_fields:
                    for _k, _v in base_fields.items():
                        try:
                            print(f"[MEMCFG] {_k}={_v}")
                        except Exception:
                            pass
                        try:
                            self.logger.info(f"[MEMCFG] {_k}={_v}")
                        except Exception:
                            pass
                # 环境变量键名与掩码值
                if api_key_env:
                    try:
                        _val = os.environ.get(api_key_env, '')
                        _masked = (_val[:4] + '...') if _val else '未设置'
                        print(f"[MEMCFG] env {api_key_env}={_masked}")
                    except Exception:
                        pass
                    try:
                        _val = os.environ.get(api_key_env, '')
                        _masked = (_val[:4] + '...') if _val else '未设置'
                        self.logger.info(f"[MEMCFG] env {api_key_env}={_masked}")
                    except Exception:
                        pass
                print(f"[MEMCFG] agent={name or '-'} | model={model or '-'} | memories={len(memories)} | write_policy={write_policy or '-'}")
                try:
                    self.logger.info(f"[MEMCFG] agent={name or '-'} | model={model or '-'} | memories={len(memories)} | write_policy={write_policy or '-'}")
                except Exception:
                    pass
                if isinstance(memories, list) and memories:
                    for _i, _mem in enumerate(memories):
                        try:
                            _j = json.dumps(_mem, ensure_ascii=False)
                            if len(_j) > 800:
                                _j = _j[:797] + '...'
                            print(f"[MEMCFG] memory[{_i}]={_j}")
                        except Exception:
                            pass
                        try:
                            _j2 = json.dumps(_mem, ensure_ascii=False)
                            if len(_j2) > 800:
                                _j2 = _j2[:797] + '...'
                            self.logger.info(f"[MEMCFG] memory[{_i}]={_j2}")
                        except Exception:
                            pass
            except Exception:
                pass

            # 9.5) 加载配置文件内容到折叠面板
            try:
                if hasattr(self, 'asst_mem_config_preview') and hasattr(self, 'config_panel'):
                    # 读取生成的配置文件
                    with open(self._mem_agent_config_path, 'r', encoding='utf-8') as f:
                        config_content = f.read()
                    
                    # 格式化JSON（确保美观展示）
                    try:
                        json_obj = json.loads(config_content)
                        config_content = json.dumps(json_obj, ensure_ascii=False, indent=2)
                    except Exception:
                        # 如果格式化失败，使用原始内容
                        pass
                    
                    # 更新面板标题
                    file_name = os.path.basename(self._mem_agent_config_path)
                    self.config_panel.setTitle(f"配置文件预览 - {file_name}")
                    
                    # 先展开面板，然后设置文本
                    self.config_panel.expand()
                    self.asst_mem_config_preview.setPlainText(config_content)
                    
                    # 主动触发高度调整
                    self._adjust_config_preview_height()
                    
                    try:
                        self.logger.info("[MEMCFG] 已加载配置内容到UI预览面板")
                    except Exception:
                        pass
            except Exception as e:
                try:
                    self.logger.warning(f"[MEMCFG] 加载配置到面板失败: {str(e)}")
                except Exception:
                    pass

            # 10) UI 提示
            ErrorHandler.handle_success(self, "成功", "已生成临时内存配置到 temp/agent_mem_config.json")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "生成内存配置失败", e)

    def _create_model_tab(self):
        """创建Model页面"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 三栏分割
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左栏：改为“仓库下拉选择器 + 系统提示 + 运行区”
        left = QWidget(); left_layout = QVBoxLayout(left)
        sel_layout = QHBoxLayout()
        self.model_selector = QComboBox()
        btn_model_refresh = QPushButton("刷新")
        try:
            btn_model_refresh.clicked.connect(self._refresh_model_selector)
            self.model_selector.currentIndexChanged.connect(self._on_model_selector_changed)
        except Exception:
            pass
        sel_layout.addWidget(QLabel("选择Model:"))
        sel_layout.addWidget(self.model_selector)
        sel_layout.addWidget(btn_model_refresh)
        left_layout.addLayout(sel_layout)

        # 恢复：本地文件路径 + 浏览按钮
        file_row = QHBoxLayout()
        from PySide6.QtWidgets import QLineEdit
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText("选择或输入本地模型JSON路径…")
        btn_model_browse = QPushButton("浏览…")
        try:
            btn_model_browse.clicked.connect(self.on_browse_model)
        except Exception:
            pass
        try:
            # 支持直接在输入框按回车加载本地JSON
            self.model_path.returnPressed.connect(self.on_load_model_path)
        except Exception:
            pass
        file_row.addWidget(self.model_path)
        file_row.addWidget(btn_model_browse)
        left_layout.addLayout(file_row)
        # 初始化Model下拉
        try:
            self._refresh_model_selector()
        except Exception:
            pass
        # 启动时清空默认模型，保持右侧与系统提示为空，避免误解为已加载默认模型
        try:
            self._clear_model_ui_fields()
        except Exception:
            pass
        # 仅一个“保存”按钮（原样保存，弹出文件选择器）
        try:
            btn_save_model_cfg_left = QPushButton("保存")
            try:
                btn_save_model_cfg_left.clicked.connect(self.on_save_model_config)
            except Exception:
                pass
            left_layout.addWidget(btn_save_model_cfg_left)
        except Exception:
            pass
        left_layout.addWidget(QLabel("系统提示词:"))
        self.system_prompt = QTextEdit()
        try:
            self.system_prompt.setPlaceholderText("在此输入系统提示词（System Prompt）…")
        except Exception:
            pass
        self.system_prompt.setMinimumHeight(120)
        self.system_prompt.setMaximumHeight(200)
        left_layout.addWidget(self.system_prompt)
        # 与 Team 页一致：在系统提示词下方加入输入/输出对话区
        self._create_chat_area(left_layout)
        # 中栏：模型参数表单
        middle_panel = self._create_model_middle_panel()
        # 右栏：配置浏览框与生成
        right_panel = self._create_model_right_panel()
        # 组装分栏（三栏）
        splitter.addWidget(left)
        splitter.addWidget(middle_panel)
        splitter.addWidget(right_panel)
        # 尺寸与交互：不可折叠 + 手柄宽度 + 面板自适应填充
        try:
            left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            middle_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            right_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(6)
        except Exception:
            pass
        # 伸缩策略：左 3 / 中 3 / 右 2
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        layout.addWidget(splitter)
        # 加入主Tab
        self.tabs.addTab(widget, "Model")

    def _create_model_middle_panel(self) -> QWidget:
        """创建中栏：动态模型参数表单（完整可扩展，含必填项行）。"""
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        # 自适应：零边距/零间距 + 可扩展尺寸策略
        try:
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(0)
            panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass
        try:
            title = QLabel("模型参数（对齐完整配置）")
            try:
                f = title.font(); f.setBold(True); title.setFont(f)
            except Exception:
                pass
            vbox.addWidget(title)

            # 可滚动参数编辑区
            scroll = QScrollArea()
            try:
                scroll.setWidgetResizable(True)
                scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            except Exception:
                pass
            host = QWidget(); self._model_param_form = QFormLayout(host)
            try:
                # 使表单字段在可用空间内扩展，避免内容被裁切
                self._model_param_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                self._model_param_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
                self._model_param_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
                self._model_param_form.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
            except Exception:
                pass
            try:
                host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            except Exception:
                pass
            try:
                # 显式设置布局，避免某些平台下未生效导致控件不显示
                host.setLayout(self._model_param_form)
            except Exception:
                pass
            scroll.setWidget(host)
            vbox.addWidget(scroll)

            # 存放编辑器引用，便于回填/读取
            self._model_param_editors = {}

            # 首次构建
            try:
                self._refresh_model_param_panel()
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"创建Model中栏失败: {e}")
            except Exception:
                pass
        return panel

    def _create_model_right_panel(self) -> QWidget:
        """创建 Model 页右侧面板：仅包含配置文件浏览框 + 按钮行（在浏览框下）。"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        try:
            # 仅浏览框（不再显示标题/标签）
            self.model_config_preview = QTextEdit()
            try:
                self.model_config_preview.setReadOnly(True)
                self.model_config_preview.setMinimumHeight(160)
                self.model_config_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            except Exception:
                pass
            layout.addWidget(self.model_config_preview)

            # 按钮行：生成 / 复制 / 清空（放在浏览框下方）
            from PySide6.QtWidgets import QHBoxLayout
            btn_row = QHBoxLayout()
            self.btn_generate_model_cfg = QPushButton("生成model 配置")
            self.btn_copy_model_cfg = QPushButton("复制")
            self.btn_clear_model_cfg = QPushButton("清空")
            try:
                self.btn_generate_model_cfg.clicked.connect(self.on_generate_model_config)
            except Exception:
                pass
            try:
                self.btn_copy_model_cfg.clicked.connect(self.on_copy_model_config)
            except Exception:
                pass
            try:
                self.btn_clear_model_cfg.clicked.connect(self.on_clear_model_config)
            except Exception:
                pass
            btn_row.addWidget(self.btn_generate_model_cfg)
            btn_row.addWidget(self.btn_copy_model_cfg)
            btn_row.addWidget(self.btn_clear_model_cfg)
            btn_row.addStretch(1)
            layout.addLayout(btn_row)

            # 初次更新
            try:
                self._update_model_config_preview()
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"创建Model右栏失败: {e}")
            except Exception:
                pass
        return panel

    def _refresh_model_param_panel(self):
        """根据 self.model_data.model_client.config 动态生成/刷新参数表单（与文档全参数字段对齐）。
        包含三项必填字段（model/base_url/api_key_env）作为表单顶部行，与其余参数同样样式。
        写回策略：必填项写入 config 根（model/base_url/api_key_env），其余写入 parameters；均刷新右侧 JSON 预览。
        """
        try:
            if not hasattr(self, '_model_param_form') or self._model_param_form is None:
                return
            # 清空旧项
            try:
                while self._model_param_form.rowCount() > 0:
                    self._model_param_form.removeRow(0)
            except Exception:
                pass

            # 读取 config 根（显示值：优先 model_client.config，回退顶层 config）
            data = getattr(self, 'model_data', None) or {}
            mc = data.get('model_client') or {}
            cfg_mc = mc.get('config') or {}
            top_cfg = data.get('config') or {}
            if not isinstance(cfg_mc, dict):
                cfg_mc = {}
            if not isinstance(top_cfg, dict):
                top_cfg = {}
            # 用于显示的只读视图
            def _cfg_get(key: str):
                v = cfg_mc.get(key)
                return v if (v is not None and v != '') else top_cfg.get(key)

            # 顶部三项：model / base_url / api_key_env
            from PySide6.QtWidgets import QLineEdit, QLabel as _QLabel
            # model
            w_model = QLineEdit()
            try:
                w_model.setText(str(_cfg_get('model') or ''))
                w_model.setPlaceholderText('例如：gpt-4o-mini / deepseek-chat / gemini-1.5-pro …')
            except Exception:
                pass
            def _on_model_text(t):
                try:
                    # 写入根 config
                    if not isinstance(getattr(self, 'model_data', None), dict):
                        self.model_data = {}
                    _mc = self.model_data.get('model_client') or {}
                    if not isinstance(_mc, dict):
                        _mc = {}
                    _cfg = _mc.get('config') or {}
                    if not isinstance(_cfg, dict):
                        _cfg = {}
                    _cfg['model'] = (t or '').strip()
                    _mc['config'] = _cfg
                    self.model_data['model_client'] = _mc
                except Exception:
                    pass
                self._update_model_config_preview()
            w_model.textChanged.connect(_on_model_text)
            self._model_param_form.addRow(_QLabel('模型ID (model):'), w_model)

            # base_url
            w_base = QLineEdit()
            try:
                w_base.setText(str(_cfg_get('base_url') or ''))
                w_base.setPlaceholderText('例如：https://api.openai.com/v1 或 http://127.0.0.1:11434/v1 …')
            except Exception:
                pass
            def _on_base_text(t):
                try:
                    if not isinstance(getattr(self, 'model_data', None), dict):
                        self.model_data = {}
                    _mc = self.model_data.get('model_client') or {}
                    if not isinstance(_mc, dict):
                        _mc = {}
                    _cfg = _mc.get('config') or {}
                    if not isinstance(_cfg, dict):
                        _cfg = {}
                    _cfg['base_url'] = (t or '').strip()
                    _mc['config'] = _cfg
                    self.model_data['model_client'] = _mc
                except Exception:
                    pass
                self._update_model_config_preview()
            w_base.textChanged.connect(_on_base_text)
            self._model_param_form.addRow(_QLabel('Base URL:'), w_base)

            # api_key_env
            w_keyenv = QLineEdit()
            try:
                w_keyenv.setText(str(_cfg_get('api_key_env') or ''))
                w_keyenv.setPlaceholderText('例如：OPENAI_API_KEY / DEEPSEEK_API_KEY / GOOGLE_API_KEY …')
            except Exception:
                pass
            def _on_keyenv_text(t):
                try:
                    if not isinstance(getattr(self, 'model_data', None), dict):
                        self.model_data = {}
                    _mc = self.model_data.get('model_client') or {}
                    if not isinstance(_mc, dict):
                        _mc = {}
                    _cfg = _mc.get('config') or {}
                    if not isinstance(_cfg, dict):
                        _cfg = {}
                    _cfg['api_key_env'] = (t or '').strip()
                    _mc['config'] = _cfg
                    self.model_data['model_client'] = _mc
                except Exception:
                    pass
                self._update_model_config_preview()
            w_keyenv.textChanged.connect(_on_keyenv_text)
            self._model_param_form.addRow(_QLabel('API Key 环境变量名:'), w_keyenv)
            self._model_param_editors = {}
            try:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.info(f"[ModelUI] 已添加必填项行：model/base_url/api_key_env")
            except Exception:
                pass

            # 读取当前 config
            cfg = {}
            try:
                data = getattr(self, 'model_data', None) or {}
                mc = data.get('model_client') or {}
                cfg = mc.get('config') or {}
                if not isinstance(cfg, dict):
                    cfg = {}
            except Exception:
                cfg = {}

            # 字段定义（与文档对齐，排除右侧三项）
            connection_fields = [
                ('organization', 'str'),
                ('timeout', 'float'),
                ('max_retries', 'int'),
                ('default_headers', 'json')
            ]
            generation_fields = [
                ('temperature', 'float'),
                ('max_tokens', 'int'),
                ('top_p', 'float'),
                ('frequency_penalty', 'float'),
                ('presence_penalty', 'float'),
                ('seed', 'int_or_null'),
                ('stop', 'json_or_str'),
                ('n', 'int'),
                ('user', 'str_or_null'),
                ('logit_bias', 'json_or_null'),
                ('response_format', 'json_or_str_or_null')
            ]
            model_info_fields = [
                (['model_info', 'vision'], 'bool'),
                (['model_info', 'function_calling'], 'bool'),
                (['model_info', 'json_output'], 'bool'),
                (['model_info', 'family'], 'str'),
                (['model_info', 'structured_output'], 'bool'),
                (['model_info', 'multiple_system_messages'], 'bool')
            ]
            autogen_fields = [
                ('model_capabilities', 'json_or_null'),
                ('add_name_prefixes', 'bool'),
                ('include_name_in_message', 'bool')
            ]

            defaults = {
                'organization': None,
                'timeout': 30.0,
                'max_retries': 3,
                'default_headers': {},
                'temperature': 0.7,
                'max_tokens': 2048,
                'top_p': 0.9,
                'frequency_penalty': 0.0,
                'presence_penalty': 0.0,
                'seed': None,
                'stop': None,
                'n': 1,
                'user': None,
                'logit_bias': None,
                'response_format': None,
                'model_capabilities': None,
                'add_name_prefixes': False,
                'include_name_in_message': True,
                ('model_info','vision'): False,
                ('model_info','function_calling'): True,
                ('model_info','json_output'): True,
                ('model_info','family'): 'unknown',
                ('model_info','structured_output'): False,
                ('model_info','multiple_system_messages'): False,
            }

            from PySide6.QtWidgets import QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QTextEdit, QLabel

            def _get_in(d: dict, path):
                try:
                    cur = d
                    for p in path:
                        if not isinstance(cur, dict):
                            return None
                        cur = cur.get(p)
                    return cur
                except Exception:
                    return None

            def _ensure_path(d: dict, path):
                cur = d
                for p in path[:-1]:
                    if not isinstance(cur.get(p), dict):
                        cur[p] = {}
                    cur = cur[p]
                return cur

            def _set_in(d: dict, path, value):
                parent = _ensure_path(d, path)
                parent[path[-1]] = value

            def _add_row(label: str, widget):
                self._model_param_form.addRow(label, widget)

            # 连接配置
            self._model_param_form.addRow(QLabel("连接配置"))
            for key, typ in connection_fields:
                val = cfg.get(key, defaults.get(key))
                if typ == 'float':
                    w = QDoubleSpinBox(); w.setRange(0.0, 600.0); w.setSingleStep(0.5)
                    try:
                        w.setValue(float(val) if val is not None else float(defaults.get(key, 0.0)))
                    except Exception:
                        w.setValue(float(defaults.get(key, 0.0)))
                    def _on(v, k=key):
                        cfg[k] = float(v); self._update_model_config_preview()
                    w.valueChanged.connect(_on)
                elif typ == 'int':
                    w = QSpinBox(); w.setRange(0, 100)
                    try:
                        fb = defaults.get(key, 0)
                        if fb is None:
                            fb = 0
                        w.setValue(int(val) if val is not None else int(fb))
                    except Exception:
                        try:
                            w.setValue(int(fb if fb is not None else 0))
                        except Exception:
                            w.setValue(0)
                    def _on(v, k=key):
                        cfg[k] = int(v); self._update_model_config_preview()
                    w.valueChanged.connect(_on)
                elif typ == 'json':
                    w = QTextEdit(); w.setPlaceholderText("{} 或 {\n  \"User-Agent\": \"AutoGen-Client\"\n}")
                    try:
                        import json as _json
                        w.setPlainText(_json.dumps(val if isinstance(val, dict) else (defaults.get(key) or {}), ensure_ascii=False, indent=2))
                    except Exception:
                        w.setPlainText("{}")
                    def _on_text(_, k=key, box=w):
                        import json as _json
                        try:
                            cfg[k] = _json.loads(box.toPlainText())
                        except Exception:
                            pass
                        self._update_model_config_preview()
                    w.textChanged.connect(_on_text)
                else:
                    w = QLineEdit(); w.setText("" if val is None else str(val))
                    def _on_text(t, k=key):
                        cfg[k] = (t or '').strip() or None; self._update_model_config_preview()
                    w.textChanged.connect(_on_text)
                _add_row(f"{key}:", w)
                self._model_param_editors[key] = w

            # 生成参数（严格遵循原始结构：model_client.config.parameters 下）
            self._model_param_form.addRow(QLabel("生成参数"))
            for key, typ in generation_fields:
                try:
                    # 从 parameters 优先读取
                    try:
                        params_cur = cfg.get('parameters') or {}
                        if not isinstance(params_cur, dict):
                            params_cur = {}
                    except Exception:
                        params_cur = {}
                    val = params_cur.get(key, defaults.get(key))
                    local_typ = typ  # 避免闭包晚绑定
                    if local_typ == 'float':
                        w = QDoubleSpinBox(); w.setRange(0.0, 2.0); w.setSingleStep(0.01)
                        try:
                            w.setValue(float(val) if val is not None else float(defaults.get(key, 0.0)))
                        except Exception:
                            w.setValue(float(defaults.get(key, 0.0)))
                        def _on(v, k=key):
                            # 写回到 parameters 路径
                            try:
                                self._update_model_param(k, float(v))
                            except Exception:
                                pass
                            self._update_model_config_preview()
                        w.valueChanged.connect(_on)
                    elif local_typ in ('int', 'int_or_null'):
                        w = QSpinBox(); w.setRange(0, 10_000_000)
                        try:
                            fb = defaults.get(key, 0)
                            if fb is None:
                                fb = 0
                            if isinstance(val, int):
                                w.setValue(val)
                            elif val is None:
                                w.setValue(int(fb))
                            else:
                                w.setValue(int(val))
                        except Exception:
                            try:
                                w.setValue(int(fb if fb is not None else 0))
                            except Exception:
                                w.setValue(0)
                        def _on(v, k=key, nullable=(local_typ=='int_or_null')):
                            try:
                                self._update_model_param(k, int(v) if not nullable or v != 0 else None)
                            except Exception:
                                pass
                            self._update_model_config_preview()
                        w.valueChanged.connect(_on)
                    elif local_typ in ('json_or_str', 'json_or_str_or_null'):
                        w = QLineEdit(); w.setText('' if val is None else (val if isinstance(val, str) else ''))
                        w.setPlaceholderText("可填写字符串；如需JSON结构请在其它区域维护")
                        def _on_text(t, k=key, lt=local_typ):
                            try:
                                self._update_model_param(k, t or (None if 'or_null' in lt else ''))
                            except Exception:
                                pass
                            self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    elif local_typ == 'json_or_null':
                        w = QTextEdit();
                        try:
                            import json as _json
                            w.setPlainText('' if val is None else _json.dumps(val, ensure_ascii=False, indent=2))
                        except Exception:
                            w.setPlainText('')
                        def _on_text(_, k=key, box=w):
                            import json as _json
                            txt = box.toPlainText().strip()
                            if not txt:
                                new_val = None
                            else:
                                try:
                                    new_val = _json.loads(txt)
                                except Exception:
                                    new_val = None
                            try:
                                self._update_model_param(k, new_val)
                            except Exception:
                                pass
                            self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    elif local_typ in ('str', 'str_or_null'):
                        w = QLineEdit(); w.setText('' if val is None else str(val))
                        def _on_text(t, k=key, lt=local_typ):
                            try:
                                self._update_model_param(k, (t or '').strip() or (None if 'or_null' in lt else ''))
                            except Exception:
                                pass
                            self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    else:
                        w = QLineEdit(); w.setText('' if val is None else str(val))
                        def _on_text(t, k=key):
                            try:
                                self._update_model_param(k, t)
                            except Exception:
                                pass
                            self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    _add_row(f"{key}:", w)
                    self._model_param_editors[key] = w
                except Exception as _e:
                    try:
                        if getattr(self, 'logger', None):
                            self.logger.warning(f"生成参数字段渲染失败: {key} / {typ} / {_e}")
                    except Exception:
                        pass

            # 模型能力信息
            self._model_param_form.addRow(QLabel("模型能力信息 (model_info)"))
            for path, typ in model_info_fields:
                try:
                    label = '.'.join(path)
                    val = _get_in(cfg, path)
                    if val is None:
                        val = defaults.get(tuple(path))
                    if typ == 'bool':
                        w = QCheckBox(); w.setChecked(bool(val))
                        def _on_check(state, p=path):
                            _set_in(cfg, p, bool(state)); self._update_model_config_preview()
                        w.stateChanged.connect(_on_check)
                    else:
                        w = QLineEdit(); w.setText('' if val is None else str(val))
                        def _on_text(t, p=path):
                            _set_in(cfg, p, (t or '').strip() or '')
                            self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    _add_row(f"{label}:", w)
                    self._model_param_editors[label] = w
                except Exception as _e:
                    try:
                        if getattr(self, 'logger', None):
                            self.logger.warning(f"model_info 字段渲染失败: {path} / {typ} / {_e}")
                    except Exception:
                        pass

            # AutoGen 特定
            self._model_param_form.addRow(QLabel("AutoGen 特定"))
            for key, typ in autogen_fields:
                try:
                    val = cfg.get(key, defaults.get(key))
                    if typ == 'bool':
                        w = QCheckBox(); w.setChecked(bool(val))
                        def _on_check(state, k=key):
                            cfg[k] = bool(state); self._update_model_config_preview()
                        w.stateChanged.connect(_on_check)
                    elif typ == 'json_or_null':
                        w = QTextEdit();
                        try:
                            import json as _json
                            w.setPlainText('' if val is None else _json.dumps(val, ensure_ascii=False, indent=2))
                        except Exception:
                            w.setPlainText('')
                        def _on_text(_, k=key, box=w):
                            import json as _json
                            txt = box.toPlainText().strip()
                            if not txt:
                                cfg[k] = None
                            else:
                                try:
                                    cfg[k] = _json.loads(txt)
                                except Exception:
                                    pass
                            self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    else:
                        w = QLineEdit(); w.setText('' if val is None else str(val))
                        def _on_text(t, k=key):
                            cfg[k] = (t or '').strip() or None; self._update_model_config_preview()
                        w.textChanged.connect(_on_text)
                    _add_row(f"{key}:", w)
                    self._model_param_editors[key] = w
                except Exception as _e:
                    try:
                        if getattr(self, 'logger', None):
                            self.logger.warning(f"AutoGen 特定字段渲染失败: {key} / {typ} / {_e}")
                    except Exception:
                        pass

            # 回写 cfg 到 self.model_data（保持引用一致）
            try:
                data = getattr(self, 'model_data', None) or {}
                mc = data.get('model_client') or {}
                mc['config'] = cfg
                data['model_client'] = mc
                self.model_data = data
            except Exception:
                pass
            try:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.info(f"[ModelUI] 参数表单构建完成，当前行数: {self._model_param_form.rowCount()}")
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"刷新模型参数面板失败: {e}")
            except Exception:
                pass
        return panel

    def _ensure_model_config_paths(self):
        """确保 self.model_data.model_client.config 字典路径存在。"""
        if not isinstance(getattr(self, 'model_data', None), dict):
            self.model_data = {}
        mc = self.model_data.get('model_client')
        if not isinstance(mc, dict):
            mc = {}
            self.model_data['model_client'] = mc
        cfg = mc.get('config')
        if not isinstance(cfg, dict):
            cfg = {}
            mc['config'] = cfg
        return cfg

    def on_copy_model_config(self):
        """复制右侧配置浏览框内容到剪贴板。"""
        try:
            if hasattr(self, 'model_config_preview') and self.model_config_preview is not None:
                text = self.model_config_preview.toPlainText() or ''
                from PySide6.QtWidgets import QApplication
                cb = QApplication.clipboard()
                cb.setText(text)
                try:
                    if hasattr(self, 'logger') and self.logger:
                        self.logger.info("已复制 model 配置到剪贴板")
                except Exception:
                    pass
                try:
                    ErrorHandler.handle_success(self, "成功", "配置已复制到剪贴板")
                except Exception:
                    pass
        except Exception as e:
            try:
                self.logger.warning(f"复制配置失败: {e}")
            except Exception:
                pass

    def on_clear_model_config(self):
        """清空右侧配置浏览框内容。"""
        try:
            if hasattr(self, 'model_config_preview') and self.model_config_preview is not None:
                self.model_config_preview.clear()
                try:
                    if hasattr(self, 'logger') and self.logger:
                        self.logger.info("已清空 model 配置预览")
                except Exception:
                    pass
        except Exception as e:
            try:
                self.logger.warning(f"清空配置失败: {e}")
            except Exception:
                pass
            
    def on_save_model_config(self):
        """保存右侧配置浏览框中的内容到本地 JSON 文件（弹窗选择路径，按原文保存）。"""
        try:
            # 读取预览内容
            if not hasattr(self, 'model_config_preview') or self.model_config_preview is None:
                return
            text = self.model_config_preview.toPlainText() or ''
            if not text.strip():
                ErrorHandler.handle_warning(self, "提示", "没有可保存的配置内容")
                return
            # 选择路径并保存
            from PySide6.QtWidgets import QFileDialog
            default_name = "model_config.json"
            base_dir = os.getcwd() if hasattr(os, 'getcwd') else ""
            path, _ = QFileDialog.getSaveFileName(
                self, "保存Model配置", os.path.join(base_dir, 'out', default_name), "JSON 文件 (*.json)"
            )
            if not path:
                return
            # 确保目录
            d = os.path.dirname(path)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            # 写入
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            if hasattr(self, 'logger') and self.logger:
                self.logger.info(f"已保存 model 配置到: {path}")
            ErrorHandler.handle_success(self, "成功", f"配置已保存到:\n{path}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "保存失败", e)

    def on_quick_save_model_config(self):
        """快速保存（原样，无对话框）：将预览文本直接写入固定路径 out/model_config.json。"""
        try:
            if not hasattr(self, 'model_config_preview') or self.model_config_preview is None:
                return
            text = self.model_config_preview.toPlainText() or ''
            if not text.strip():
                try:
                    ErrorHandler.handle_warning(self, "提示", "没有可保存的配置内容")
                except Exception:
                    pass
                return
            # 目标路径：项目根/out/model_config.json
            try:
                base_dir = os.getcwd()
            except Exception:
                base_dir = '.'
            out_dir = os.path.join(base_dir, 'out')
            try:
                if not os.path.exists(out_dir):
                    os.makedirs(out_dir, exist_ok=True)
            except Exception:
                pass
            out_path = os.path.join(out_dir, 'model_config.json')
            try:
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                try:
                    if hasattr(self, 'logger') and self.logger:
                        self.logger.info(f"已快速保存 model 配置到: {out_path}")
                except Exception:
                    pass
                try:
                    ErrorHandler.handle_success(self, "成功", f"配置已保存到:\n{out_path}")
                except Exception:
                    pass
            except Exception as e:
                try:
                    ErrorHandler.handle_ui_error(self, "保存失败", e)
                except Exception:
                    pass
        except Exception as e:
            try:
                self.logger.warning(f"快速保存失败: {e}")
            except Exception:
                pass

    def _create_agent_tab(self):
        """创建Agent页面"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)
        # 左栏：本地文件 + 按钮行 + 对话区（移除“Agent选择器”与“左侧系统消息编辑框”）
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel)
        # 顶部“选择Agent”下拉已移除，避免干扰生成逻辑

        # 恢复：本地文件路径 + 浏览按钮
        path_row = QHBoxLayout()
        from PySide6.QtWidgets import QLineEdit
        self.agent_path = QLineEdit()
        self.agent_path.setPlaceholderText("选择或输入本地Agent JSON路径…")
        btn_agent_browse = QPushButton("浏览…")
        try:
            btn_agent_browse.clicked.connect(self.on_browse_agent)
        except Exception:
            pass
        path_row.addWidget(self.agent_path)
        path_row.addWidget(btn_agent_browse)
        left_layout.addLayout(path_row)
        # 已移除：初始化Agent下拉
        # （删除）系统消息左侧编辑框：统一使用右侧表单 det_system_message 管理 system_message
        # 按钮行
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.on_save_agent)
        # 保留占位的隐藏“运行”按钮以兼容旧逻辑（仍隐藏，不在UI展示）
        run_btn = QPushButton("运行")
        run_btn.setVisible(False)
        run_btn.setEnabled(False)
        # 新增：清空按钮（与“保存”并排）
        clear_btn = QPushButton("清空")
        try:
            clear_btn.clicked.connect(self._on_agent_clear_all)
        except Exception:
            pass

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(clear_btn)
        # 保留占位的隐藏“运行”按钮以兼容旧逻辑（仍隐藏，不在UI展示）
        btn_layout.addWidget(run_btn)
        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)
        # 与 Team 页一致：在系统消息与按钮区后加入输入/输出对话区
        self._create_agent_chat_area(left_layout)
        
        # 右栏：四个子页签
        right_panel = self._create_agent_right_tabs()
        # 组装左右两栏
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        # 自适应与交互优化
        try:
            left_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            right_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(6)
        except Exception:
            pass
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)
        # 加入主Tab
        self.tabs.addTab(widget, "Agent")

    def _on_agent_clear_all(self):
        """清空 Agent 页面的主要 UI 与运行内存（不写盘）。"""
        try:
            # 左侧：路径、系统消息、对话输入输出
            try:
                if hasattr(self, 'agent_path') and self.agent_path is not None:
                    self.agent_path.setText("")
            except Exception:
                pass
            # 已移除左侧 system_message 编辑框，无需清理
            try:
                if hasattr(self, 'agent_chat_input') and self.agent_chat_input is not None:
                    self.agent_chat_input.clear()
            except Exception:
                pass
            try:
                if hasattr(self, 'agent_chat_output') and self.agent_chat_output is not None:
                    self.agent_chat_output.clear()
            except Exception:
                pass

            # 右侧：预览与只读信息
            try:
                if hasattr(self, 'asst_mem_config_preview') and self.asst_mem_config_preview is not None:
                    self.asst_mem_config_preview.blockSignals(True)
                    self.asst_mem_config_preview.clear()
                    self.asst_mem_config_preview.blockSignals(False)
                    # 重置预览来源锁
                    try:
                        self._config_preview_source = None
                    except Exception:
                        pass
                    # 重置预览标题
                    try:
                        if hasattr(self, 'config_panel') and self.config_panel is not None:
                            self.config_panel.setTitle("配置文件预览")
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if hasattr(self, 'asst_model_env_info') and self.asst_model_env_info is not None:
                    self.asst_model_env_info.blockSignals(True)
                    self.asst_model_env_info.clear()
                    self.asst_model_env_info.blockSignals(False)
            except Exception:
                pass

            # 右侧详情表单：名称/描述/模型选择
            try:
                if hasattr(self, 'det_name') and self.det_name is not None:
                    self.det_name.blockSignals(True)
                    self.det_name.setText("")
                    self.det_name.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_description') and self.det_description is not None:
                    self.det_description.blockSignals(True)
                    self.det_description.clear()
                    self.det_description.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_model') and self.det_model is not None:
                    # 兼容 QComboBox/QLineEdit 两种形态
                    from PySide6.QtWidgets import QComboBox, QLineEdit
                    if isinstance(self.det_model, QComboBox):
                        self.det_model.blockSignals(True)
                        self.det_model.setCurrentIndex(-1)
                        self.det_model.setEditText("")
                        self.det_model.blockSignals(False)
                    elif isinstance(self.det_model, QLineEdit):
                        self.det_model.blockSignals(True)
                        self.det_model.setText("")
                        self.det_model.blockSignals(False)
            except Exception:
                pass

            # 右下清单列表（工具/记忆/MCP 等）
            for attr in ('right_tools_list', 'right_vs_list', 'right_mcp_list', 'agent_import_list'):
                try:
                    w = getattr(self, attr, None)
                    if w is not None:
                        w.clear()
                except Exception:
                    pass

            # 清空导入缓存，避免遗留的工具/向量库/MCP 在生成时被误合并
            try:
                if hasattr(self, '_agent_import_cache') and isinstance(self._agent_import_cache, dict):
                    self._agent_import_cache.clear()
                else:
                    self._agent_import_cache = {}
            except Exception:
                pass

            # 清空运行内存：agent_data / model_data / 最近导入模型 / 运行源 / 内存配置路径
            try:
                self.agent_data = {}
            except Exception:
                pass
            try:
                self.model_data = {}
            except Exception:
                pass
            try:
                if hasattr(self, '_last_imported_model_client'):
                    self._last_imported_model_client = None
            except Exception:
                pass
            try:
                self._exec_config_source = 'local'
            except Exception:
                pass
            try:
                self._mem_agent_config_path = ''
            except Exception:
                pass
            try:
                # 已移除 Agent 选择器
                pass
            except Exception:
                pass

            try:
                ErrorHandler.handle_success(self, "已清空", "已清空参数与内存（已重置选择器与预览）")
            except Exception:
                pass
        except Exception as e:
            try:
                ErrorHandler.handle_ui_error(self, "清空失败", e)
            except Exception:
                pass

    def _refresh_model_selector(self):
        """刷新Model仓库下拉列表（仅文件系统）。"""
        try:
            if not hasattr(self, 'model_selector'):
                return
            self.model_selector.blockSignals(True)
            self.model_selector.clear()
            items = []
            # 仅从文件系统读取模型配置
            try:
                base_dir = Path(__file__).parent.parent.parent
                models_dir = base_dir / 'config' / 'models'
                if models_dir.exists() and models_dir.is_dir():
                    for p in sorted(models_dir.glob('*.json')):
                        try:
                            with p.open('r', encoding='utf-8') as f:
                                obj = json.load(f)
                                if isinstance(obj, dict):
                                    data = dict(obj)
                                    data.setdefault('__path', str(p))
                                    if not data.get('name'):
                                        data['name'] = p.stem
                                    items.append(data)
                        except Exception as e:
                            self.logger.warning(f"加载模型文件{p}失败: {e}")
            except Exception as e:
                self.logger.warning(f"扫描 config/models 失败: {e}")
            for it in items:
                name = str(it.get('name') or it.get('id') or 'unnamed')
                self.model_selector.addItem(name, userData=it)
        except Exception as e:
            self.logger.warning(f"刷新Model下拉失败: {e}")
        finally:
            try:
                self.model_selector.blockSignals(False)
                if items:
                    self.model_selector.setCurrentIndex(0)
                    try:
                        self._on_model_selector_changed(0)
                    except Exception:
                        pass
            except Exception:
                pass

    def _on_model_selector_changed(self, idx: int):
        """选择Model后，加载到右侧面板并同步到当前会话。"""
        try:
            if idx < 0 or not hasattr(self, 'model_selector'):
                return
            data = self.model_selector.currentData()
            if not isinstance(data, dict):
                return
            # 优先从磁盘重新读取所选文件，确保获得“本地模型配置文件”的最新内容
            try:
                cfg_path = str(data.get('__path') or data.get('_config_path') or '')
            except Exception:
                cfg_path = ''
            loaded = None
            if cfg_path:
                try:
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                    # 保留源路径以便调试/后续操作
                    if isinstance(loaded, dict):
                        loaded['__path'] = cfg_path
                except Exception as e:
                    try:
                        # 回退使用下拉携带的数据
                        self.logger.warning(f"读取模型文件失败，使用下拉缓存数据: {e}")
                    except Exception:
                        pass
            # 若读取成功则使用读取结果，否则使用下拉缓存的数据
            self.model_data = loaded if isinstance(loaded, dict) else data
            try:
                self.backend = None
                if hasattr(self, 'logger') and self.logger:
                    self.logger.info("Model 已切换，已重置后端实例")
            except Exception:
                pass
            # 调试：输出切换后的 Model 名称/ID
            try:
                _name = str((self.model_data or {}).get('name') or (self.model_data or {}).get('id') or '')
                _mc = dict(((self.model_data or {}).get('model_client') or {}).get('config') or {})
                _model_id = str(_mc.get('model') or '')
                print(f"[SWITCH] model selected -> name={_name or '-'} | model_id={_model_id or '-'}")
            except Exception:
                pass
            sysmsg = str((self.model_data or {}).get('system_message', '') or '')
            if hasattr(self, 'system_prompt') and isinstance(self.system_prompt, QTextEdit):
                self.system_prompt.blockSignals(True)
                self.system_prompt.setPlainText(sysmsg)
                self.system_prompt.blockSignals(False)
            # 刷新中部参数表与右侧预览
            try:
                self._refresh_model_param_panel()
                self._refresh_model_right_panel()
            except Exception:
                pass
        except Exception as e:
            self.logger.warning(f"更新Model配置失败: {e}")


    def on_browse_model(self):
        """浏览选择本地模型 JSON 文件，并加载到当前会话。"""
        try:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "选择模型 JSON 文件", os.getcwd(), "JSON Files (*.json)"
            )
            if not path:
                return
            try:
                if hasattr(self, 'model_path') and self.model_path is not None:
                    self.model_path.setText(path)
            except Exception:
                pass
            self.on_load_model_path()
        except Exception as e:
            try:
                self.logger.warning(f"浏览模型文件失败: {e}")
            except Exception:
                pass

    def on_load_model_path(self):
        """从左侧输入框指定的路径读取本地模型配置，刷新 UI 并强制回填必填项。"""
        try:
            path = ''
            try:
                if hasattr(self, 'model_path') and self.model_path is not None:
                    path = (self.model_path.text() or '').strip()
            except Exception:
                path = ''
            if not path:
                return
            obj = None
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
            except Exception as e:
                ErrorHandler.handle_warning(self, "提示", f"读取模型文件失败: {str(e)[:200]}")
                return
            if not isinstance(obj, dict):
                ErrorHandler.handle_warning(self, "提示", "模型文件格式错误：根应为 JSON 对象")
                return
            # 设置当前模型数据
            self.model_data = dict(obj)
            try:
                self.model_data['__path'] = path
            except Exception:
                pass
            # 回填系统提示（若存在）
            try:
                sysmsg = str((self.model_data or {}).get('system_message', '') or '')
                if hasattr(self, 'system_prompt') and isinstance(self.system_prompt, QTextEdit):
                    self.system_prompt.blockSignals(True)
                    self.system_prompt.setPlainText(sysmsg)
                    self.system_prompt.blockSignals(False)
            except Exception:
                pass
            # 刷新参数面板、预览
            try:
                self._refresh_model_param_panel()
            except Exception:
                pass
            try:
                self._refresh_model_right_panel()
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"从路径加载模型失败: {e}")
            except Exception:
                pass

    def _update_model_config_preview(self):
        """根据当前 self.model_data 生成美化 JSON 并写入右侧预览框。
        - 满足“将读入的配置文件写入右侧栏内的配置文件浏览框内”的需求，显示完整配置。
        - 只写预览框，不落盘。
        """
        try:
            data = getattr(self, 'model_data', None) or {}
            try:
                import json as _json
                pretty = _json.dumps(data if isinstance(data, dict) else {}, ensure_ascii=False, indent=2)
            except Exception:
                try:
                    pretty = str(data)
                except Exception:
                    pretty = '{}'
            if hasattr(self, 'model_config_preview') and self.model_config_preview is not None:
                try:
                    self.model_config_preview.blockSignals(True)
                except Exception:
                    pass
                self.model_config_preview.setPlainText(pretty)
                try:
                    self.model_config_preview.blockSignals(False)
                except Exception:
                    pass
        except Exception as e:
            try:
                self.logger.warning(f"更新Model配置预览失败: {e}")
            except Exception:
                pass
        
    def _refresh_model_right_panel(self):
        """[已迁移] 右侧不再承载必填项，仅保留预览；此方法兼容性保留为更新预览。"""
        try:
            self._update_model_config_preview()
        except Exception as e:
            try:
                self.logger.warning(f"刷新Model右侧预览失败: {e}")
            except Exception:
                pass


    def on_generate_model_config(self):
        """生成 model 配置（对齐本地知识库“全量模型参数样例”的完整Schema）。
        规则：
        - 顶层仅输出 provider、component_type(=model) 与 config。
        - config 内输出全量字段；若当前内存未提供，则赋值为 None；
        - 仅保留 Schema 中定义的字段，不输出非标准字段（如 model_client、__path、label、description 等）。
        - model_info 仅保留允许键：vision/function_calling/json_output/family/structured_output/multiple_system_messages，
          未提供时使用样例默认值（均为布尔/字符串默认）。
        - 不再做 api_key 的环境变量注入/占位符；如未提供则为 None。
        """
        try:
            # 1) 清空浏览框
            try:
                if hasattr(self, 'model_config_preview') and self.model_config_preview is not None:
                    self.model_config_preview.clear()
            except Exception:
                pass

            # 2) 汇总当前页面内的配置数据
            base = getattr(self, 'model_data', None) or {}
            if not isinstance(base, dict):
                base = {}
            # 顶层 name/id/label/description 等均不在标准导出范围
            mc = base.get('model_client') or {}
            if not isinstance(mc, dict):
                mc = {}
            mcc = mc.get('config') or {}
            if not isinstance(mcc, dict):
                mcc = {}
            top_cfg = base.get('config') or {}
            if not isinstance(top_cfg, dict):
                top_cfg = {}

            def _get(key, default=None):
                v = mcc.get(key)
                if v is None or v == '':
                    v = top_cfg.get(key, default)
                return v if v is not None else default

            provider = (mc.get('provider') or base.get('provider') or top_cfg.get('provider')
                        or 'autogen_ext.models.openai.OpenAIChatCompletionClient')
            model_id = _get('model', '')
            base_url = _get('base_url', '')
            # api_key_env 不在导出中使用；支持 api_key 明文（若存在），否则尝试从环境变量注入
            api_key = _get('api_key', '')
            model_info = _get('model_info', {})
            if not isinstance(model_info, dict):
                model_info = {}
            # 仅保留有效字段；缺失补齐默认
            default_model_info = {
                "vision": False,
                "function_calling": False,
                "json_output": False,
                "family": "unknown",
                "structured_output": False,
                "multiple_system_messages": False,
            }
            # 以已有字段优先，缺省补齐（剔除无效字段）
            mi = dict(default_model_info)
            try:
                for k, v in (model_info or {}).items():
                    if k in default_model_info:
                        mi[k] = v
            except Exception:
                pass
            model_info = mi
            # 若 family 仍为 unknown/空，则基于 base_url/provider/model 启发式推断（moonshot/deepseek/openai/anthropic/dashscope/qwen）
            try:
                fam_cur = str(model_info.get('family') or '').strip().lower()
                if not fam_cur or fam_cur == 'unknown':
                    hay = ' '.join([
                        str(base_url or '').lower(),
                        str(provider or '').lower(),
                        str(model_id or '').lower(),
                    ])
                    if 'moonshot' in hay:
                        model_info['family'] = 'moonshot'
                    elif 'deepseek' in hay:
                        model_info['family'] = 'deepseek'
                    elif 'anthropic' in hay:
                        model_info['family'] = 'anthropic'
                    elif 'dashscope' in hay or 'qwen' in hay:
                        model_info['family'] = 'qwen'
                    elif 'openai' in hay:
                        model_info['family'] = 'openai'
            except Exception:
                pass
            timeout = _get('timeout', 30.0)
            try:
                timeout = float(timeout)
            except Exception:
                timeout = 30.0
            max_retries = _get('max_retries', 3)
            try:
                max_retries = int(max_retries)
            except Exception:
                max_retries = 3
            parameters = _get('parameters', {})
            if not isinstance(parameters, dict):
                parameters = {}
            # 将 parameters 拍平到根级；过滤保留的根级关键字，防止重复/错误位置
            reserved_root = {"model", "base_url", "api_key", "timeout", "max_retries", "organization", "model_info"}
            flat_params = {k: v for k, v in parameters.items() if k not in reserved_root}

            # 额外合并来源：1) 直接在 config 根级的动态字段；2) UI 实时编辑器的值
            # 1) 合并来自 mcc/top_cfg 的其余非保留字段（避免遗漏）
            extra_from_cfg = {}
            try:
                for k, v in (mcc or {}).items():
                    if k in (reserved_root | {"parameters", "api_key_env"}):
                        continue
                    extra_from_cfg[k] = v
            except Exception:
                pass
            try:
                for k, v in (top_cfg or {}).items():
                    if k in (reserved_root | {"parameters", "api_key_env"}):
                        continue
                    # 不覆盖 mcc 同名项
                    if k not in extra_from_cfg:
                        extra_from_cfg[k] = v
            except Exception:
                pass

            # 2) 合并来自 UI 表单编辑器（若存在）：统一读取控件值
            extra_from_ui = {}
            try:
                editors = getattr(self, '_model_param_editors', {}) or {}
                for k, w in editors.items():
                    if not k or k in {"api_key_env"}:  # 严禁导出 api_key_env
                        continue
                    try:
                        val = None
                        wt = type(w).__name__
                        if wt in ("QLineEdit",):
                            val = w.text()
                        elif wt in ("QTextEdit",):
                            val = w.toPlainText()
                        elif wt in ("QCheckBox",):
                            val = bool(w.isChecked())
                        elif wt in ("QSpinBox", "QSlider"):
                            val = int(w.value())
                        elif wt in ("QDoubleSpinBox",):
                            val = float(w.value())
                        elif wt in ("QComboBox",):
                            val = w.currentText()
                        else:
                            # 尝试通用属性
                            if hasattr(w, 'value'):
                                val = w.value()
                            elif hasattr(w, 'text'):
                                val = w.text()
                        # 规范：空字符串视为 None
                        if isinstance(val, str):
                            val = val.strip()
                            if val == "":
                                val = None
                        extra_from_ui[k] = val
                    except Exception:
                        continue
            except Exception:
                pass

            # 可选的 organization（若提供，放在根级）
            organization = _get('organization', None)

            # 按你的要求：若未显式提供 api_key，但表单/配置存在 api_key_env，则导出占位符 ${ENV_NAME}
            if not api_key:
                env_from_ui = None
                try:
                    editors = getattr(self, '_model_param_editors', {}) or {}
                    w_env = editors.get('api_key_env')
                    if w_env is not None:
                        t = None
                        if hasattr(w_env, 'text'):
                            t = w_env.text()
                        elif hasattr(w_env, 'toPlainText'):
                            t = w_env.toPlainText()
                        if isinstance(t, str):
                            t = t.strip()
                        env_from_ui = t or None
                except Exception:
                    env_from_ui = None
                env_name = env_from_ui or _get('api_key_env', '')
                if isinstance(env_name, str):
                    env_name = env_name.strip()
                if env_name:
                    api_key = f"${{{env_name}}}"

            # 3) 规范化输出：provider + component_type + config（完整键集合，未提供时为 null）
            # 定义完整键清单（依据本地知识库）
            full_keys = [
                "model","api_key","base_url","organization","timeout","max_retries",
                "frequency_penalty","logit_bias","max_tokens","n","presence_penalty",
                "response_format","seed","stop","temperature","top_p","user",
                "stream_options","parallel_tool_calls","model_capabilities","add_name_prefixes",
                "include_name_in_message","default_headers"
            ]
            # 预填 null
            config_obj = {k: None for k in full_keys}
            # 填充必备与已知值
            if model_id:
                config_obj["model"] = model_id
            config_obj["api_key"] = api_key if api_key else None
            config_obj["base_url"] = base_url or None
            config_obj["organization"] = organization if organization else None
            config_obj["timeout"] = timeout if timeout is not None else None
            config_obj["max_retries"] = max_retries if max_retries is not None else None
            # JSON 类型字段白名单（字符串时尝试解析为对象/数组）
            _json_keys = {"default_headers", "logit_bias", "response_format", "stream_options", "model_capabilities", "stop"}

            def _normalize_value(key, val):
                try:
                    if isinstance(val, str):
                        s = val.strip()
                        if s == "":
                            return None
                        if key in _json_keys and (s.startswith("{") or s.startswith("[")):
                            import json as _json
                            return _json.loads(s)
                    return val
                except Exception:
                    return val

            # 拍平参数写入（不会覆盖上述已设置的关键值），并处理 model_info.* 映射
            for k, v in flat_params.items():
                if isinstance(k, str) and k.startswith("model_info."):
                    subk = k.split(".", 1)[1]
                    if subk in model_info:
                        model_info[subk] = _normalize_value(subk, v)
                    continue
                v2 = _normalize_value(k, v)
                if k in config_obj:
                    if config_obj[k] is None:
                        config_obj[k] = v2
                else:
                    # 允许其他未列出的参数直接并入（兼容将来扩展）
                    config_obj[k] = v2

            # 并入来自 mcc/top_cfg 的其余字段（避免遗漏），不覆盖已设置值；处理 model_info.*
            for k, v in (extra_from_cfg or {}).items():
                if k in {"api_key_env", "parameters", "model_info"}:
                    continue
                if isinstance(k, str) and k.startswith("model_info."):
                    subk = k.split(".", 1)[1]
                    if subk in model_info:
                        model_info[subk] = _normalize_value(subk, v)
                    continue
                v2 = _normalize_value(k, v)
                if k in config_obj:
                    if config_obj[k] is None:
                        config_obj[k] = v2
                else:
                    config_obj[k] = v2

            # 并入来自 UI 编辑器的值（优先级最高），允许覆盖 null；处理 model_info.*
            for k, v in (extra_from_ui or {}).items():
                if k in {"api_key_env", "parameters", "model_info"}:
                    continue
                if isinstance(k, str) and k.startswith("model_info."):
                    subk = k.split(".", 1)[1]
                    if subk in model_info and v is not None:
                        model_info[subk] = _normalize_value(subk, v)
                    continue
                v2 = _normalize_value(k, v)
                if k in config_obj:
                    if v2 is not None:
                        config_obj[k] = v2
                else:
                    config_obj[k] = v2
            # 始终输出 model_info（扩展后的有效字段集）
            config_obj["model_info"] = model_info

            cfg_out = {
                "provider": provider,
                "component_type": "model",
                "config": config_obj,
            }

            # 4) 写入预览
            try:
                import json as _json
                pretty = _json.dumps(cfg_out, ensure_ascii=False, indent=2)
            except Exception:
                try:
                    pretty = str(cfg_out)
                except Exception:
                    pretty = '{}'
            try:
                if hasattr(self, 'model_config_preview') and self.model_config_preview is not None:
                    self.model_config_preview.setPlainText(pretty)
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"生成model配置失败: {e}")
            except Exception:
                pass

    def _update_model_param(self, key: str, value):
        """将参数更新到内存中的 self.model_data（严格原始结构路径）。
        - 路径：model_data['model_client']['config']['parameters'][key] = value
        - 仅在用户显式变更时写入；允许按需创建缺失的嵌套字典，但不迁移或重命名其他字段。
        """
        try:
            if not isinstance(key, str) or key.strip() == '':
                return
            if not isinstance(getattr(self, 'model_data', None), dict):
                return
            mc = self.model_data.get('model_client')
            if not isinstance(mc, dict):
                mc = {}
                self.model_data['model_client'] = mc
            cfg = mc.get('config')
            if not isinstance(cfg, dict):
                cfg = {}
                mc['config'] = cfg
            params = cfg.get('parameters')
            if not isinstance(params, dict):
                params = {}
                cfg['parameters'] = params
            # 直接写入用户提供值（不做归一化）
            params[key] = value
            # 可选：日志记录，便于追踪
            try:
                self.logger.info(f"Model参数已更新: {key}={value}")
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"更新模型参数失败: {e}")
            except Exception:
                pass

    def _refresh_agent_selector(self):
        """刷新Agent仓库下拉列表（仅文件系统 config/agents；tooltip 显示源路径）。"""
        try:
            if not hasattr(self, 'agent_selector'):
                return
            self.agent_selector.blockSignals(True)
            self.agent_selector.clear()
            items = []
            try:
                base_dir = Path(__file__).parent.parent.parent
                agents_dir = base_dir / 'config' / 'agents'
                if agents_dir.exists() and agents_dir.is_dir():
                    for p in sorted(agents_dir.glob('*.json')):
                        try:
                            with p.open('r', encoding='utf-8') as f:
                                obj = json.load(f)
                                if isinstance(obj, dict):
                                    data = dict(obj)
                                    # 强制使用实际文件路径覆盖_config_path，确保显示正确
                                    data['_config_path'] = str(p)
                                    items.append(data)
                        except Exception:
                            continue
            except Exception as e:
                self.logger.warning(f"扫描 config/agents 失败: {e}")
            for it in items:
                # 显示名固定为完整文件名，包含.json扩展名
                try:
                    cfg_path = str(it.get('_config_path', ''))
                    filename = Path(cfg_path).name if cfg_path else ''
                    print(f"[DEBUG] Agent文件路径: {cfg_path}")
                    print(f"[DEBUG] Agent文件名: {filename}")
                except Exception as e:
                    print(f"[DEBUG] 获取文件名异常: {e}")
                    filename = ''
                label = filename or 'unnamed'
                print(f"[DEBUG] 添加到选择器的标签: {label}")
                self.agent_selector.addItem(label, userData=it)
                try:
                    idx2 = self.agent_selector.count() - 1
                    src = str(it.get('_config_path', ''))
                    if src:
                        self.agent_selector.setItemData(idx2, src, role=Qt.ItemDataRole.ToolTipRole)
                except Exception:
                    pass
        except Exception as e:
            self.logger.warning(f"刷新Agent下拉失败: {e}")
        finally:
            try:
                self.agent_selector.blockSignals(False)
                # 按最新规范：默认不自动选择任何Agent，避免“默认加载的Agent”干扰后续生成
                self.agent_selector.setCurrentIndex(-1)
            except Exception:
                pass

    def _on_agent_selector_changed(self, idx: int):
        """选择Agent后：刷新右侧相关区域（只读展示原始配置）。"""
        try:
            if idx < 0 or not hasattr(self, 'agent_selector'):
                return
            data = self.agent_selector.currentData()
            if not isinstance(data, dict):
                return
            # 更新当前Agent数据（仅内存，不写盘）
            self.agent_data = data
            # 切换来源为 local：选择Agent后优先使用本地所选配置
            try:
                # 确保清除内存配置的优先级
                self._exec_config_source = 'local'
                # 确保获取到实际选择的配置
                if hasattr(self, 'agent_chat_output'):
                    self.agent_chat_output.append(f"[信息] 已选择Agent: {data.get('name', '未命名')}\n")
                try:
                    print("[SWITCH] exec_source := local (因用户切换Agent)")
                except Exception:
                    pass
            except Exception:
                pass
            # 调试：输出切换后的 Agent 名称与其模型名
            try:
                _agent_name = str((self.agent_data or {}).get('name') or '')
                _mc = dict(((self.agent_data or {}).get('model_client') or {}).get('config') or {})
                _model_id = str(_mc.get('model') or '')
                print(f"[SWITCH] agent selected -> agent={_agent_name or '-'} | model={_model_id or '-' }")
            except Exception:
                pass
            # 注意：根据最新规则，选择Agent不再写入“配置文件预览”以避免与“导入/生成”逻辑相互干扰。
            # 将当前选择的文件路径写入左侧路径框，便于用户确认
            try:
                if hasattr(self, 'agent_path'):
                    src_path = str((self.agent_data or {}).get('_config_path') or '')
                    self.agent_path.setText(src_path)
            except Exception:
                pass
            # 刷新：右下记忆（memory/vectorstores）
            try:
                if hasattr(self, 'right_vs_list'):
                    self._refresh_right_vectorstores_tab()
            except Exception:
                pass
            # 刷新：工具列表（tools）
            try:
                if hasattr(self, 'right_tools_list'):
                    self._refresh_right_tools_tab()
            except Exception:
                pass
            # 刷新：MCP 清单
            try:
                if hasattr(self, 'right_mcp_list'):
                    self._refresh_right_mcp_tab()
            except Exception:
                pass
            # 刷新：Agent 详情表单并同步模型选择器
            try:
                # 优先切换到 AssistantAgent 页，确保用户可见模型选择器
                try:
                    if hasattr(self, 'agent_right_tabs'):
                        self.agent_right_tabs.setCurrentIndex(0)
                except Exception:
                    pass
                # 先刷新候选，再回填表单
                try:
                    self._refresh_det_model_candidates()
                except Exception:
                    pass
                # 显式将模型名写入下拉，避免候选集缺失时不显示
                try:
                    model_name = self._extract_model_name_from_agent(self.agent_data)
                    if hasattr(self, 'det_model') and model_name:
                        found = False
                        for i in range(self.det_model.count()):
                            if self.det_model.itemText(i) == model_name:
                                found = True
                                break
                        if not found:
                            self.det_model.addItem(model_name)
                        self.det_model.setCurrentText(model_name)
                except Exception:
                    pass
                # 最后统一回填其他字段
                self._refresh_right_agent_detail_tab()
            except Exception:
                pass
        except Exception as e:
            self.logger.warning(f"处理Agent选择变化失败: {e}")

    def _create_agent_right_tabs(self) -> QWidget:
        """创建Agent页右侧四个选项卡容器：AssistantAgent / MultimodalWebSurfer / SocietyOfMindAgent / OpenAIAgent"""
        container = QWidget()
        v = QVBoxLayout(container)
        
        # 关键：右侧容器零边距/零间距，并占满可用空间
        try:
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass

        self.agent_right_tabs = QTabWidget(container)
        try:
            self.agent_right_tabs.currentChanged.connect(self._on_right_tab_changed)
            # TabWidget 本身也需要可扩展
            self.agent_right_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass

        # Tab 1: AssistantAgent（左：基础表单；右：列表参数）
        tab_asst = QWidget(); split_asst = QSplitter(Qt.Orientation.Horizontal, tab_asst)
        # 关键：页签容器采用零边距布局承载splitter
        try:
            _lyt_asst = QVBoxLayout(tab_asst)
            _lyt_asst.setContentsMargins(0, 0, 0, 0)
            _lyt_asst.setSpacing(0)
            _lyt_asst.addWidget(split_asst)
        except Exception:
            pass
        # 左（可滚动）
        asst_left = QWidget(); asst_form = QFormLayout(asst_left)
        # name（必填）
        self.det_name = QLineEdit(); self.det_name.setPlaceholderText("Agent名称（name）")
        # 移除非标准：role / agent_type
        # 模型（model_client.model）在右侧管理，仅此处提供选择器以便只读展示/切换
        self.det_model = QComboBox(); self.det_model.setEditable(True)
        # 模型选择器顶对齐 + 字号增加两号
        try:
            _f = self.det_model.font(); _f.setPointSize(max(1, _f.pointSize() + 2)); self.det_model.setFont(_f)
        except Exception:
            pass
        try:
            self._refresh_det_model_candidates()
        except Exception:
            pass
        # 移除非标准：temperature/top_p/max_tokens/presence_penalty/frequency_penalty（属于 model_client.config 超参）

        # AssistantAgentConfig 关键字段（严格对齐 0.7.1）
        # description（必填）
        self.det_description = QTextEdit();
        try:
            self.det_description.setMaximumHeight(80)
        except Exception:
            pass
        self.det_description.setPlaceholderText("description：Agent的描述信息（字符串）")
        # system_message（可选）
        self.det_system_message = QTextEdit()
        try:
            self.det_system_message.setMaximumHeight(80)
        except Exception:
            pass
        self.det_system_message.setPlaceholderText("system_message：系统提示（字符串，部分模型可为 None）")
        # reflect_on_tool_use
        self.det_reflect_on_tool_use = QCheckBox("reflect_on_tool_use：工具调用后进行反思")
        # tool_call_summary_format
        self.det_tool_call_summary_format = QTextEdit()
        try:
            self.det_tool_call_summary_format.setMaximumHeight(60)
        except Exception:
            pass
        self.det_tool_call_summary_format.setPlaceholderText("tool_call_summary_format：工具调用摘要格式（字符串模板）")
        # model_client_stream
        self.det_model_client_stream = QCheckBox("model_client_stream：启用流式输出（默认False）")
        # max_tool_iterations
        self.det_max_tool_iterations = QSpinBox(); self.det_max_tool_iterations.setRange(1, 99); self.det_max_tool_iterations.setValue(1)
        # model_context（显示为组件名/类型，通常只读展示）
        self.det_model_context = QLineEdit(); self.det_model_context.setPlaceholderText("model_context：模型上下文组件（只读/组件名）"); self.det_model_context.setReadOnly(True)
        # metadata（以JSON字符串形式编辑，前端不做隐式转换）
        self.det_metadata = QTextEdit()
        try:
            self.det_metadata.setMaximumHeight(80)
        except Exception:
            pass
        self.det_metadata.setPlaceholderText("metadata：键值对（JSON字符串，例如 {\"domain\":\"test\"} ）")
        # structured_message_factory（显示为组件名/类型，通常只读展示）
        self.det_structured_message_factory = QLineEdit(); self.det_structured_message_factory.setPlaceholderText("structured_message_factory：结构化消息工厂（只读/组件名）"); self.det_structured_message_factory.setReadOnly(True)

        btn_row = QHBoxLayout()
        # 仅保留：生成内存配置按钮
        self.btn_generate_mem_cfg = QPushButton("生成内存配置")
        try:
            self.btn_generate_mem_cfg.clicked.connect(self.on_generate_mem_agent_config)
            try:
                self.logger.info("[MEMCFG] 按钮连接完成: btn_generate_mem_cfg -> on_generate_mem_agent_config")
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.error(f"[MEMCFG] 按钮连接失败: generate_mem_cfg -> {e}")
            except Exception:
                pass

        # 按 AssistantAgentConfig 字段顺序组织
        asst_form.addRow("name", self.det_name)
        asst_form.addRow("description", self.det_description)
        asst_form.addRow("system_message", self.det_system_message)
        asst_form.addRow("reflect_on_tool_use", self.det_reflect_on_tool_use)
        asst_form.addRow("tool_call_summary_format", self.det_tool_call_summary_format)
        asst_form.addRow("model_client_stream", self.det_model_client_stream)
        asst_form.addRow("max_tool_iterations", self.det_max_tool_iterations)
        asst_form.addRow("model_context", self.det_model_context)
        asst_form.addRow("metadata", self.det_metadata)
        asst_form.addRow("structured_message_factory", self.det_structured_message_factory)
        # 将按钮加入一行：编辑/保存/取消/生成内存配置
        btn_row.addWidget(self.btn_generate_mem_cfg)
        asst_form.addRow(btn_row)

        # 右（与 _refresh_right_agent_detail_tab 对齐：asst_* 命名，可滚动）
        asst_right = QWidget(); asst_right_layout = QVBoxLayout(asst_right)
        
        # 内存配置文件预览抽屉（在模型选择器之前）
        self.asst_mem_config_preview = QTextEdit()
        self.asst_mem_config_preview.setReadOnly(True)
        self.asst_mem_config_preview.setPlaceholderText("点击'生成内存配置'按钮后，此处将显示生成的配置文件内容...")
        self.asst_mem_config_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.asst_mem_config_preview.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        # 文档内容变化时触发大小重新计算
        self.asst_mem_config_preview.textChanged.connect(self._adjust_config_preview_height)
        
        # 创建完全自适应的折叠面板，启用复制按钮
        self.config_panel = CollapsiblePanel("配置文件预览", show_add_button=False, show_copy_button=True, clickable_header=True, max_content_height=800, start_collapsed=False)
        self.config_panel.setContentWidget(self.asst_mem_config_preview)
        # 连接复制按钮信号
        self.config_panel.copyClicked.connect(self._copy_config_to_clipboard)
        
        # 添加折叠面板到右侧布局
        asst_right_layout.addWidget(self.config_panel)
        
        # 移除右列模型选择器与环境信息展示（按需求删除）
        # 需求：删除右侧四个折叠抽屉（工具/记忆/工作台/交接），因此不再创建对应组件与添加布局。
        # 保留上方配置文件预览与模型环境信息区域。

        # 在模型只读信息下方新增：参与者（导入器）组件，用于导入 工具/MCP/向量库 配置文件，显示为列表项
        try:
            part_group = QGroupBox("参与者（导入器）")
            part_v = QVBoxLayout(part_group)
            header = QHBoxLayout()
            header.addWidget(QLabel("导入的配置文件列表"))
            self.btn_agent_import_add = QPushButton("导入…")
            try:
                self.btn_agent_import_add.clicked.connect(self._agent_import_add)
            except Exception:
                pass
            header.addStretch(1)
            header.addWidget(self.btn_agent_import_add)
            part_v.addLayout(header)

            self.agent_import_list = QListWidget()
            try:
                # 点击列表项：在右侧配置浏览框显示该配置文件内容
                self.agent_import_list.itemClicked.connect(self._on_agent_import_item_clicked)
            except Exception:
                pass
            part_v.addWidget(self.agent_import_list)

            # 右侧上下移动控制
            ctrl_row = QHBoxLayout()
            self.btn_agent_import_up = QPushButton("上移")
            self.btn_agent_import_down = QPushButton("下移")
            try:
                self.btn_agent_import_up.clicked.connect(lambda: self._agent_import_move_selected(-1))
                self.btn_agent_import_down.clicked.connect(lambda: self._agent_import_move_selected(1))
            except Exception:
                pass
            ctrl_row.addStretch(1)
            ctrl_row.addWidget(self.btn_agent_import_up)
            ctrl_row.addWidget(self.btn_agent_import_down)
            part_v.addLayout(ctrl_row)

            asst_right_layout.addWidget(part_group)
        except Exception:
            pass
        # 顶部对齐，空白留在下方
        try:
            asst_right_layout.addStretch(1)
        except Exception:
            pass

        # 右侧可滚动
        asst_scroll = QScrollArea(); asst_scroll.setWidget(asst_right); asst_scroll.setWidgetResizable(True)
        # 包裹滚动区
        asst_left_scroll = QScrollArea(); asst_left_scroll.setWidgetResizable(True); asst_left_scroll.setWidget(asst_left)
        asst_right_scroll = QScrollArea(); asst_right_scroll.setWidgetResizable(True); asst_right_scroll.setWidget(asst_right)
        # 自适应：强制Expanding尺寸策略
        try:
            for w in (asst_left, asst_right, asst_left_scroll, asst_right_scroll):
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass
        split_asst.addWidget(asst_left_scroll); split_asst.addWidget(asst_right_scroll)
        try:
            split_asst.setChildrenCollapsible(False)
            split_asst.setHandleWidth(6)
        except Exception:
            pass
        split_asst.setStretchFactor(0, 3); split_asst.setStretchFactor(1, 2)
        self.agent_right_tabs.addTab(tab_asst, "AssistantAgent")

        # Tab 2: MultimodalWebSurfer（占位基础表单 + 右侧预留）
        tab_surf = QWidget(); split_surf = QSplitter(Qt.Orientation.Horizontal, tab_surf)
        try:
            _lyt_surf = QVBoxLayout(tab_surf)
            _lyt_surf.setContentsMargins(0, 0, 0, 0)
            _lyt_surf.setSpacing(0)
            _lyt_surf.addWidget(split_surf)
        except Exception:
            pass
        # 左（可滚动）
        surf_left = QWidget(); surf_form = QFormLayout(surf_left)
        # 必需
        self.surf_name = QLineEdit()
        self.surf_model = QLineEdit()
        # 可选
        self.surf_downloads_folder = QLineEdit()
        self.surf_desc = QLineEdit()
        self.surf_debug_dir = QLineEdit()
        self.surf_headless = QCheckBox("无头模式（默认True）"); self.surf_headless.setChecked(True)
        self.surf_start_page = QLineEdit(); self.surf_start_page.setPlaceholderText("https://www.bing.com/")
        self.surf_animate_actions = QCheckBox("动画显示操作（默认False）")
        self.surf_to_save_screenshots = QCheckBox("保存截图（默认False）")
        self.surf_use_ocr = QCheckBox("使用OCR（默认False）")
        self.surf_browser_channel = QLineEdit()
        self.surf_browser_data_dir = QLineEdit()
        self.surf_to_resize_viewport = QCheckBox("调整视口大小（默认True）"); self.surf_to_resize_viewport.setChecked(True)

        # 表单布局（按规范顺序）
        surf_form.addRow("name", self.surf_name)
        surf_form.addRow("model", self.surf_model)
        surf_form.addRow("downloads_folder", self.surf_downloads_folder)
        surf_form.addRow("description", self.surf_desc)
        surf_form.addRow("debug_dir", self.surf_debug_dir)
        surf_form.addRow("headless", self.surf_headless)
        surf_form.addRow("start_page", self.surf_start_page)
        surf_form.addRow("animate_actions", self.surf_animate_actions)
        surf_form.addRow("to_save_screenshots", self.surf_to_save_screenshots)
        surf_form.addRow("use_ocr", self.surf_use_ocr)
        surf_form.addRow("browser_channel", self.surf_browser_channel)
        surf_form.addRow("browser_data_dir", self.surf_browser_data_dir)
        surf_form.addRow("to_resize_viewport", self.surf_to_resize_viewport)
        # 右（可滚动）
        surf_right = QWidget(); surf_right_layout = QVBoxLayout(surf_right)
        surf_right_layout.addWidget(QLabel("（预留列表区）")); surf_right_layout.addStretch()
        surf_scroll = QScrollArea(); surf_scroll.setWidget(surf_right); surf_scroll.setWidgetResizable(True)
        # 包裹滚动区
        surf_left_scroll = QScrollArea(); surf_left_scroll.setWidgetResizable(True); surf_left_scroll.setWidget(surf_left)
        surf_right_scroll = QScrollArea(); surf_right_scroll.setWidgetResizable(True); surf_right_scroll.setWidget(surf_right)
        try:
            for w in (surf_left, surf_right, surf_left_scroll, surf_right_scroll):
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass
        split_surf.addWidget(surf_left_scroll); split_surf.addWidget(surf_right_scroll)
        try:
            split_surf.setChildrenCollapsible(False)
            split_surf.setHandleWidth(6)
        except Exception:
            pass
        split_surf.setStretchFactor(0, 3); split_surf.setStretchFactor(1, 2)
        self.agent_right_tabs.addTab(tab_surf, "MultimodalWebSurfer")

        # Tab 3: SocietyOfMindAgent（团队参数 + 右侧Team清单只读）
        tab_soma = QWidget(); split_soma = QSplitter(Qt.Orientation.Horizontal, tab_soma)
        try:
            _lyt_soma = QVBoxLayout(tab_soma)
            _lyt_soma.setContentsMargins(0, 0, 0, 0)
            _lyt_soma.setSpacing(0)
            _lyt_soma.addWidget(split_soma)
        except Exception:
            pass
        # 左（可滚动）
        soma_left = QWidget(); soma_form = QFormLayout(soma_left)
        self.soma_name = QLineEdit(); self.soma_desc = QLineEdit(); self.soma_instruction = QLineEdit(); self.soma_response_prompt = QLineEdit(); self.soma_model = QLineEdit()
        # 新增：team（只读组件名）与 model_context（只读）
        self.soma_team = QLineEdit(); self.soma_team.setReadOnly(True); self.soma_team.setPlaceholderText("team：内部Team组件（只读）")
        self.soma_model_context = QLineEdit(); self.soma_model_context.setReadOnly(True); self.soma_model_context.setPlaceholderText("model_context：模型上下文（只读）")

        soma_form.addRow("name", self.soma_name)
        soma_form.addRow("team", self.soma_team)
        soma_form.addRow("model", self.soma_model)
        soma_form.addRow("description", self.soma_desc)
        soma_form.addRow("instruction", self.soma_instruction)
        soma_form.addRow("response_prompt", self.soma_response_prompt)
        soma_form.addRow("model_context", self.soma_model_context)
        # 右（可滚动）
        soma_right = QWidget(); soma_right_layout = QVBoxLayout(soma_right)
        soma_right_layout.addWidget(QLabel("Team（只读显示）"))
        self.soma_team_list = QListWidget(); soma_right_layout.addWidget(self.soma_team_list)
        soma_scroll = QScrollArea(); soma_scroll.setWidget(soma_right); soma_scroll.setWidgetResizable(True)
        # 包裹滚动区
        soma_left_scroll = QScrollArea(); soma_left_scroll.setWidgetResizable(True); soma_left_scroll.setWidget(soma_left)
        soma_right_scroll = QScrollArea(); soma_right_scroll.setWidgetResizable(True); soma_right_scroll.setWidget(soma_right)
        try:
            for w in (soma_left, soma_right, soma_left_scroll, soma_right_scroll):
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass
        split_soma.addWidget(soma_left_scroll); split_soma.addWidget(soma_right_scroll)
        try:
            split_soma.setChildrenCollapsible(False)
            split_soma.setHandleWidth(6)
        except Exception:
            pass
        split_soma.setStretchFactor(0, 3); split_soma.setStretchFactor(1, 2)
        self.agent_right_tabs.addTab(tab_soma, "SocietyOfMindAgent")

        # Tab 4: OpenAIAgent（基础表单 + 工具清单只读）
        tab_oai = QWidget(); split_oai = QSplitter(Qt.Orientation.Horizontal, tab_oai)
        try:
            _lyt_oai = QVBoxLayout(tab_oai)
            _lyt_oai.setContentsMargins(0, 0, 0, 0)
            _lyt_oai.setSpacing(0)
            _lyt_oai.addWidget(split_oai)
        except Exception:
            pass
        # 左（可滚动）
        oai_left = QWidget(); oai_form = QFormLayout(oai_left)
        self.oai_name = QLineEdit(); self.oai_instructions = QTextEdit(); self.oai_instructions.setMaximumHeight(80)
        self.oai_model = QLineEdit(); self.oai_temperature = QDoubleSpinBox(); self.oai_temperature.setRange(0.0, 2.0); self.oai_temperature.setValue(1.0)
        self.oai_max_tokens = QSpinBox(); self.oai_max_tokens.setRange(1, 128000); self.oai_json_mode = QCheckBox("JSON模式"); self.oai_store = QCheckBox("存储对话")
        # 新增：description 与 truncation
        self.oai_description = QTextEdit(); self.oai_description.setMaximumHeight(60)
        self.oai_truncation = QComboBox(); self.oai_truncation.setEditable(True); self.oai_truncation.addItems(["disabled", "auto"]); self.oai_truncation.setCurrentText("disabled")

        oai_form.addRow("name", self.oai_name)
        oai_form.addRow("instructions", self.oai_instructions)
        oai_form.addRow("model", self.oai_model)
        oai_form.addRow("description", self.oai_description)
        oai_form.addRow("tools（只读见右侧）", QLabel(""))
        oai_form.addRow("temperature", self.oai_temperature)
        oai_form.addRow("max_output_tokens", self.oai_max_tokens)
        oai_form.addRow("json_mode", self.oai_json_mode)
        oai_form.addRow("store", self.oai_store)
        oai_form.addRow("truncation", self.oai_truncation)
        # 右（可滚动）
        oai_right = QWidget(); oai_right_layout = QVBoxLayout(oai_right)
        oai_right_layout.addWidget(QLabel("工具列表（只读）"))
        self.oai_tools_list = QListWidget(); oai_right_layout.addWidget(self.oai_tools_list)
        oai_scroll = QScrollArea(); oai_scroll.setWidget(oai_right); oai_scroll.setWidgetResizable(True)
        # 包裹滚动区
        oai_left_scroll = QScrollArea(); oai_left_scroll.setWidgetResizable(True); oai_left_scroll.setWidget(oai_left)
        oai_right_scroll = QScrollArea(); oai_right_scroll.setWidgetResizable(True); oai_right_scroll.setWidget(oai_right)
        try:
            for w in (oai_left, oai_right, oai_left_scroll, oai_right_scroll):
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass
        split_oai.addWidget(oai_left_scroll); split_oai.addWidget(oai_right_scroll)
        try:
            split_oai.setChildrenCollapsible(False)
            split_oai.setHandleWidth(6)
        except Exception:
            pass
        split_oai.setStretchFactor(0, 3); split_oai.setStretchFactor(1, 2)
        self.agent_right_tabs.addTab(tab_oai, "OpenAIAgent")

        v.addWidget(self.agent_right_tabs)
        # 确保Agent右侧选项卡容器与各子页签采用零边距/零间距布局，并设置容器与QTabWidget为Expanding，使内部splitter能够随主窗口与右栏平滑自适应大小。
        self.agent_right_tabs.setContentsMargins(0, 0, 0, 0)
        _tabs_lyt = self.agent_right_tabs.layout()
        if _tabs_lyt is not None:
            _tabs_lyt.setSpacing(0)
        self.agent_right_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 绑定与初次刷新（仅Assistant页表单参与表单同步）
        try:
            self._bind_agent_detail_form_signals()
        except Exception:
            pass
        try:
            self._refresh_det_model_candidates()
            self._refresh_right_agent_detail_tab()
            # 初次填充模型只读信息
            self._update_agent_model_env_preview()
        except Exception:
            pass
        return container

    def _update_agent_model_env_preview(self):
        """根据右侧 `det_model` 当前文本，在 config/models 中查找对应模型，
        只读显示 base_url 与 api_key_env；找不到或字段缺失时显示 '-'。
        不做任何隐式结构转换与写盘。
        """
        try:
            # 若控件不存在则忽略
            if not hasattr(self, 'det_model') or not hasattr(self, 'asst_model_env_info'):
                return
            model_name = (self.det_model.currentText() or '').strip()
            base_url = None
            api_key_env = None
            if model_name:
                try:
                    base_dir = Path(__file__).parent.parent.parent
                    models_dir = base_dir / 'config' / 'models'
                    if models_dir.exists() and models_dir.is_dir():
                        for p in sorted(models_dir.glob('*.json')):
                            obj = None
                            try:
                                with p.open('r', encoding='utf-8') as f:
                                    obj = json.load(f)
                            except Exception:
                                obj = None
                            if not isinstance(obj, dict):
                                continue
                            # 允许以多种途径匹配：name 或 config.model 或 model
                            nm = str(obj.get('name') or obj.get('id') or '').strip()
                            cfg = obj.get('config') or {}
                            if not isinstance(cfg, dict):
                                cfg = {}
                            mc = obj.get('model_client') or {}
                            if not isinstance(mc, dict):
                                mc = {}
                            mcc = mc.get('config') or {}
                            if not isinstance(mcc, dict):
                                mcc = {}
                            model_field = str(cfg.get('model') or obj.get('model') or mcc.get('model') or nm or '').strip()
                            if model_field == model_name or nm == model_name:
                                # 提取字段：优先嵌套，再顶层；不做归一化
                                base_url = (
                                    mcc.get('base_url')
                                    if isinstance(mcc, dict) and 'base_url' in mcc else (
                                        cfg.get('base_url') if 'base_url' in cfg else obj.get('base_url')
                                    )
                                )
                                api_key_env = (
                                    mcc.get('api_key_env')
                                    if isinstance(mcc, dict) and 'api_key_env' in mcc else (
                                        cfg.get('api_key_env') if 'api_key_env' in cfg else obj.get('api_key_env')
                                    )
                                )
                                break
                except Exception:
                    pass
            # 展示（保持可复制、只读，避免换行过高）
            try:
                txt = f"base_url: {str(base_url) if base_url else '-'}\napi_key_env: {str(api_key_env) if api_key_env else '-'}"
                self.asst_model_env_info.blockSignals(True)
                self.asst_model_env_info.setPlainText(txt)
                self.asst_model_env_info.blockSignals(False)
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"更新模型只读信息失败: {e}")
            except Exception:
                pass

    # ---- 辅助：从 Agent 配置中提取模型名 ----
    def _extract_model_name_from_agent(self, agent: dict) -> str:
        try:
            if not isinstance(agent, dict):
                return ""
            mc = agent.get('model_client') or {}
            if isinstance(mc, dict):
                mcc = mc.get('config') or {}
                if isinstance(mcc, dict) and mcc.get('model'):
                    return str(mcc.get('model'))
            cfg = agent.get('config') or {}
            if isinstance(cfg, dict) and cfg.get('model'):
                return str(cfg.get('model'))
            if agent.get('model'):
                return str(agent.get('model'))
            return ""
        except Exception:
            return ""

    # ---- 回填右侧 Agent 详情表单 ----
    def _refresh_right_agent_detail_tab(self):
        """将内存中的 self.agent_data 回填到右侧 AssistantAgent 表单，并同步模型下拉。"""
        try:
            data = getattr(self, 'agent_data', None)
            if not isinstance(data, dict):
                return
            # 基础字段
            try:
                if hasattr(self, 'det_name'):
                    self.det_name.blockSignals(True)
                    self.det_name.setText(str(data.get('name') or ''))
                    self.det_name.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_description'):
                    self.det_description.blockSignals(True)
                    self.det_description.setPlainText(str(data.get('description') or ''))
                    self.det_description.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_system_message'):
                    # 支持 system_message 或 system_prompt 兼容字段
                    sysmsg = data.get('system_message')
                    if sysmsg is None:
                        sysmsg = data.get('system_prompt')
                    self.det_system_message.blockSignals(True)
                    self.det_system_message.setPlainText(str(sysmsg or ''))
                    self.det_system_message.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_reflect_on_tool_use'):
                    self.det_reflect_on_tool_use.blockSignals(True)
                    self.det_reflect_on_tool_use.setChecked(bool(data.get('reflect_on_tool_use') or False))
                    self.det_reflect_on_tool_use.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_tool_call_summary_format'):
                    self.det_tool_call_summary_format.blockSignals(True)
                    self.det_tool_call_summary_format.setPlainText(str(data.get('tool_call_summary_format') or ''))
                    self.det_tool_call_summary_format.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_model_client_stream'):
                    self.det_model_client_stream.blockSignals(True)
                    self.det_model_client_stream.setChecked(bool(data.get('model_client_stream') or False))
                    self.det_model_client_stream.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_max_tool_iterations'):
                    v = data.get('max_tool_iterations')
                    if isinstance(v, int):
                        self.det_max_tool_iterations.blockSignals(True)
                        self.det_max_tool_iterations.setValue(max(1, min(99, v)))
                        self.det_max_tool_iterations.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_model_context'):
                    mc_name = ''
                    mc = data.get('model_context')
                    if isinstance(mc, dict):
                        mc_name = str(mc.get('name') or mc.get('id') or '')
                    self.det_model_context.blockSignals(True)
                    self.det_model_context.setText(mc_name)
                    self.det_model_context.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_metadata'):
                    meta = data.get('metadata')
                    txt = json.dumps(meta, ensure_ascii=False, indent=2) if isinstance(meta, dict) else (str(meta) if meta is not None else '')
                    self.det_metadata.blockSignals(True)
                    self.det_metadata.setPlainText(txt)
                    self.det_metadata.blockSignals(False)
            except Exception:
                pass
            try:
                if hasattr(self, 'det_structured_message_factory'):
                    smf = data.get('structured_message_factory')
                    name = ''
                    if isinstance(smf, dict):
                        name = str(smf.get('name') or smf.get('id') or '')
                    self.det_structured_message_factory.blockSignals(True)
                    self.det_structured_message_factory.setText(name)
                    self.det_structured_message_factory.blockSignals(False)
            except Exception:
                pass

            # 同步模型下拉
            try:
                model_name = self._extract_model_name_from_agent(data)
                if hasattr(self, 'det_model'):
                    # 确保候选项存在；若不存在则加入临时项
                    found = False
                    for i in range(self.det_model.count()):
                        if self.det_model.itemText(i) == model_name:
                            found = True
                            break
                    if not found and model_name:
                        self.det_model.addItem(model_name)
                    # 设置当前文本
                    self.det_model.setCurrentText(model_name)
                    # 更新右侧只读环境信息
                    self._update_agent_model_env_preview()
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"回填Agent详情表单失败: {e}")
            except Exception:
                pass

    def _create_settings_tab(self):
        """创建"设置"页面（二级选项卡结构）：
        - 第一个子选项卡"设置"：左右两栏，左栏放设置功能，右栏放占位符
        - 第二个子选项卡"笔记"：左中右三栏，左栏占位符，中右栏放笔记编辑和输出功能
        """
        try:
            # 主容器和二级选项卡
            widget = QWidget()
            layout = QVBoxLayout(widget)
            from PySide6.QtWidgets import QTabWidget
            sub_tabs = QTabWidget()
            
            # === 第一个子选项卡："设置" ===
            self._create_settings_subtab(sub_tabs)
            
            # === 第二个子选项卡："笔记" ===
            self._create_notes_subtab(sub_tabs)
            
            layout.addWidget(sub_tabs)
            self.tabs.addTab(widget, '设置')
            
            # 启动后自动连接（长驻会话）
            try:
                self._settings_status.setText('连接中...')
                self._settings_status.setStyleSheet('color: orange;')
                # 延迟到事件循环，避免阻塞 UI 构建
                from PySide6.QtCore import QTimer
                QTimer.singleShot(50, self._on_settings_start_session)
            except Exception:
                pass
        except Exception as e:
            # 出错则给出占位页面
            fallback = QWidget(); v = QVBoxLayout(fallback)
            v.addWidget(QLabel(f"设置 页面加载失败：{str(e)[:200]}"))
            self.tabs.addTab(fallback, '设置')

    def _create_settings_subtab(self, parent_tabs):
        """创建"设置"子选项卡（左右两栏）"""
        try:
            settings_widget = QWidget()
            settings_layout = QVBoxLayout(settings_widget)
            splitter = QSplitter(Qt.Orientation.Horizontal)

            # 左栏：参数表单
            left = QWidget(); left_form = QFormLayout(left)
            from PySide6.QtWidgets import QLineEdit, QPushButton
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            def _d(*p):
                return os.path.join(base_dir, *p)
            self.settings_script = QLineEdit(_d('scripts', 'run_team_interactive.py'))
            self.settings_team = QLineEdit(_d('config', 'teams', 'team_notes_master.json'))
            self.settings_env = QLineEdit(_d('.env'))
            self.settings_rounds = QLineEdit('1')
            self.settings_timeout = QLineEdit('180')
            from PySide6.QtWidgets import QLabel
            # 按钮区：启动/断开 + 单次运行
            row_btn = QWidget(); from PySide6.QtWidgets import QHBoxLayout
            row_btn_layout = QHBoxLayout(row_btn); row_btn_layout.setContentsMargins(0,0,0,0)
            btn_start = QPushButton('启动会话')
            btn_stop = QPushButton('断开会话')
            btn_run = QPushButton('单次运行')
            self._settings_status = QLabel('未连接')
            try:
                self._settings_status.setStyleSheet('color: gray;')
            except Exception:
                pass
            try:
                btn_start.clicked.connect(self._on_settings_start_session)
                btn_stop.clicked.connect(self._on_settings_stop_session)
                btn_run.clicked.connect(self._on_settings_run_clicked)
            except Exception:
                pass
            row_btn_layout.addWidget(btn_start)
            row_btn_layout.addWidget(btn_stop)
            row_btn_layout.addStretch(1)
            row_btn_layout.addWidget(btn_run)
            # 日志按钮：弹出日志查看对话框
            btn_logs = QPushButton('日志')
            try:
                btn_logs.clicked.connect(self._open_logs_dialog)
            except Exception:
                pass
            row_btn_layout.addWidget(btn_logs)
            row_btn_layout.addWidget(self._settings_status)
            left_form.addRow('脚本:', self.settings_script)
            left_form.addRow('team-json:', self.settings_team)
            left_form.addRow('env-file:', self.settings_env)
            left_form.addRow('max-rounds:', self.settings_rounds)
            left_form.addRow('timeout(s):', self.settings_timeout)
            left_form.addRow('', row_btn)

            # 向量库清理（参数与操作）
            try:
                from PySide6.QtWidgets import QFrame
                sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
                left_form.addRow(sep)
                self.settings_chroma_path = QLineEdit(_d('data', 'autogen_official_memory', 'vector_demo'))
                self.settings_chroma_coll = QLineEdit('vector_demo_assistant')
                left_form.addRow('chroma路径:', self.settings_chroma_path)
                left_form.addRow('collection:', self.settings_chroma_coll)
                row_vec = QWidget(); from PySide6.QtWidgets import QHBoxLayout
                row_vec_l = QHBoxLayout(row_vec); row_vec_l.setContentsMargins(0,0,0,0)
                btn_vec_preview = QPushButton('清理预览 (dry-run)')
                btn_vec_apply = QPushButton('执行清理 (apply)')
                btn_vec_preview.clicked.connect(lambda: self._on_settings_cleanup(True))
                btn_vec_apply.clicked.connect(lambda: self._on_settings_cleanup(False))
                row_vec_l.addWidget(btn_vec_preview)
                row_vec_l.addWidget(btn_vec_apply)
                left_form.addRow('', row_vec)

                # 简易关键词检索（正则）
                self.settings_vec_keywords = QLineEdit('开发|研发|dev')
                left_form.addRow('keywords(正则):', self.settings_vec_keywords)
                btn_vec_search = QPushButton('向量检索（关键词统计）')
                btn_vec_search.clicked.connect(self._on_settings_vector_keyword_search)
                # 灌注选项与按钮 + 批量导入 + 进度/取消 + 依赖检测
                from PySide6.QtWidgets import QHBoxLayout, QCheckBox, QProgressBar, QComboBox
                self.settings_ingest_preprocess = QCheckBox('预处理(清洗+分段)')
                self.settings_ingest_preprocess.setChecked(True)
                # 预处理参数：分段长度与重叠
                self.settings_chunk_size = QLineEdit('1500')
                self.settings_chunk_overlap = QLineEdit('100')
                # OCR/ASR 引擎与语言
                self.settings_ocr_engine = QComboBox(); self.settings_ocr_engine.addItems(['pytesseract'])
                self.settings_ocr_lang = QLineEdit('chi_sim+eng')
                self.settings_asr_engine = QComboBox(); self.settings_asr_engine.addItems(['faster-whisper'])
                # 进度与取消
                self._ingest_progress = QProgressBar(); self._ingest_progress.setMaximum(100); self._ingest_progress.setValue(0)
                self._ingest_cancel = False
                btn_ing_cancel = QPushButton('取消导入')
                btn_ing_cancel.clicked.connect(self._on_ingest_cancel)
                btn_vec_ingest = QPushButton('灌注数据(选择导入)')
                btn_vec_ingest.clicked.connect(self._on_settings_vector_ingest)
                btn_vec_ingest_dir = QPushButton('批量导入文件夹')
                btn_vec_ingest_dir.clicked.connect(self._on_settings_vector_ingest_dir)
                btn_check_deps = QPushButton('解析器依赖检测')
                btn_check_deps.clicked.connect(self._check_parsers_dependencies)
                btn_install_cmds = QPushButton('安装可选解析器(打印命令)')
                btn_install_cmds.clicked.connect(self._print_install_commands)
                # 行1：检索+预处理开关+单文件灌注+目录灌注
                row_ing = QWidget(); row_ing_l = QHBoxLayout(row_ing); row_ing_l.setContentsMargins(0,0,0,0)
                row_ing_l.addWidget(btn_vec_search)
                row_ing_l.addSpacing(6)
                row_ing_l.addWidget(self.settings_ingest_preprocess)
                row_ing_l.addSpacing(6)
                row_ing_l.addWidget(btn_vec_ingest)
                row_ing_l.addSpacing(6)
                row_ing_l.addWidget(btn_vec_ingest_dir)
                left_form.addRow('', row_ing)
                # 行2：预处理参数
                row_prep = QWidget(); row_prep_l = QHBoxLayout(row_prep); row_prep_l.setContentsMargins(0,0,0,0)
                row_prep_l.addWidget(QLabel('chunk:'))
                row_prep_l.addWidget(self.settings_chunk_size)
                row_prep_l.addWidget(QLabel('overlap:'))
                row_prep_l.addWidget(self.settings_chunk_overlap)
                left_form.addRow('预处理参数:', row_prep)
                # 行3：OCR/ASR 引擎
                row_eng = QWidget(); row_eng_l = QHBoxLayout(row_eng); row_eng_l.setContentsMargins(0,0,0,0)
                row_eng_l.addWidget(QLabel('OCR:'))
                row_eng_l.addWidget(self.settings_ocr_engine)
                row_eng_l.addWidget(QLabel('lang:'))
                row_eng_l.addWidget(self.settings_ocr_lang)
                row_eng_l.addSpacing(12)
                row_eng_l.addWidget(QLabel('ASR:'))
                row_eng_l.addWidget(self.settings_asr_engine)
                left_form.addRow('解析引擎:', row_eng)
                # 行4：进度/取消 + 依赖检测
                row_prog = QWidget(); row_prog_l = QHBoxLayout(row_prog); row_prog_l.setContentsMargins(0,0,0,0)
                row_prog_l.addWidget(self._ingest_progress, 1)
                row_prog_l.addWidget(btn_ing_cancel)
                row_prog_l.addSpacing(8)
                row_prog_l.addWidget(btn_check_deps)
                row_prog_l.addWidget(btn_install_cmds)
                left_form.addRow('导入进度:', row_prog)

                # GraphRAG 同步区域（root/settings/input/output + 三个操作按钮）
                try:
                    from PySide6.QtWidgets import QHBoxLayout
                    sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
                    left_form.addRow(sep2)
                    self.settings_gr_root = QLineEdit('graphrag')
                    self.settings_gr_yaml = QLineEdit('graphrag/settings.yaml')
                    self.settings_gr_input = QLineEdit('graphrag/input')
                    self.settings_gr_output = QLineEdit('graphrag/output')
                    # 导出仅用 normalized 选项
                    self.settings_export_norm_only = QCheckBox('仅导出 normalized')
                    self.settings_export_norm_only.setChecked(False)
                    # 导出条数上限与过滤关键词（可选）
                    self.settings_export_limit = QLineEdit('0')
                    self.settings_export_limit.setPlaceholderText('0 为不限')
                    self.settings_export_keyword = QLineEdit('')
                    self.settings_export_keyword.setPlaceholderText('在文本文本与metadata中模糊匹配，可留空')
                    # 增量同步与重置
                    self.settings_export_incremental = QCheckBox('增量同步(仅新增/变更)')
                    self.settings_export_incremental.setChecked(True)
                    left_form.addRow('gr.root_dir:', self.settings_gr_root)
                    left_form.addRow('settings.yaml:', self.settings_gr_yaml)
                    left_form.addRow('input_dir:', self.settings_gr_input)
                    left_form.addRow('output_dir:', self.settings_gr_output)
                    left_form.addRow('', self.settings_export_norm_only)
                    left_form.addRow('', self.settings_export_incremental)
                    left_form.addRow('导出条数上限(0为不限):', self.settings_export_limit)
                    left_form.addRow('过滤关键词(可留空):', self.settings_export_keyword)
                    row_gr = QWidget(); row_gr_l = QHBoxLayout(row_gr); row_gr_l.setContentsMargins(0,0,0,0)
                    btn_gr_export = QPushButton('导出(Chroma→input)')
                    btn_gr_index = QPushButton('重建索引')
                    btn_gr_sync = QPushButton('一键同步')
                    btn_gr_reset_state = QPushButton('重置增量状态')
                    btn_dep_check = QPushButton('依赖检测')
                    btn_dep_install = QPushButton('打印安装命令')
                    btn_gr_export.clicked.connect(self._on_graphrag_export)
                    btn_gr_index.clicked.connect(self._on_graphrag_index)
                    btn_gr_sync.clicked.connect(self._on_graphrag_sync)
                    btn_gr_reset_state.clicked.connect(self._on_graphrag_reset_state)
                    btn_dep_check.clicked.connect(self._check_parsers_dependencies)
                    btn_dep_install.clicked.connect(self._print_install_commands)
                    row_gr_l.addWidget(btn_gr_export)
                    row_gr_l.addWidget(btn_gr_index)
                    row_gr_l.addWidget(btn_gr_sync)
                    row_gr_l.addWidget(btn_gr_reset_state)
                    row_gr_l.addWidget(btn_dep_check)
                    row_gr_l.addWidget(btn_dep_install)
                    left_form.addRow('GraphRAG:', row_gr)
                except Exception:
                    pass
            except Exception:
                pass
            
            # 右栏：占位符
            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.addWidget(QLabel("设置功能已集中在左侧栏\n右侧预留扩展空间"))
            
            # 组装设置子选项卡
            splitter.addWidget(left)
            splitter.addWidget(right)
            try:
                left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                splitter.setChildrenCollapsible(False)
                splitter.setHandleWidth(6)
                splitter.setStretchFactor(0, 3)
                splitter.setStretchFactor(1, 1)
            except Exception:
                pass
            
            settings_layout.addWidget(splitter)
            parent_tabs.addTab(settings_widget, "设置")
        except Exception as e:
            # 出错则给出占位页面
            fallback = QWidget(); v = QVBoxLayout(fallback)
            v.addWidget(QLabel(f"设置子页面加载失败：{str(e)[:200]}"))
            parent_tabs.addTab(fallback, "设置")
    
    def _create_notes_subtab(self, parent_tabs):
        """创建"笔记"子选项卡（左中右三栏）"""
        try:
            notes_widget = QWidget()
            notes_layout = QVBoxLayout(notes_widget)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            
            # 左栏：占位符
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.addWidget(QLabel("笔记功能扩展区\n（预留空间）"))

            # 中栏：输入（上：笔记整理框；下：笔记输入框）
            middle = QWidget(); mid_v = QVBoxLayout(middle)
            from PySide6.QtWidgets import QLineEdit
            # 上：笔记整理框（可选，多行，带MD工具栏）
            self.settings_note_curate = MarkdownEditor('笔记整理（MD编辑/预览）')
            mid_v.addWidget(self.settings_note_curate)
            # 下：笔记输入框（带MD工具栏）
            self.settings_note_input = MarkdownEditor('笔记输入（Enter 提交；Shift+Enter 换行；自动加 #笔记 前缀）')
            # 放大高度（约等于8行的高度）
            try:
                fm = self.settings_note_input.editor.fontMetrics()
                line_h = fm.lineSpacing() if fm else 18
                self.settings_note_input.setMinimumHeight(int(line_h * 8 + 12))
            except Exception:
                pass
            # 回车触发笔记模式：若已连接则发送一行；否则走一次性运行
            try:
                self.settings_note_input.returnPressed.connect(lambda: self._settings_on_return('note'))
            except Exception:
                pass
            mid_v.addWidget(self.settings_note_input)
            # 粘贴按钮行（将剪贴板内容粘贴到笔记输入框内）
            try:
                paste_row = QWidget(); from PySide6.QtWidgets import QHBoxLayout, QPushButton
                paste_layout = QHBoxLayout(paste_row); paste_layout.setContentsMargins(0,0,0,0)
                btn_paste = QPushButton('粘贴')
                def _do_paste():
                    try:
                        from PySide6.QtWidgets import QApplication
                        cb = QApplication.clipboard()
                        txt = cb.text() if cb else ''
                        if txt:
                            self.settings_note_input.insert_text(txt)
                    except Exception:
                        pass
                btn_paste.clicked.connect(_do_paste)
                # 新增：复制整个笔记输入内容
                btn_copy = QPushButton('复制')
                def _do_copy():
                    try:
                        from PySide6.QtWidgets import QApplication
                        cb = QApplication.clipboard()
                        if cb:
                            cb.setText(self.settings_note_input.text() or '')
                    except Exception:
                        pass
                btn_copy.clicked.connect(_do_copy)
                paste_layout.addWidget(btn_paste, 0)
                paste_layout.addWidget(btn_copy, 0)
                paste_layout.addStretch(1)
                mid_v.addWidget(paste_row)
            except Exception:
                pass

            # 右栏：输出
            right = QWidget(); right_v = QVBoxLayout(right)
            self.settings_output = QTextEdit(); self.settings_output.setReadOnly(True)
            self.settings_output.setPlaceholderText('脚本 stdout 原文将显示在此处（stderr 仅输出到控制台用于诊断）')
            # 输出选项：Markdown渲染、过滤调试信息
            try:
                self._settings_output_md_chk = QCheckBox('以Markdown渲染输出')
                self._settings_output_filter_chk = QCheckBox('仅显示有效内容（笔记/问答）')
                row_opts = QWidget(); row_opts_l = QHBoxLayout(row_opts); row_opts_l.setContentsMargins(0,0,0,0)
                row_opts_l.addWidget(self._settings_output_md_chk)
                row_opts_l.addWidget(self._settings_output_filter_chk)
                row_opts_l.addStretch(1)
                right_v.addWidget(row_opts)
                self._settings_output_md_text = ''  # 原始缓冲
                def _on_filter_changed():
                    try:
                        self._render_output()
                    except Exception:
                        pass
                self._settings_output_filter_chk.stateChanged.connect(_on_filter_changed)
            except Exception:
                pass
            right_v.addWidget(self.settings_output)
            # 右栏下方：问答输入（回车运行；Shift+Enter 换行；自动换行）
            self.settings_qa_input = MarkdownEditor('问答输入（MD编辑/预览；Enter 提交；Shift+Enter 换行）')
            self.settings_qa_input.setPlaceholderText('问答输入（Enter 提交；Shift+Enter 换行）')
            # 放大高度（约等于8行的高度）
            try:
                fm2 = self.settings_qa_input.editor.fontMetrics()
                line_h2 = fm2.lineSpacing() if fm2 else 18
                self.settings_qa_input.setMinimumHeight(int(line_h2 * 8 + 12))
            except Exception:
                pass
            try:
                self.settings_qa_input.returnPressed.connect(lambda: self._settings_on_return('qa'))
            except Exception:
                pass
            right_v.addWidget(self.settings_qa_input)

            # 组装笔记子选项卡
            splitter.addWidget(left)
            splitter.addWidget(middle)
            splitter.addWidget(right)
            try:
                left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                middle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                splitter.setChildrenCollapsible(False)
                splitter.setHandleWidth(6)
                splitter.setStretchFactor(0, 1)
                splitter.setStretchFactor(1, 3)
                splitter.setStretchFactor(2, 3)
            except Exception:
                pass
            
            notes_layout.addWidget(splitter)
            parent_tabs.addTab(notes_widget, "笔记")
        except Exception as e:
            # 出错则给出占位页面
            fallback = QWidget(); v = QVBoxLayout(fallback)
            v.addWidget(QLabel(f"笔记子页面加载失败：{str(e)[:200]}"))
            parent_tabs.addTab(fallback, "笔记")

    def _on_settings_run_clicked(self):
        """点击运行：等同于用笔记模式运行中栏输入。"""
        try:
            txt = self.settings_note_input.text() if hasattr(self, 'settings_note_input') else ''
            self._settings_run(txt, 'note')
        except Exception as e:
            self.settings_output.setPlainText(f"运行失败：{str(e)[:200]}")

    # =============== 输出渲染/过滤 ===============
    def _append_output(self, chunk: str):
        try:
            self._settings_output_md_text = (self._settings_output_md_text or '') + (chunk or '')
            self._render_output(append_only=True, last_chunk=chunk)
        except Exception:
            # 保底：直接追加到文本框
            try:
                self.settings_output.moveCursor(QTextCursor.End)
                self.settings_output.insertPlainText(chunk)
                self.settings_output.moveCursor(QTextCursor.End)
            except Exception:
                pass

    def _render_output(self, append_only: bool = False, last_chunk: str = ''):
        raw = self._settings_output_md_text or ''
        use_filter = False
        try:
            use_filter = bool(self._settings_output_filter_chk.isChecked())
        except Exception:
            pass
        if not use_filter:
            # 原样渲染：仅在追加时增量写入，否则重设
            try:
                if append_only and last_chunk:
                    self.settings_output.moveCursor(QTextCursor.End)
                    self.settings_output.insertPlainText(last_chunk)
                    self.settings_output.moveCursor(QTextCursor.End)
                else:
                    self.settings_output.setPlainText(raw)
                    self.settings_output.moveCursor(QTextCursor.End)
            except Exception:
                pass
            return
        # 过滤模式：只显示 笔记正文 / 问答问句与回答
        try:
            lines = (raw or '').splitlines()
            out_lines = []
            in_block = False
            for ln in lines:
                s = ln.strip('\r')
                if s == '-----':
                    in_block = not in_block
                    continue
                if in_block:
                    out_lines.append(s)
                    continue
                # 问答/笔记回显
                if s.startswith('[笔记] '):
                    out_lines.append('Note: ' + s[len('[笔记] '):])
                    continue
                if s.startswith('[问答] '):
                    out_lines.append('Q: ' + s[len('[问答] '):])
                    continue
                # 过滤常见诊断标签
                if s.startswith('['):
                    if s.startswith('[助手-'):
                        # 将助手回复作为 A: 输出（结构化）
                        content = s
                        # 去掉形如"[助手-x] "前缀
                        try:
                            idx = content.find(']')
                            if idx >= 0 and idx + 1 < len(content):
                                content = content[idx+1:].lstrip()
                        except Exception:
                            pass
                        if content:
                            out_lines.append('A: ' + content)
                    # 其他以 [ 开头的一律视为诊断信息忽略
                    continue
                # 普通行：若不是纯诊断，多为模型正文，保留为 A:（追加）
                if s:
                    out_lines.append('A: ' + s)
            filtered = '\n'.join(out_lines)
            self.settings_output.setPlainText(filtered)
            self.settings_output.moveCursor(QTextCursor.End)
        except Exception:
            # 失败则退回原样
            try:
                self.settings_output.setPlainText(raw)
                self.settings_output.moveCursor(QTextCursor.End)
            except Exception:
                pass

    def _on_settings_cleanup(self, dry_run: bool = True):
        """运行向量库清理脚本，stdout 直接追加到右侧输出框。"""
        try:
            import subprocess, sys, os, json
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            script = os.path.join(base_dir, 'scripts', 'maintenance', 'Clean-ChromaVectorMemory.py')
            if not os.path.exists(script):
                self.settings_output.append('[清理] 脚本不存在。')
                return
            persistence = (self.settings_chroma_path.text() if hasattr(self, 'settings_chroma_path') else '') or ''
            collection = (self.settings_chroma_coll.text() if hasattr(self, 'settings_chroma_coll') else '') or ''
            if not persistence:
                self.settings_output.append('[清理] chroma路径为空。')
                return
            if not collection:
                self.settings_output.append('[清理] collection 为空。')
                return
            cmd = [
                sys.executable, '-X', 'utf8', '-u', script,
                '--persistence', persistence,
                '--collection', collection,
            ]
            if dry_run:
                cmd.append('--dry-run')
            else:
                cmd.extend(['--apply', '--backup'])
            try:
                res = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=120)
            except subprocess.TimeoutExpired:
                self.settings_output.append('[清理] 超时。')
                return
            out = res.stdout or ''
            err = res.stderr or ''
            # 追加报告到输出框
            try:
                from PySide6.QtGui import QTextCursor
                self.settings_output.moveCursor(QTextCursor.End)
                mode = 'dry-run' if dry_run else 'apply'
                self.settings_output.insertPlainText(f"\n[清理:{mode}] 输出:\n")
                self.settings_output.insertPlainText(out if out.strip() else '(无输出)')
                self.settings_output.moveCursor(QTextCursor.End)
            except Exception:
                pass
            # 控制台打印 stderr 尾部
            if err.strip():
                lines = [l for l in err.splitlines() if l.strip()]
                tail = '\n'.join(lines[-30:]) if lines else err
                print(f"[CLEANUP][stderr-tail]\n{tail}")
        except Exception as e:
            try:
                self.settings_output.append(f"[清理] 失败：{str(e)[:200]}")
            except Exception:
                pass

    def _on_settings_vector_keyword_search(self):
        """遍历 Chroma collection，按正则关键字统计命中条数与示例。"""
        try:
            import os, re, json
            from chromadb import PersistentClient
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            persistence = (self.settings_chroma_path.text() if hasattr(self, 'settings_chroma_path') else '') or ''
            collection = (self.settings_chroma_coll.text() if hasattr(self, 'settings_chroma_coll') else '') or ''
            pattern = (self.settings_vec_keywords.text() if hasattr(self, 'settings_vec_keywords') else '') or ''
            if not persistence or not collection:
                self.settings_output.append('[检索] chroma路径或collection为空。')
                return
            try:
                rgx = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                self.settings_output.append(f'[检索] 正则无效: {e}')
                return
            client = PersistentClient(path=persistence)
            col = client.get_or_create_collection(collection)
            data = col.get()
            ids = data.get('ids') or []
            docs = data.get('documents') or []
            metas = data.get('metadatas') or []
            total = len(ids)
            hits = []
            for i, (id_, doc) in enumerate(zip(ids, docs)):
                text = (doc or '')
                if rgx.search(text):
                    snippet = text[:160].replace('\n',' ')
                    hits.append({"id": id_, "snippet": snippet})
            report = {
                "collection": collection,
                "persistence": persistence,
                "keywords": pattern,
                "total": total,
                "matched": len(hits),
                "ratio": round((len(hits)/total), 4) if total else 0.0,
                "samples": hits[:20],
            }
            from PySide6.QtGui import QTextCursor
            self.settings_output.moveCursor(QTextCursor.End)
            self.settings_output.insertPlainText('\n[检索] 关键词统计:\n')
            self.settings_output.insertPlainText(json.dumps(report, ensure_ascii=False, indent=2))
            self.settings_output.moveCursor(QTextCursor.End)
        except Exception as e:
            try:
                self.settings_output.append(f"[检索] 失败：{str(e)[:200]}")
            except Exception:
                pass

    def _on_settings_vector_ingest(self):
        """选择本地文件并灌注到 Chroma 向量库。
        - 支持文本类：.txt/.md/.log/.json/.csv（其他类型先跳过，后续可扩展）
        - 元数据：mode='note', subtype='raw', source_path, imported_at
        - 预处理可选：轻度清洗与长度分段
        """
        try:
            from PySide6.QtWidgets import QFileDialog
            import os, uuid, time
            from datetime import datetime
            from chromadb import PersistentClient
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            persistence = (self.settings_chroma_path.text() if hasattr(self, 'settings_chroma_path') else '') or ''
            collection = (self.settings_chroma_coll.text() if hasattr(self, 'settings_chroma_coll') else '') or ''
            if not persistence or not collection:
                self.settings_output.append('[灌注] 失败：chroma 路径或 collection 为空。')
                return
            # 选择文件（扩展更多类型：docx/pdf/xlsx/csv/图片/音频）
            filters = (
                'Documents/Text (*.txt *.md *.log *.json *.csv *.docx *.pdf *.xlsx);;'
                'Images (*.png *.jpg *.jpeg *.bmp *.webp);;'
                'Audio (*.wav *.mp3 *.m4a);;'
                'All Files (*.*)'
            )
            files, _ = QFileDialog.getOpenFileNames(self, '选择要灌注的文件（可多选）', base_dir, filters)
            if not files:
                return
            # 预处理选项
            do_prep = False
            try:
                do_prep = bool(self.settings_ingest_preprocess.isChecked())
            except Exception:
                pass
            # 读取预处理参数
            def _to_int(edit, default_val: int) -> int:
                try:
                    v = int(edit.text())
                    return v if v > 0 else default_val
                except Exception:
                    return default_val
            chunk_size = _to_int(getattr(self, 'settings_chunk_size', None) or type('x',(object,),{'text':lambda s:'1500'})(), 1500)
            overlap = _to_int(getattr(self, 'settings_chunk_overlap', None) or type('x',(object,),{'text':lambda s:'100'})(), 100)
            # 建立连接
            client = PersistentClient(path=persistence)
            col = client.get_or_create_collection(collection)
            total_files = 0
            total_chunks = 0
            skipped = 0
            # 基础读取与解析函数集合（按可用性优雅降级）
            def _read_text(path: str) -> str:
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        return f.read()
                except Exception:
                    return ''
            def _read_docx(path: str) -> str:
                try:
                    from docx import Document  # python-docx
                except Exception:
                    return ''
                try:
                    doc = Document(path)
                    paras = []
                    for p in doc.paragraphs:
                        txt = (p.text or '').strip()
                        if txt:
                            paras.append(txt)
                    return '\n'.join(paras)
                except Exception:
                    return ''
            def _read_pdf(path: str) -> str:
                # 优先 PyMuPDF（fitz）
                try:
                    import fitz  # PyMuPDF
                except Exception:
                    fitz = None
                if fitz is None:
                    return ''
                try:
                    doc = fitz.open(path)
                    texts = []
                    for page in doc:
                        try:
                            t = page.get_text()
                            if t and t.strip():
                                texts.append(t)
                            else:
                                # 图片页尝试OCR降级
                                try:
                                    from PIL import Image
                                    import pytesseract
                                    pix = page.get_pixmap(dpi=200)
                                    import io
                                    img = Image.open(io.BytesIO(pix.tobytes('png')))
                                    ot = pytesseract.image_to_string(img, lang=getattr(self, 'settings_ocr_lang', type('x',(object,),{'text':lambda s:'chi_sim+eng'})()).text())
                                    if ot and ot.strip():
                                        texts.append(ot)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    return '\n'.join([t for t in texts if t and t.strip()])
                except Exception:
                    return ''
            def _read_xlsx(path: str) -> str:
                try:
                    import openpyxl
                except Exception:
                    return ''
                try:
                    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                    out_lines = []
                    for ws in wb.worksheets:
                        try:
                            out_lines.append(f'# Sheet: {ws.title}')
                        except Exception:
                            pass
                        for row in ws.iter_rows(values_only=True):
                            try:
                                vals = [str(c) if c is not None else '' for c in row]
                                # 简单以制表符连接
                                out_lines.append('\t'.join(vals).rstrip())
                            except Exception:
                                pass
                    return '\n'.join(out_lines)
                except Exception:
                    return ''
            def _read_csv(path: str) -> str:
                try:
                    import csv
                except Exception:
                    return _read_text(path)
                try:
                    out_lines = []
                    with open(path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
                        reader = csv.reader(f)
                        for row in reader:
                            try:
                                out_lines.append('\t'.join([str(x) for x in row]))
                            except Exception:
                                pass
                    return '\n'.join(out_lines)
                except Exception:
                    return _read_text(path)
            def _read_image_ocr(path: str) -> str:
                # 优先 pytesseract + PIL（需要本机安装 tesseract 可执行）
                try:
                    from PIL import Image
                    import pytesseract
                except Exception:
                    return ''
                try:
                    img = Image.open(path)
                    # 语言配置来自 UI
                    lang = 'chi_sim+eng'
                    try:
                        lang = self.settings_ocr_lang.text() or lang
                    except Exception:
                        pass
                    txt = pytesseract.image_to_string(img, lang=lang)
                    return (txt or '').strip()
                except Exception:
                    return ''
            def _read_audio_asr(path: str) -> str:
                # 尝试 faster-whisper（需模型，会自动下载；若不可用则返回空）
                try:
                    from faster_whisper import WhisperModel
                except Exception:
                    return ''
                try:
                    # 引擎与精度策略可扩展，这里固定 small/int8 以通用
                    model = WhisperModel("small", device="cpu", compute_type="int8")
                    segments, info = model.transcribe(path, language='zh')
                    texts = []
                    for seg in segments:
                        try:
                            texts.append(seg.text)
                        except Exception:
                            pass
                    return '\n'.join([t for t in texts if t and t.strip()])
                except Exception:
                    return ''
            def _prep_text(s: str) -> str:
                s = (s or '').replace('\r\n', '\n').replace('\r', '\n')
                # 轻度清洗：去多余空行，去左右空白
                lines = [ln.strip() for ln in s.split('\n')]
                # 合并连续空行
                out = []
                last_blank = False
                for ln in lines:
                    blank = (ln == '')
                    if blank and last_blank:
                        continue
                    out.append(ln)
                    last_blank = blank
                return '\n'.join(out).strip()
            def _chunk(s: str, size: int = 1500, overlap: int = 100) -> list[str]:
                s = s or ''
                if len(s) <= size:
                    return [s] if s else []
                chunks = []
                i = 0
                L = len(s)
                while i < L:
                    end = min(i + size, L)
                    chunks.append(s[i:end])
                    if end == L:
                        break
                    i = end - overlap if overlap > 0 else end
                return chunks
            for fp in files:
                ext = os.path.splitext(fp)[1].lower()
                txt = ''
                if ext in ('.txt', '.md', '.log'):
                    txt = _read_text(fp)
                elif ext == '.json':
                    txt = _read_text(fp)
                elif ext == '.csv':
                    txt = _read_csv(fp)
                elif ext == '.docx':
                    txt = _read_docx(fp)
                elif ext == '.pdf':
                    txt = _read_pdf(fp)
                elif ext == '.xlsx':
                    txt = _read_xlsx(fp)
                elif ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
                    txt = _read_image_ocr(fp)
                elif ext in ('.wav', '.mp3', '.m4a'):
                    txt = _read_audio_asr(fp)
                else:
                    # 类型未知：尝试按文本读取
                    txt = _read_text(fp)
                if not txt.strip():
                    skipped += 1
                    try:
                        self.settings_output.append(f"[灌注] 跳过（无法解析或空）：{os.path.basename(fp)}")
                    except Exception:
                        pass
                    continue
                if do_prep:
                    txt = _prep_text(txt)
                segs = _chunk(txt, size=chunk_size, overlap=overlap) if do_prep else [txt]
                if not segs:
                    skipped += 1
                    continue
                imported_at = datetime.utcnow().isoformat() + 'Z'
                base_id = str(uuid.uuid4())
                ids = []
                docs = []
                metas = []
                for idx, seg in enumerate(segs):
                    ids.append(f"{base_id}-{idx}")
                    docs.append(seg)
                    metas.append({
                        'mode': 'note',
                        'subtype': 'raw' if not do_prep else 'normalized',
                        'source_path': os.path.relpath(fp, base_dir),
                        'imported_at': imported_at,
                        'segment_index': idx,
                        'segment_total': len(segs),
                    })
                try:
                    col.add(documents=docs, metadatas=metas, ids=ids)
                    total_files += 1
                    total_chunks += len(segs)
                except Exception:
                    skipped += 1
                    continue
                # 进度
                try:
                    pct = int(((total_files + 1) / max(1, len(files))) * 100)
                    self._ingest_progress.setValue(pct)
                    if getattr(self, '_ingest_cancel', False):
                        self.settings_output.append('[灌注] 已取消')
                        break
                except Exception:
                    pass
            from PySide6.QtGui import QTextCursor
            self.settings_output.moveCursor(QTextCursor.End)
            self.settings_output.insertPlainText(f"\n[灌注] 完成：文件={total_files} | 分段={total_chunks} | 跳过={skipped}\n")
            self.settings_output.moveCursor(QTextCursor.End)
        except Exception as e:
            try:
                self.settings_output.append(f"[灌注] 失败：{str(e)[:200]}")
            except Exception:
                pass

    def _on_ingest_cancel(self):
        try:
            self._ingest_cancel = True
        except Exception:
            pass

    def _on_settings_vector_ingest_dir(self):
        """选择文件夹，递归导入所有受支持的文件类型。"""
        try:
            from PySide6.QtWidgets import QFileDialog
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            dir_path = QFileDialog.getExistingDirectory(self, '选择导入文件夹', base_dir)
            if not dir_path:
                return
            # 收集文件
            exts = {'.txt','.md','.log','.json','.csv','.docx','.pdf','.xlsx','.png','.jpg','.jpeg','.bmp','.webp','.wav','.mp3','.m4a'}
            files = []
            for root, _, fnames in os.walk(dir_path):
                for name in fnames:
                    if os.path.splitext(name)[1].lower() in exts:
                        files.append(os.path.join(root, name))
            if not files:
                try:
                    self.settings_output.append('[导入文件夹] 未找到可导入的文件')
                except Exception:
                    pass
                return
            # 复用单文件导入流程：直接设置为临时清单并调用核心逻辑
            # 简易方案：仿造 _on_settings_vector_ingest 的主体，避免重复选择器
            # 为保持代码简洁，这里直接调用文件选择导入流程，但将 files 覆盖
            # 实现：临时替换 QFileDialog.getOpenFileNames 的返回值（不修改库，直接内联逻辑）不现实
            # 故复制最核心处理段（小重复，保持可读性）
            try:
                # 构造一次性处理：调用内部私有处理器
                self._ingest_files_batch(files)
            except Exception:
                # 若内部私有处理不存在（首次调用），降级到局部实现
                pass
        except Exception as e:
            try:
                self.settings_output.append(f"[导入文件夹] 失败：{str(e)[:200]}")
            except Exception:
                pass

    def _ingest_files_batch(self, files: list[str]):
        """内部批量导入实现，供目录导入调用。"""
        try:
            import os, uuid
            from datetime import datetime
            from chromadb import PersistentClient
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            persistence = (self.settings_chroma_path.text() if hasattr(self, 'settings_chroma_path') else '') or ''
            collection = (self.settings_chroma_coll.text() if hasattr(self, 'settings_chroma_coll') else '') or ''
            if not persistence or not collection:
                self.settings_output.append('[灌注] 失败：chroma 路径或 collection 为空。')
                return
            client = PersistentClient(path=persistence)
            col = client.get_or_create_collection(collection)
            # 基本参数
            do_prep = bool(getattr(self, 'settings_ingest_preprocess', None) and self.settings_ingest_preprocess.isChecked())
            def _to_int(edit, default_val: int) -> int:
                try:
                    v = int(edit.text())
                    return v if v > 0 else default_val
                except Exception:
                    return default_val
            chunk_size = _to_int(getattr(self, 'settings_chunk_size', None) or type('x',(object,),{'text':lambda s:'1500'})(), 1500)
            overlap = _to_int(getattr(self, 'settings_chunk_overlap', None) or type('x',(object,),{'text':lambda s:'100'})(), 100)
            total_files = 0
            total_chunks = 0
            skipped = 0
            # 由于与上面函数有重复，这里最小复制关键读取器
            def _read_text(path: str) -> str:
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        return f.read()
                except Exception:
                    return ''
            def _prep_text(s: str) -> str:
                s = (s or '').replace('\r\n', '\n').replace('\r', '\n')
                lines = [ln.strip() for ln in s.split('\n')]
                out = []
                last_blank = False
                for ln in lines:
                    blank = (ln == '')
                    if blank and last_blank:
                        continue
                    out.append(ln)
                    last_blank = blank
                return '\n'.join(out).strip()
            def _chunk(s: str, size: int = 1500, overlap: int = 100) -> list[str]:
                s = s or ''
                if len(s) <= size:
                    return [s] if s else []
                chunks = []
                i = 0
                L = len(s)
                while i < L:
                    end = min(i + size, L)
                    chunks.append(s[i:end])
                    if end == L:
                        break
                    i = end - overlap if overlap > 0 else end
                return chunks
            try:
                self._ingest_cancel = False
                self._ingest_progress.setValue(0)
            except Exception:
                pass
            total_count = len(files)
            for idx_file, fp in enumerate(files):
                try:
                    txt = _read_text(fp)
                    if not txt.strip():
                        skipped += 1
                        continue
                    if do_prep:
                        txt = _prep_text(txt)
                    segs = _chunk(txt, size=chunk_size, overlap=overlap) if do_prep else [txt]
                    if not segs:
                        skipped += 1
                        continue
                    imported_at = datetime.utcnow().isoformat() + 'Z'
                    base_id = str(uuid.uuid4())
                    ids = []
                    docs = []
                    metas = []
                    for idx, seg in enumerate(segs):
                        ids.append(f"{base_id}-{idx}")
                        docs.append(seg)
                        metas.append({
                            'mode': 'note',
                            'subtype': 'raw' if not do_prep else 'normalized',
                            'source_path': os.path.relpath(fp, base_dir),
                            'imported_at': imported_at,
                            'segment_index': idx,
                            'segment_total': len(segs),
                        })
                    col.add(documents=docs, metadatas=metas, ids=ids)
                    total_files += 1
                    total_chunks += len(segs)
                    # 进度
                    try:
                        pct = int(((idx_file + 1) / max(1, total_count)) * 100)
                        self._ingest_progress.setValue(pct)
                        if getattr(self, '_ingest_cancel', False):
                            self.settings_output.append('[灌注] 已取消')
                            break
                    except Exception:
                        pass
                except Exception:
                    skipped += 1
                    continue
            from PySide6.QtGui import QTextCursor
            self.settings_output.moveCursor(QTextCursor.End)
            self.settings_output.insertPlainText(f"\n[导入文件夹] 完成：文件={total_files} | 分段={total_chunks} | 跳过={skipped}\n")
            self.settings_output.moveCursor(QTextCursor.End)
        except Exception as e:
            try:
                self.settings_output.append(f"[导入文件夹] 失败：{str(e)[:200]}")
            except Exception:
                pass

    # =============== GraphRAG 同步（导出/索引） ===============
    def _on_graphrag_export(self):
        """从 Chroma 导出文档到 graphrag/input（纯文本）。"""
        try:
            import os
            from chromadb import PersistentClient
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            persistence = (self.settings_chroma_path.text() if hasattr(self, 'settings_chroma_path') else '') or ''
            collection = (self.settings_chroma_coll.text() if hasattr(self, 'settings_chroma_coll') else '') or ''
            input_dir = (self.settings_gr_input.text() if hasattr(self, 'settings_gr_input') else 'graphrag/input')
            if not persistence or not collection:
                self.settings_output.append('[GraphRAG] 导出失败：chroma 路径或 collection 为空。')
                return
            abs_input = input_dir if os.path.isabs(input_dir) else os.path.join(base_dir, input_dir)
            os.makedirs(abs_input, exist_ok=True)
            client = PersistentClient(path=persistence)
            col = client.get_or_create_collection(collection)
            data = col.get()
            ids = data.get('ids') or []
            docs = data.get('documents') or []
            metas = data.get('metadatas') or []
            # 读取导出上限与过滤关键词
            try:
                limit_text = self.settings_export_limit.text().strip()
                export_limit = int(limit_text) if limit_text else 0
            except Exception:
                export_limit = 0
            try:
                kw = (self.settings_export_keyword.text() or '').strip()
            except Exception:
                kw = ''

            # 增量状态载入
            try:
                root_dir = (self.settings_gr_root.text() if hasattr(self, 'settings_gr_root') else 'graphrag')
                abs_root = root_dir if os.path.isabs(root_dir) else os.path.join(base_dir, root_dir)
                state_path = os.path.join(abs_root, '.state.json')
                import json as _json
                old_state = {}
                if hasattr(self, 'settings_export_incremental') and bool(self.settings_export_incremental.isChecked()):
                    if os.path.exists(state_path):
                        try:
                            with open(state_path, 'r', encoding='utf-8') as sf:
                                old_state = _json.load(sf) or {}
                        except Exception:
                            old_state = {}
                else:
                    old_state = {}
            except Exception:
                old_state = {}

            wrote = 0
            new_state = {}
            cnt_new, cnt_changed, cnt_skipped = 0, 0, 0
            for i, (id_, doc, md) in enumerate(zip(ids, docs, metas)):
                try:
                    text = (doc or '').strip()
                    if not text:
                        continue
                    # 仅导出“笔记”相关（mode=note）；优先包含 normalized/raw
                    m = md or {}
                    if (m.get('mode') or '').lower() != 'note':
                        continue
                    # 若勾选“仅导出 normalized”，则过滤 subtype
                    try:
                        norm_only = bool(self.settings_export_norm_only.isChecked())
                    except Exception:
                        norm_only = False
                    if norm_only:
                        if (m.get('subtype') or '').lower() != 'normalized':
                            continue
                    subtype = (m.get('subtype') or '').lower()
                    if subtype not in ('normalized', 'raw'):
                        # 放宽：若未标 subtype 也允许导出
                        pass
                    # 关键词过滤：在文本与metadata字符串中模糊匹配
                    if kw:
                        try:
                            hay = ' '.join([text, json.dumps(m, ensure_ascii=False)])
                            if kw.lower() not in hay.lower():
                                continue
                        except Exception:
                            pass
                    # 计算指纹并做增量判断
                    try:
                        import hashlib
                        ident = str(id_ or f'doc_{i}')
                        digest = hashlib.md5(text.encode('utf-8', errors='ignore')).hexdigest()
                        fp_key = f"{ident}:{digest}"
                        new_state[ident] = digest
                        if old_state and old_state.get(ident) == digest:
                            # 未变更，跳过
                            cnt_skipped += 1
                            continue
                        else:
                            if old_state and ident in old_state and old_state.get(ident) != digest:
                                cnt_changed += 1
                            else:
                                cnt_new += 1
                    except Exception:
                        pass
                    # 文件名：优先使用 id；否则按序号
                    name = str(id_ or f'doc_{i}').replace('/', '_')
                    fp = os.path.join(abs_input, f'{name}.txt')
                    with open(fp, 'w', encoding='utf-8', errors='ignore') as f:
                        f.write(text)
                    wrote += 1
                    if export_limit and wrote >= export_limit:
                        break
                except Exception:
                    continue
            from PySide6.QtGui import QTextCursor
            self.settings_output.moveCursor(QTextCursor.End)
            extra = []
            if export_limit:
                extra.append(f"limit={export_limit}")
            if kw:
                extra.append(f"kw='{kw}'")
            if old_state:
                extra.append("incremental=true")
            extra_text = (" (" + ", ".join(extra) + ")") if extra else ""
            summary = f" 新增:{cnt_new} 变更:{cnt_changed} 跳过未变更:{cnt_skipped}"
            self.settings_output.insertPlainText(f"\n[GraphRAG] 导出完成：{wrote} 条 → {abs_input}{extra_text}{summary}\n")
            # 写回新状态（仅在启用增量时）
            try:
                if hasattr(self, 'settings_export_incremental') and bool(self.settings_export_incremental.isChecked()):
                    os.makedirs(abs_root, exist_ok=True)
                    with open(state_path, 'w', encoding='utf-8') as sf:
                        _json.dump(new_state, sf, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self.settings_output.moveCursor(QTextCursor.End)
        except Exception as e:
            try:
                self.settings_output.append(f"[GraphRAG] 导出失败：{str(e)[:200]}")
            except Exception:
                pass

    def _check_parsers_dependencies(self):
        """检查解析器依赖是否可用，并打印缺失项。"""
        try:
            checks = [
                ("pymupdf", 'import fitz'),
                ("python-docx", 'from docx import Document'),
                ("openpyxl", 'import openpyxl'),
                ("pillow", 'from PIL import Image'),
                ("pytesseract", 'import pytesseract'),
                ("faster-whisper", 'from faster_whisper import WhisperModel'),
            ]
            missing = []
            for pkg, stmt in checks:
                try:
                    exec(stmt, {})
                except Exception:
                    missing.append(pkg)
            if missing:
                self.settings_output.append('[依赖检测] 缺失: ' + ', '.join(missing))
            else:
                self.settings_output.append('[依赖检测] 所有可选解析器依赖均可用')
        except Exception as e:
            try:
                self.settings_output.append(f"[依赖检测] 失败：{str(e)[:200]}")
            except Exception:
                pass

    def _print_install_commands(self):
        """打印安装可选解析器的 PowerShell 命令（不直接执行）。"""
        try:
            cmds = [
                'pip install pymupdf',
                'pip install python-docx',
                'pip install openpyxl',
                'pip install pillow pytesseract',
                'pip install faster-whisper',
            ]
            self.settings_output.append('[安装命令] 建议在PowerShell中逐条执行（或选用所需项）:\n' + '\n'.join(cmds))
            self.settings_output.append('注意：OCR 需本机安装 tesseract 可执行，并配置语言包（如 chi_sim）。')
        except Exception:
            pass

    def _on_graphrag_index(self):
        """执行 graphrag index（需要已安装 graphrag CLI）。"""
        try:
            import os, subprocess
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            root_dir = (self.settings_gr_root.text() if hasattr(self, 'settings_gr_root') else 'graphrag')
            cfg = (self.settings_gr_yaml.text() if hasattr(self, 'settings_gr_yaml') else 'graphrag/settings.yaml')
            abs_root = root_dir if os.path.isabs(root_dir) else os.path.join(base_dir, root_dir)
            abs_cfg = cfg if os.path.isabs(cfg) else os.path.join(base_dir, cfg)
            cmd = ['graphrag', 'index', '--root', abs_root, '--config', abs_cfg]
            result = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=600)
            out = result.stdout or ''
            err = result.stderr or ''
            from PySide6.QtGui import QTextCursor
            self.settings_output.moveCursor(QTextCursor.End)
            self.settings_output.insertPlainText(f"\n[GraphRAG] 重建索引：命令={' '.join(cmd)}\n")
            if out.strip():
                self.settings_output.insertPlainText(out + "\n")
            if err.strip():
                self.settings_output.insertPlainText("[stderr]\n" + err + "\n")
            self.settings_output.moveCursor(QTextCursor.End)
        except FileNotFoundError:
            try:
                self.settings_output.append('[GraphRAG] 失败：未找到 graphrag 可执行（请 pip install graphrag 或确保 PATH）。')
            except Exception:
                pass
        except Exception as e:
            try:
                self.settings_output.append(f"[GraphRAG] 索引失败：{str(e)[:200]}")
            except Exception:
                pass

    def _on_graphrag_reset_state(self):
        """删除增量同步状态文件 graphrag/.state.json。"""
        try:
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            root_dir = (self.settings_gr_root.text() if hasattr(self, 'settings_gr_root') else 'graphrag')
            abs_root = root_dir if os.path.isabs(root_dir) else os.path.join(base_dir, root_dir)
            state_path = os.path.join(abs_root, '.state.json')
            if os.path.exists(state_path):
                os.remove(state_path)
                self.settings_output.append('[GraphRAG] 已重置增量状态（删除 .state.json）。')
            else:
                self.settings_output.append('[GraphRAG] 未找到 .state.json，已跳过。')
        except Exception as e:
            try:
                self.settings_output.append(f"[GraphRAG] 重置增量状态失败：{str(e)[:200]}")
            except Exception:
                pass

    def _on_graphrag_sync(self):
        """一键同步：先导出再重建索引。"""
        try:
            self._on_graphrag_export()
            self._on_graphrag_index()
        except Exception as e:
            try:
                self.settings_output.append(f"[GraphRAG] 一键同步失败：{str(e)[:200]}")
            except Exception:
                pass

    # =============== 日志查看 ===============
    def _open_logs_dialog(self):
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle('日志查看')
            lay = QVBoxLayout(dlg)
            row = QWidget(); row_l = QHBoxLayout(row); row_l.setContentsMargins(0,0,0,0)
            row_l.addWidget(QLabel('选择日志文件:'))
            cb = QComboBox(); row_l.addWidget(cb, 1)
            btn_reload = QPushButton('刷新'); row_l.addWidget(btn_reload)
            lay.addWidget(row)
            view = QTextEdit(); view.setReadOnly(True)
            lay.addWidget(view, 1)

            import os, glob
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            logs_dir = os.path.join(base_dir, 'logs')

            def _list_files():
                files = []
                try:
                    patterns = ['*.log', '*.jsonl', '*.json', '*.txt']
                    for p in patterns:
                        files.extend(glob.glob(os.path.join(logs_dir, p)))
                    files = sorted(files, key=lambda x: os.path.getmtime(x), reverse=True)
                except Exception:
                    files = []
                return files

            def _load(path: str, tail_lines: int = 500):
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    if tail_lines and len(lines) > tail_lines:
                        lines = lines[-tail_lines:]
                    view.setPlainText(''.join(lines))
                    try:
                        view.moveCursor(QTextCursor.End)
                    except Exception:
                        pass
                except Exception as e:
                    view.setPlainText(f"读取失败: {e}")

            def _refresh():
                files = _list_files()
                cb.blockSignals(True)
                cb.clear()
                for fp in files:
                    cb.addItem(os.path.basename(fp), fp)
                cb.blockSignals(False)
                if files:
                    _load(files[0])

            def _on_sel(idx: int):
                p = cb.currentData()
                if p:
                    _load(p)

            btn_reload.clicked.connect(_refresh)
            cb.currentIndexChanged.connect(_on_sel)
            _refresh()
            dlg.resize(820, 560)
            dlg.exec()
        except Exception as e:
            try:
                self.settings_output.append(f"[日志] 打开失败：{str(e)[:200]}")
            except Exception:
                pass

    # =============== 持久化会话（方案A：子进程常驻） ===============
    def _on_settings_start_session(self):
        try:
            import subprocess, sys, os, threading
            if getattr(self, '_settings_proc', None) is not None:
                self._settings_status.setText('已连接')
                return
            script = (self.settings_script.text() or '').strip()
            team = (self.settings_team.text() or '').strip()
            envf = (self.settings_env.text() or '').strip()
            rounds = (self.settings_rounds.text() or '1').strip()
            timeout_s = (self.settings_timeout.text() or '180').strip()
            if not script or not os.path.exists(script):
                self._settings_status.setText('脚本无效')
                return
            if not team or not os.path.exists(team):
                self._settings_status.setText('team无效')
                return
            cmd = [
                sys.executable, '-X', 'utf8', '-u',
                script,
                '--team-json', team,
                '--max-rounds', rounds,
                '--timeout', timeout_s,
                '--env-file', envf,
                '--stdin-mode', 'interactive',
            ]
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            proc = subprocess.Popen(
                cmd, cwd=base_dir,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='ignore', bufsize=1
            )
            self._settings_proc = proc
            self._settings_stdout_buf = []
            self._settings_stderr_buf = []
            # 读取线程
            def _read_stdout():
                try:
                    for line in iter(proc.stdout.readline, ''):
                        if not line:
                            break
                        self._settings_stdout_buf.append(line)
                except Exception:
                    pass
            def _read_stderr():
                try:
                    for line in iter(proc.stderr.readline, ''):
                        if not line:
                            break
                        self._settings_stderr_buf.append(line)
                except Exception:
                    pass
            self._settings_th_out = threading.Thread(target=_read_stdout, daemon=True)
            self._settings_th_err = threading.Thread(target=_read_stderr, daemon=True)
            self._settings_th_out.start(); self._settings_th_err.start()
            # 定时刷新输出到UI（主线程）
            from PySide6.QtCore import QTimer
            self._settings_timer = QTimer(self)
            def _flush_buffers():
                try:
                    if self._settings_stdout_buf:
                        chunk = ''.join(self._settings_stdout_buf)
                        self._settings_stdout_buf.clear()
                        self._append_output(chunk)
                    if self._settings_stderr_buf:
                        # 只打印尾部到控制台
                        tail = ''.join(self._settings_stderr_buf[-30:])
                        self._settings_stderr_buf.clear()
                        print(f"[SETTINGS][live][stderr-tail]\n{tail}")
                except Exception:
                    pass
            self._settings_timer.timeout.connect(_flush_buffers)
            self._settings_timer.start(200)
            self._settings_status.setText('已连接')
            try:
                self._settings_status.setStyleSheet('color: green;')
                # 轻量提示连接成功
                try:
                    self._append_output('[连接] 已建立长驻会话\n')
                except Exception:
                    pass
            except Exception:
                pass
        except Exception as e:
            try:
                self._settings_status.setText('连接失败')
                try:
                    self._settings_status.setStyleSheet('color: red;')
                except Exception:
                    pass
                print(f"[SETTINGS][live][error] {e}")
            except Exception:
                pass

    def _on_settings_stop_session(self):
        try:
            proc = getattr(self, '_settings_proc', None)
            if not proc:
                self._settings_status.setText('未连接')
                return
            try:
                proc.stdin.write(':quit\n')
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                if getattr(self, '_settings_timer', None):
                    self._settings_timer.stop()
                    self._settings_timer = None
            except Exception:
                pass
            self._settings_proc = None
            self._settings_status.setText('未连接')
            try:
                self._settings_status.setStyleSheet('color: gray;')
            except Exception:
                pass
        except Exception:
            try:
                self._settings_status.setText('断开异常')
                try:
                    self._settings_status.setStyleSheet('color: red;')
                except Exception:
                    pass
            except Exception:
                pass

    def _settings_send_line(self, text: str, mode: str):
        try:
            proc = getattr(self, '_settings_proc', None)
            if not proc or not proc.stdin:
                # 未连接则提示
                self._settings_status.setText('未连接')
                return
            msg = self._settings_prepare_message(text, mode)
            if not msg:
                return
            proc.stdin.write(msg + '\n')
            proc.stdin.flush()
        except Exception as e:
            try:
                self._settings_status.setText('发送失败')
                print(f"[SETTINGS][live][send-error] {e}")
            except Exception:
                pass

    def _settings_on_return(self, mode: str):
        """按回车时的统一入口：优先使用长驻会话；如未连接则回退到一次性运行。"""
        try:
            text = ''
            if mode == 'note' and hasattr(self, 'settings_note_input'):
                text = self.settings_note_input.text()
            elif mode == 'qa' and hasattr(self, 'settings_qa_input'):
                text = self.settings_qa_input.text()
            msg = self._settings_prepare_message(text, mode)
            if not msg:
                return
            # 将本次输入回显到右侧输出，并清空输入框
            try:
                label = '笔记' if mode == 'note' else '问答'
                self._append_output(f"[{label}] {msg}\n")
            except Exception:
                pass
            try:
                if mode == 'note' and hasattr(self, 'settings_note_input'):
                    self.settings_note_input.clear()
                elif mode == 'qa' and hasattr(self, 'settings_qa_input'):
                    self.settings_qa_input.clear()
            except Exception:
                pass
            # 路由策略：
            # - 笔记模式且包含换行 -> 使用一次性运行（保留原始换行，不拆分多轮）
            # - 其他 -> 若有会话则发送，否则一次性运行
            if mode == 'note' and ('\n' in text or '\r' in text):
                # 一次性笔记：使用隐性分隔符包裹全文，强标记 OneShot
                oneshot = self._build_oneshot_note_payload(text)
                self._settings_run(oneshot, mode)
                return
            proc = getattr(self, '_settings_proc', None)
            if proc and proc.stdin:
                self._settings_send_line(msg, mode)
                return
            self._settings_run(msg, mode)
        except Exception as e:
            try:
                print(f"[SETTINGS][on-return][error] {e}")
            except Exception:
                pass

    def _settings_prepare_message(self, text: str, mode: str) -> str:
        try:
            msg = (text or '')
            if mode != 'note':
                # 问答保持单行，避免交互模式拆多轮
                msg = msg.replace('\r\n', '\n')
                msg = ' '.join([ln.strip() for ln in msg.split('\n') if ln.strip()])
            if mode == 'note' and msg and (not msg.startswith('#笔记')):
                msg = '#笔记 ' + msg
            return msg
        except Exception:
            return text or ''

    def _build_oneshot_note_payload(self, text: str) -> str:
        """构造一次性（OneShot）笔记提交体：
        - 首行确保以 #笔记 开头
        - 使用隐性分隔符包裹正文：<!-- NOTE-ONESHOT:BEGIN --> / <!-- NOTE-ONESHOT:END -->
        - 保留原始 Markdown 格式与换行
        """
        try:
            raw = text or ''
            # 统一换行
            raw = raw.replace('\r\n', '\n')
            head = '#笔记'
            # 确保首行是 #笔记
            if not raw.lstrip().startswith(head):
                # 若用户已手动写了 #笔记，我们不重复；否则在最前插入一行
                raw = f"{head}\n{raw}" if raw else head
            # 将首行与正文拆分：第一行视为可能的 #笔记 行
            parts = raw.split('\n', 1)
            first = parts[0] if parts else head
            rest = parts[1] if len(parts) > 1 else ''
            # 如果首行包含除 #笔记 外的文字，也视为正文一部分
            if first.strip() != head:
                # 去掉首行开头的 #笔记 前缀，其余并入正文
                if first.strip().startswith(head):
                    rest = (first.strip()[len(head):].lstrip() + ('\n' + rest if rest else '')).lstrip('\n')
                else:
                    # 非标准情形，保守：仍把首行加入正文
                    rest = (first + ('\n' + rest if rest else ''))
                first = head
            # 包裹分隔符，仅正文放入内层
            begin = '<!-- NOTE-ONESHOT:BEGIN -->'
            end = '<!-- NOTE-ONESHOT:END -->'
            body = rest
            payload = f"{first}\n{begin}\n{body}\n{end}"
            return payload
        except Exception:
            # 失败则退回简单前缀版本
            return self._settings_prepare_message(text or '', 'note')

    def _settings_run(self, text: str, mode: str = 'note'):
        """公共运行器：mode in {'note','qa'}。仅拼接命令并承接I/O。"""
        try:
            import subprocess, sys, os
            script = (self.settings_script.text() or '').strip()
            team = (self.settings_team.text() or '').strip()
            envf = (self.settings_env.text() or '').strip()
            rounds = (self.settings_rounds.text() or '1').strip()
            timeout_s = (self.settings_timeout.text() or '180').strip()
            if not script or not os.path.exists(script):
                self.settings_output.setPlainText('脚本路径无效。')
                return
            if not team or not os.path.exists(team):
                self.settings_output.setPlainText('team-json 路径无效。')
                return
            # 回显输入
            try:
                label = '笔记' if mode == 'note' else '问答'
                self.settings_output.moveCursor(self.settings_output.textCursor().End)
                self.settings_output.insertPlainText(f"[{label}] {text}\n")
                self.settings_output.moveCursor(self.settings_output.textCursor().End)
            except Exception:
                pass
            # 组装命令
            cmd = [
                sys.executable,
                '-X', 'utf8', '-u',
                script,
                '--team-json', team,
                '--max-rounds', rounds,
                '--timeout', timeout_s,
                '--env-file', envf,
            ]
            # stdin
            # 单次模式也压缩多行为单行，保持与交互一致
            t = (text or '').replace('\r\n', '\n')
            t = ' '.join([ln.strip() for ln in t.split('\n') if ln.strip()])
            stdin_text = t + "\n:quit\n"
            # 执行
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            try:
                result = subprocess.run(
                    cmd, cwd=base_dir, input=stdin_text,
                    capture_output=True, text=True, encoding='utf-8', errors='ignore',
                    timeout=float(timeout_s) + 15.0,
                )
            except subprocess.TimeoutExpired:
                self.settings_output.setPlainText('执行超时。')
                return
            # 输出
            out = result.stdout or ''
            try:
                text_to_add = ("\n" + out) if out and (not out.startswith('\n')) else (out or '')
                self._append_output(text_to_add)
            except Exception:
                # 兜底：若失败仍回退覆盖式
                self.settings_output.setPlainText(out)
            # 诊断：stderr 尾部打印到控制台
            try:
                err = result.stderr or ''
                if err.strip():
                    lines = [l for l in err.splitlines() if l.strip()]
                    tail = "\n".join(lines[-30:]) if lines else err
                    print(f"[SETTINGS][{mode}][stderr-tail]\n{tail}")
            except Exception:
                pass
        except Exception as e:
            self.settings_output.setPlainText(f"运行失败：{str(e)[:200]}")
        
    def _create_config_explorer_tab(self):
        """创建配置浏览器页面，显示配置文件目录树和详情"""
        try:
            # 创建配置浏览器页面实例
            config_explorer = ConfigExplorerPage()
            # 添加到主选项卡
            self.tabs.addTab(config_explorer, "配置浏览器")
        except Exception as e:
            self.logger.error(f"创建配置浏览器页面失败: {e}")
            # 创建错误提示页面
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.addWidget(QLabel(f"配置浏览器加载失败: {e}"))
            self.tabs.addTab(widget, "配置浏览器")

    def _create_team_tab(self):
        """创建 Team 页面（集成TeamManagementPage）"""
        # 创建TeamManagementPage实例
        self.team_management_page = TeamManagementPage(self)
        
        # 添加到主选项卡
        self.tabs.addTab(self.team_management_page, "Team")

    def _create_warehouse_tab(self):
        """创建 Warehouse 页面：改为二级信息卡结构，内嵌向量库管理器为第一页。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 标题
        title = QLabel("资源仓库：工具 / MCP / 向量库")
        try:
            f = title.font(); f.setBold(True); title.setFont(f)
        except Exception:
            pass
        layout.addWidget(title)

        # 二级选项卡
        sub_tabs = QTabWidget()

        # 子页1：向量库管理器（内嵌，不再弹出对话框）
        vs_page = QWidget(); vs_layout = QVBoxLayout(vs_page)
        try:
            vs_dialog = WarehouseVectorStoresDialog(self)
            # 作为子部件嵌入
            try:
                # 以部件方式显示，避免作为独立窗口
                vs_dialog.setParent(vs_page)
                vs_dialog.setWindowFlags(Qt.Widget)
            except Exception:
                pass
            # 信号桥接到主窗口
            try:
                vs_dialog.memory_mounted.connect(self._on_memory_mounted)
            except Exception:
                pass
            vs_layout.addWidget(vs_dialog)
        except Exception as e:
            # 若创建失败，给出占位说明
            err = QLabel(f"向量库管理器加载失败：{str(e)[:200]}")
            err.setWordWrap(True)
            vs_layout.addWidget(err)

        sub_tabs.addTab(vs_page, "向量库管理器")

        # 子页2：双库生成器（作为并列Tab嵌入，移除原先在向量库页中的弹窗入口）
        dual_page = QWidget(); dual_layout = QVBoxLayout(dual_page)
        try:
            dual_dialog = WarehouseDualLibraryDialog(self)
            try:
                dual_dialog.setParent(dual_page)
                dual_dialog.setWindowFlags(Qt.Widget)
            except Exception:
                pass
            # 将双库生成器发出的 kb/chat 两个 ComponentModel 直接并入当前 Agent
            def _on_dual_mounted(kb: Dict[str, Any], chat: Dict[str, Any]):
                try:
                    self._on_memory_mounted("chromadb_kb", kb)
                    self._on_memory_mounted("chromadb_chat", chat)
                except Exception:
                    pass
            try:
                dual_dialog.dual_memory_mounted.connect(_on_dual_mounted)
            except Exception:
                pass
            dual_layout.addWidget(dual_dialog)
        except Exception as e:
            err2 = QLabel(f"双库生成器加载失败：{str(e)[:200]}")
            err2.setWordWrap(True)
            dual_layout.addWidget(err2)

        sub_tabs.addTab(dual_page, "双库生成器")

        # 子页3：概览/说明 信息卡（占位，可后续扩展为工具/MCP卡片式仓库）
        info_page = QWidget(); info_layout = QVBoxLayout(info_page)
        info = QLabel(
            "概览：\n"
            "- 本页整合仓库资源为二级卡片。\n"
            "- 第1页：AutoGen 0.7.1 原生向量库管理器，支持挂载为 Memory。\n"
            "- 第2页：双库生成器（KB/Chat），可直接挂载两条 Memory。\n"
            "- 预留后续卡片：工具仓库（卡片+筛选）、MCP 仓库（卡片+筛选）。"
        )
        info.setWordWrap(True)
        info_layout.addWidget(info)
        info_layout.addStretch(1)
        sub_tabs.addTab(info_page, "概览")

        layout.addWidget(sub_tabs)

        self.tabs.addTab(widget, "Warehouse")

    def _create_project_tab(self):
        """创建 Project 页面（占位实现，防止缺失导致崩溃）。"""
        try:
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.addWidget(QLabel("Project 页面（占位）\n- 后续在此集成项目级脚本与批处理入口、索引与清理管控。"))
            self.tabs.addTab(widget, "Project")
        except Exception as e:
            # 兜底：若页面创建失败，显示错误占位
            fallback = QWidget()
            v = QVBoxLayout(fallback)
            v.addWidget(QLabel(f"Project 页面加载失败：{str(e)[:200]}"))
            self.tabs.addTab(fallback, "Project")

    def _on_memory_mounted(self, sid: str, memory_entry: dict):
        """接收仓库（向量库/双库生成器）发来的 Memory 条目并合入当前Agent配置。
        - 不进行隐式归一化；遵循AutoGen 0.7.1字段。
        - 若当前无Agent数据，则创建一个最小Agent以便挂载（不落盘）。
        - 刷新右侧“记忆”名称列表与Agent详情预览。
        """
        try:
            if not isinstance(memory_entry, dict):
                return
            # 确保存在内存中的 agent_data
            if not isinstance(getattr(self, 'agent_data', None), dict) or not self.agent_data:
                try:
                    # 创建一个最小Agent占位，避免用户必须先选择/新建
                    self.agent_data = {
                        "type": "agent",
                        "name": "Assistant",
                        "role": "assistant",
                        "system_message": "You are a helpful assistant.",
                        "model_client": {
                            "provider": "autogen_ext.models.openai.OpenAIChatCompletionClient",
                            "config": {"model": "qwen-turbo-latest"}
                        },
                        "memory": [],
                        "tools": [],
                        "_autogen_version": "0.7.1",
                        "capabilities": []
                    }
                except Exception:
                    return
            # 合入 memory 条目
            mem = self.agent_data.get('memory')
            if not isinstance(mem, list):
                mem = []
                self.agent_data['memory'] = mem
            mem.append(memory_entry)
            # UI反馈
            try:
                ErrorHandler.handle_success(self, "已挂载", f"已挂载Memory：{sid}")
            except Exception:
                pass
            # 刷新右侧“记忆”列表
            try:
                if hasattr(self, 'right_vs_list'):
                    self._refresh_right_vectorstores_tab()
            except Exception:
                pass
            # 刷新 Agent 详情表单（只读展示）
            try:
                self._refresh_right_agent_detail_tab()
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"接收Memory挂载失败: {e}")
            except Exception:
                pass

    # 右栏 Tabs：刷新与事件
    def _on_right_tab_changed(self, idx: int):
        # 新结构：0=AssistantAgent，1=MultimodalWebSurfer，2=SocietyOfMindAgent，3=OpenAIAgent
        if idx == 0:
            self._refresh_right_agent_detail_tab()
        else:
            # 其他页签当前仅展示，不做自动刷新
            pass

    # 新增：工具
    def _new_tool(self):
        try:
            text, ok = QInputDialog.getText(self, "新增工具", "工具ID（如 google.search）:")
            if not ok or not text.strip():
                return
            if not hasattr(self, "agent_data") or not isinstance(self.agent_data, dict):
                self.agent_data = {"type": "agent", "tools": []}
            tools = self.agent_data.get("tools", []) or []
            tools.append({"id": text.strip()})
            self.agent_data["tools"] = tools
            self._refresh_right_tools_tab()
            ErrorHandler.handle_success(self, "成功", f"已新增工具：{text.strip()}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "新增工具失败", e)

    # 新增：向量库
    def _new_vs(self):
        try:
            name, ok = QInputDialog.getText(self, "新增向量库", "向量库名称（collection_name）:")
            if not ok or not name.strip():
                return
            vendor, _ = QInputDialog.getText(self, "新增向量库", "厂商（可选）:")
            item = {"name": name.strip()}
            if vendor and vendor.strip():
                item["vendor"] = vendor.strip()
            if not hasattr(self, "_custom_vectorstores"):
                self._custom_vectorstores = []
            self._custom_vectorstores.append(item)
            self._refresh_right_vectorstores_tab()
            ErrorHandler.handle_success(self, "成功", f"已新增向量库：{name.strip()}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "新增向量库失败", e)

    # 新增：MCP
    def _new_mcp(self):
        try:
            name, ok = QInputDialog.getText(self, "新增MCP", "服务名（name）:")
            if not ok or not name.strip():
                return
            typ, _ = QInputDialog.getText(self, "新增MCP", "类型（proc/stdio/http，默认proc）:")
            from repositories.mcp_repo import MCPRepository
            repo = MCPRepository()
            reg = repo.get_servers()
            servers = reg.get("servers", [])
            servers.append({"name": name.strip(), "type": (typ.strip() if typ and typ.strip() else "proc")})
            reg["servers"] = servers
            repo.save_servers(reg)
            self._refresh_right_mcp_tab()
            ErrorHandler.handle_success(self, "成功", f"已新增MCP：{name.strip()}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "新增MCP失败", e)

    # 新增：Agent 配置
    def _new_agent_config(self):
        try:
            # 基于用户规则和记忆，默认加入“必须调用工具/结构化输出”约束
            default_agent = {
                "type": "agent",
                "name": "Assistant",
                "role": "assistant",
                "system_message": "You are a helpful assistant.\n\n【重要约束】你必须调用工具或使用结构化输出格式回答。",
                "model_client": {
                    "provider": "autogen_ext.models.openai.OpenAIChatCompletionClient",
                    "config": {
                        "model": self.det_model.currentText() or "qwen-turbo-latest",
                        "api_key_env": "DASHSCOPE_API_KEY" if "qwen" in (self.det_model.currentText() or "") else "OPENAI_API_KEY",
                        "base_url": ("https://dashscope.aliyuncs.com/compatible-mode/v1" if "qwen" in (self.det_model.currentText() or "") else ""),
                        "model_info": {
                            "api_type": "openai",
                            "family": "qwen" if "qwen" in (self.det_model.currentText() or "") else "openai",
                            "vision": False,
                            "function_calling": True,
                            "json_output": True,
                            "structured_output": False,
                            "organization": None,
                            "timeout": None
                        },
                        "timeout": 60,
                        "parameters": {
                            "temperature": float(self.det_temperature.value()),
                            "top_p": float(self.det_top_p.value()),
                            "max_tokens": int(self.det_max_tokens.value())
                        }
                    }
                },
                "memory": [],
                "memory_write_policy": "qa_both",
                "tools": [],
                "_autogen_version": "0.7.1",
                "capabilities": []
            }
            self.agent_data = default_agent
            # 回填表单并刷新预览
            self._refresh_right_agent_detail_tab()
            ErrorHandler.handle_success(self, "成功", "已创建新的Agent配置")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "新增Agent失败", e)

    def _bind_agent_detail_form_signals(self):
        """绑定 Agent 详情表单的信号到 JSON 同步方法。"""
        try:
            # 基本信息
            if hasattr(self, 'det_name'):
                self.det_name.textChanged.connect(self._sync_agent_form_to_json)
            if hasattr(self, 'det_role') and getattr(self, 'det_role') is not None:
                self.det_role.textChanged.connect(self._sync_agent_form_to_json)
            # 下拉框
            if hasattr(self, 'det_agent_type') and getattr(self, 'det_agent_type') is not None:
                self.det_agent_type.currentTextChanged.connect(self._sync_agent_form_to_json)
            if hasattr(self, 'det_model') and getattr(self, 'det_model') is not None:
                self.det_model.currentTextChanged.connect(self._sync_agent_form_to_json)
            # 数值参数
            for attr in ('det_temperature','det_top_p','det_max_tokens','det_presence_penalty','det_frequency_penalty'):
                if hasattr(self, attr) and getattr(self, attr) is not None:
                    try:
                        getattr(self, attr).valueChanged.connect(self._sync_agent_form_to_json)
                    except Exception:
                        pass
        except Exception as e:
            self.logger.warning(f"绑定Agent表单信号失败: {e}")

    def _sync_agent_form_to_json(self):
        """将右侧详情表单字段同步到内存中的 self.agent_data。
        注意：不做结构归一化或隐式迁移，仅更新显式字段。
        适配新版字段：description/system_message/reflect_on_tool_use/tool_call_summary_format/
        model_client_stream/max_tool_iterations/model_context/metadata/structured_message_factory。
        """
        try:
            data = getattr(self, 'agent_data', None)
            if not isinstance(data, dict):
                data = {"type": "agent"}
            # 基本字段
            if hasattr(self, 'det_name'):
                _new_name = (self.det_name.text() or '').strip()
                data["name"] = _new_name
                # 若存在运行期 config 字典，则同时回写 config.name，保持一致
                try:
                    _cfg0 = data.get('config')
                    if isinstance(_cfg0, dict):
                        _cfg0['name'] = _new_name
                        data['config'] = _cfg0
                except Exception:
                    pass
            # 新字段（严格对齐 0.7.1）
            if hasattr(self, 'det_description') and self.det_description is not None:
                data["description"] = (self.det_description.toPlainText() or '').strip()
            if hasattr(self, 'det_system_message') and self.det_system_message is not None:
                # system_message 为字符串；若为空则不强行写 None
                sm = (self.det_system_message.toPlainText() or '').strip()
                if sm != '':
                    data["system_message"] = sm
                else:
                    # 清空时保留原值，不隐式删除
                    pass
            if hasattr(self, 'det_reflect_on_tool_use') and self.det_reflect_on_tool_use is not None:
                try:
                    data["reflect_on_tool_use"] = bool(self.det_reflect_on_tool_use.isChecked())
                except Exception:
                    pass
            if hasattr(self, 'det_tool_call_summary_format') and self.det_tool_call_summary_format is not None:
                data["tool_call_summary_format"] = (self.det_tool_call_summary_format.toPlainText() or '').strip()
            if hasattr(self, 'det_model_client_stream') and self.det_model_client_stream is not None:
                try:
                    data["model_client_stream"] = bool(self.det_model_client_stream.isChecked())
                except Exception:
                    pass
            if hasattr(self, 'det_max_tool_iterations') and self.det_max_tool_iterations is not None:
                try:
                    data["max_tool_iterations"] = int(self.det_max_tool_iterations.value())
                except Exception:
                    pass
            if hasattr(self, 'det_model_context') and self.det_model_context is not None:
                # 仅记录名称/标识符文本
                data["model_context"] = (self.det_model_context.text() or '').strip()
            if hasattr(self, 'det_metadata') and self.det_metadata is not None:
                # 前端不做隐式转换：尝试解析JSON，失败则存字符串
                meta_str = (self.det_metadata.toPlainText() or '').strip()
                if meta_str:
                    try:
                        import json as _json
                        data["metadata"] = _json.loads(meta_str)
                    except Exception:
                        data["metadata"] = meta_str
            if hasattr(self, 'det_structured_message_factory') and self.det_structured_message_factory is not None:
                data["structured_message_factory"] = (self.det_structured_message_factory.text() or '').strip()

            # 模型（保持原结构，若无则按最小结构补齐）
            mc = data.get("model_client")
            if not isinstance(mc, dict):
                mc = {"provider": "", "config": {"model": ""}}
            cfg = mc.get("config") or {}
            if not isinstance(cfg, dict):
                cfg = {"model": ""}
            if hasattr(self, 'det_model') and self.det_model is not None:
                cfg["model"] = (self.det_model.currentText() or '').strip()
            mc["config"] = cfg
            data["model_client"] = mc
            # 回写
            self.agent_data = data
        except Exception as e:
            try:
                self.logger.warning(f"同步Agent表单失败: {e}")
            except Exception:
                pass

    def _refresh_det_model_candidates(self):
        """刷新 Agent 详情页中的模型下拉候选项，来源于本地 config/models。"""
        try:
            if not hasattr(self, 'det_model'):
                return
            self.det_model.blockSignals(True)
            self.det_model.clear()
            base_dir = Path(__file__).parent.parent.parent
            models_dir = base_dir / 'config' / 'models'
            seen = set()
            if models_dir.exists() and models_dir.is_dir():
                for p in sorted(models_dir.glob('*.json')):
                    try:
                        with p.open('r', encoding='utf-8') as f:
                            obj = json.load(f)
                        cfg = dict((obj or {}).get('config') or {})
                        name = cfg.get('model') or obj.get('model') or obj.get('name') or p.stem
                        if not name:
                            continue
                        if name in seen:
                            continue
                        seen.add(name)
                        # 仅展示模型名文本，不做隐式映射
                        self.det_model.addItem(str(name))
                    except Exception:
                        continue
        except Exception as e:
            try:
                self.logger.warning(f"刷新Agent详情模型候选失败: {e}")
            except Exception:
                pass
        finally:
            try:
                self.det_model.blockSignals(False)
            except Exception:
                pass

    # Tools Tab
    def _refresh_right_tools_tab(self):
        try:
            self.right_tools_list.clear()
            # 模式：available = 扫描；mounted = 当前 Agent
            mode = getattr(self, "_agent_tools_mode", "mounted")
            items = []
            if mode == "mounted":
                if hasattr(self, "agent_data") and isinstance(self.agent_data, dict):
                    items = self.agent_data.get("tools", []) or []
            else:
                # 仅文件系统扫描（tools/python）
                try:
                    base_dir = Path(__file__).parent.parent.parent
                    tools_dir = base_dir / 'tools' / 'python'
                    if tools_dir.exists() and tools_dir.is_dir():
                        for ns_dir in sorted([p for p in tools_dir.iterdir() if p.is_dir()]):
                            subs = []
                            try:
                                subs = [p.stem for p in ns_dir.glob('*.py') if p.is_file() and p.stem != '__init__']
                            except Exception:
                                subs = []
                            if not subs:
                                # 仅命名空间
                                items.append({"id": ns_dir.name})
                            else:
                                for sub in subs:
                                    tid = f"{ns_dir.name}.{sub}" if sub else ns_dir.name
                                    items.append({"id": tid})
                except Exception as e:
                    self.logger.warning(f"扫描工具目录失败: {e}")
            for it in items:
                tid = it.get("id") or it.get("name") or str(it)
                label = tid
                # 标注挂载状态
                mounted = self._is_tool_mounted(tid)
                state = "已挂载" if mounted else "未挂载"
                display = f"{label}  [{state}]"
                self.right_tools_list.addItem(display)
        except Exception as e:
            self.logger.warning(f"刷新工具清单失败: {e}")

    def _is_tool_mounted(self, tool_id: str) -> bool:
        try:
            if hasattr(self, "agent_data") and isinstance(self.agent_data, dict):
                for t in self.agent_data.get("tools", []) or []:
                    tid = t.get("id") or t.get("name")
                    if tid == tool_id:
                        return True
        except Exception:
            pass
        return False

    def _on_right_tool_selected(self):
        item = self.right_tools_list.currentItem()
        if not item:
            return
        text = item.text()
        self.right_tool_detail.setPlainText(text)

    def _toggle_tool_mount(self):
        from PySide6.QtWidgets import QFileDialog
        item = self.right_tools_list.currentItem()
        if not item:
            ErrorHandler.handle_warning(self, "提示", "请先选择一个工具")
            return
        label = item.text()
        tool_id = label.split("  [")[0]
        try:
            if not hasattr(self, "agent_data"):
                self.agent_data = {}
            tools = self.agent_data.get("tools", []) or []
            if self._is_tool_mounted(tool_id):
                # 卸载
                tools = [t for t in tools if (t.get("id") or t.get("name")) != tool_id]
                self.agent_data["tools"] = tools
                ErrorHandler.handle_success(self, "成功", f"已取消挂载：{tool_id}")
            else:
                # 需要一个配置，若没有则引导导入
                cfg = {"id": tool_id, "type": "python"}
                tools.append(cfg)
                self.agent_data["tools"] = tools
                ErrorHandler.handle_success(self, "成功", f"已挂载：{tool_id}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "挂载切换失败", e)
        finally:
            self._refresh_right_tools_tab()

    def _add_tool_from_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择工具配置 JSON", os.getcwd(), "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 简单加入到 mounted 清单
            if not hasattr(self, "agent_data"):
                self.agent_data = {}
            tools = self.agent_data.get("tools", []) or []
            tools.append(data)
            self.agent_data["tools"] = tools
            ErrorHandler.handle_success(self, "成功", "工具已添加到清单并可挂载")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "添加工具失败", e)
        finally:
            self._refresh_right_tools_tab()

    def _remove_selected_tool(self):
        item = self.right_tools_list.currentItem()
        if not item:
            ErrorHandler.handle_warning(self, "提示", "请选择要移除的工具")
            return
        tool_id = item.text().split("  [")[0]
        try:
            if hasattr(self, "agent_data") and isinstance(self.agent_data, dict):
                tools = self.agent_data.get("tools", []) or []
                tools = [t for t in tools if (t.get("id") or t.get("name")) != tool_id]
                self.agent_data["tools"] = tools
            ErrorHandler.handle_success(self, "成功", f"已从清单移除：{tool_id}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "移除工具失败", e)
        finally:
            try:
                self._refresh_right_tools_tab()
            except Exception:
                pass

    def _on_right_vs_selected(self):
        item = self.right_vs_list.currentItem()
        if not item:
            return
        self.right_vs_detail.setPlainText(item.text())

    def _add_vs_from_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择向量库配置 JSON", os.getcwd(), "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._custom_vectorstores.append(data)
            ErrorHandler.handle_success(self, "成功", "向量库已添加到清单")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "添加向量库失败", e)
        finally:
            self._refresh_right_vectorstores_tab()

    def _remove_selected_vs(self):
        item = self.right_vs_list.currentItem()
        if not item:
            ErrorHandler.handle_warning(self, "提示", "请选择要移除的向量库")
            return
        name = item.text().split("  (")[0]
        try:
            self._custom_vectorstores = [x for x in (self._custom_vectorstores or []) if (x.get("name") or x.get("id")) != name]
            ErrorHandler.handle_success(self, "成功", f"已从清单移除：{name}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "移除向量库失败", e)
        finally:
            self._refresh_right_vectorstores_tab()

    def _refresh_right_vectorstores_tab(self):
        """刷新右下角记忆区：只展示 memory 的名称列表，严格只读。
        名称优先级：name > id > vectorstore > provider > class；均无时显示 "(unnamed)"。
        """
        try:
            if not hasattr(self, 'right_vs_list') or self.right_vs_list is None:
                return
            self.right_vs_list.clear()
            data = getattr(self, 'agent_data', None) or {}
            mem = data.get('memory')
            items = []

            def _label_from_dict(d: dict) -> str:
                try:
                    v = d.get('name') or d.get('id') or d.get('vectorstore') or d.get('provider') or d.get('class')
                    if v:
                        return str(v)
                    # 无名称字段时，用前两个键做简要摘要
                    keys = list(d.keys())
                    if keys:
                        k = keys[0]
                        return f"{k}:{d.get(k)}"
                except Exception:
                    pass
                return "(unnamed)"

            # 1) memory 为列表
            if isinstance(mem, list):
                items = mem
            # 2) memory 为字典
            elif isinstance(mem, dict):
                # 若包含 vectorstores/stores/memories 等列表字段，优先展示其内部项
                for key in ('vectorstores', 'stores', 'memories', 'list', 'items'):
                    lst = mem.get(key)
                    if isinstance(lst, list) and lst:
                        items = lst
                        break
                # 否则将整个 dict 作为一个条目摘要展示
                if not items:
                    items = [mem]
            # 3) 其他标量（字符串等）
            elif mem is not None:
                items = [mem]

            # 合并自定义挂载（若存在）
            try:
                if hasattr(self, '_custom_vectorstores') and isinstance(self._custom_vectorstores, list):
                    items = list(items) + list(self._custom_vectorstores)
            except Exception:
                pass

            for it in items:
                label = "(unnamed)"
                try:
                    if isinstance(it, dict):
                        label = _label_from_dict(it)
                    else:
                        label = str(it)
                except Exception:
                    label = "(unnamed)"
                self.right_vs_list.addItem(label)
        except Exception as e:
            try:
                self.logger.warning(f"刷新记忆名称列表失败: {e}")
            except Exception:
                pass

    # MCP Tab
    def _refresh_right_mcp_tab(self):
        try:
            self.right_mcp_list.clear()
            servers = []
            # 优先从数据库读取
            try:
                if getattr(self, 'config_service', None):
                    servers = list(self.config_service.list_mcp() or [])
            except Exception as e:
                self.logger.warning(f"从DB读取MCP失败: {e}")
                servers = []
            # 回退：原 repositories.mcp_repo（若存在）
            if not servers:
                try:
                    from repositories.mcp_repo import MCPRepository
                    repo = MCPRepository()
                    reg = repo.get_servers()
                    servers = reg.get("servers", [])
                except Exception as e:
                    self.logger.warning(f"读取MCP失败: {e}")
                    servers = []
            for s in servers:
                name = s.get("name", "unnamed")
                typ = s.get("type", "proc")
                self.right_mcp_list.addItem(f"{name}  ({typ})")
        except Exception as e:
            self.logger.warning(f"刷新MCP清单失败: {e}")

    def _on_right_mcp_selected(self):
        item = self.right_mcp_list.currentItem()
        if not item:
            return
        self.right_mcp_detail.setPlainText(item.text())

    # ==== Agent 右侧：参与者（导入器）====
    def _ensure_agent_import_cache(self):
        try:
            if not hasattr(self, '_agent_import_cache') or not isinstance(self._agent_import_cache, dict):
                self._agent_import_cache = {}
        except Exception:
            self._agent_import_cache = {}

    def _agent_import_add(self):
        """通过文件对话框导入一个或多个 JSON 配置文件，加入列表并缓存解析内容。"""
        from PySide6.QtWidgets import QFileDialog
        try:
            self._ensure_agent_import_cache()
            paths, _ = QFileDialog.getOpenFileNames(self, "选择配置 JSON（可多选）", os.getcwd(), "JSON Files (*.json)")
            if not paths:
                return
            for p in paths:
                self._agent_import_add_path(p)
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "导入失败", e)

    def _agent_import_add_path(self, path: str):
        """将单个路径加入导入列表并解析缓存。重复路径将跳过。"""
        try:
            if not path or not os.path.isfile(path):
                return
            self._ensure_agent_import_cache()
            # 去重
            if path in self._agent_import_cache:
                return
            # 解析 JSON
            data = None
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                # 解析失败时仍允许以占位项加入，但标注错误
                data = {"_error": str(e)}
            self._agent_import_cache[path] = data

            # 列表项
            name = os.path.basename(path)
            item = QListWidgetItem(name)
            try:
                # 保存路径到 UserRole
                item.setData(Qt.ItemDataRole.UserRole, path)
            except Exception:
                pass
            if hasattr(self, 'agent_import_list') and self.agent_import_list is not None:
                self.agent_import_list.addItem(item)
                self._decorate_agent_import_item(item)
        except Exception as e:
            try:
                self.logger.warning(f"添加导入项失败: {e}")
            except Exception:
                pass

    def _decorate_agent_import_item(self, item: 'QListWidgetItem'):
        """为给定条目添加右侧删除按钮的复合小部件。"""
        try:
            if not hasattr(self, 'agent_import_list') or self.agent_import_list is None or item is None:
                return
            # 构造行控件
            row = QWidget()
            hl = QHBoxLayout(row)
            try:
                hl.setContentsMargins(6, 2, 6, 2)
                hl.setSpacing(6)
            except Exception:
                pass
            lbl = QLabel(item.text())
            btn_del = QPushButton("删除")
            try:
                btn_del.setFixedWidth(56)
            except Exception:
                pass
            # 连接信号
            try:
                btn_del.clicked.connect(lambda: self._agent_import_delete(item))
            except Exception:
                pass
            hl.addWidget(lbl)
            hl.addStretch(1)
            hl.addWidget(btn_del)
            self.agent_import_list.setItemWidget(item, row)
        except Exception as e:
            try:
                self.logger.warning(f"装饰导入项失败: {e}")
            except Exception:
                pass

    def _agent_import_delete(self, item: 'QListWidgetItem'):
        """删除指定条目并清理缓存。"""
        try:
            if not hasattr(self, 'agent_import_list') or self.agent_import_list is None or item is None:
                return
            path = None
            try:
                path = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                pass
            row = self.agent_import_list.row(item)
            if row >= 0:
                # 先取出 widget 再移除 item
                try:
                    w = self.agent_import_list.itemWidget(item)
                    if w is not None:
                        self.agent_import_list.removeItemWidget(item)
                        try:
                            w.deleteLater()
                        except Exception:
                            pass
                except Exception:
                    pass
                _ = self.agent_import_list.takeItem(row)
            # 清理缓存
            try:
                if path and hasattr(self, '_agent_import_cache') and path in self._agent_import_cache:
                    self._agent_import_cache.pop(path, None)
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"删除导入项失败: {e}")
            except Exception:
                pass

    def _agent_import_move_selected(self, direction: int):
        """将当前选中的条目上移(-1)/下移(+1)。"""
        try:
            if not hasattr(self, 'agent_import_list') or self.agent_import_list is None:
                return
            current_row = self.agent_import_list.currentRow()
            if current_row < 0:
                return
            count = self.agent_import_list.count()
            if count <= 1:
                return
            new_row = max(0, min(count - 1, current_row + (1 if direction > 0 else -1)))
            if new_row == current_row:
                return
            # 取出 item 与其 widget
            item = self.agent_import_list.item(current_row)
            widget = self.agent_import_list.itemWidget(item)
            # 从当前行移除
            item = self.agent_import_list.takeItem(current_row)
            # 插入新位置
            self.agent_import_list.insertItem(new_row, item)
            if widget is not None:
                self.agent_import_list.setItemWidget(item, widget)
            # 重新选中
            self.agent_import_list.setCurrentRow(new_row)
        except Exception as e:
            try:
                self.logger.warning(f"移动导入项失败: {e}")
            except Exception:
                pass

    def _on_agent_import_item_clicked(self, item: 'QListWidgetItem'):
        """单击导入器列表项：读取对应文件并在右侧配置浏览框中显示其 JSON 内容。"""
        try:
            if item is None:
                return
            # 从条目中取回路径
            path = None
            try:
                path = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                path = None
            if not path or not os.path.isfile(path):
                return
            # 读取并美化 JSON
            content = ''
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
                content = json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                try:
                    # 回退为原始文本
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception:
                    content = ''
            # 写入右侧折叠面板
            try:
                if hasattr(self, 'config_panel') and self.config_panel is not None:
                    self.config_panel.setTitle(f"配置文件预览 - {os.path.basename(path)}")
                    self.config_panel.expand()
            except Exception:
                pass
            if hasattr(self, 'asst_mem_config_preview') and self.asst_mem_config_preview is not None:
                try:
                    self.asst_mem_config_preview.blockSignals(True)
                except Exception:
                    pass
                self.asst_mem_config_preview.setPlainText(content or '')
                try:
                    self.asst_mem_config_preview.blockSignals(False)
                except Exception:
                    pass
                try:
                    self._adjust_config_preview_height()
                except Exception:
                    pass
                # 记录预览来源
                try:
                    self._config_preview_source = 'import'
                except Exception:
                    pass
        except Exception as e:
            try:
                self.logger.warning(f"导入器项预览失败: {e}")
            except Exception:
                pass

    def _add_mcp_from_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择MCP配置 JSON", os.getcwd(), "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            from repositories.mcp_repo import MCPRepository
            repo = MCPRepository()
            reg = repo.get_servers()
            servers = reg.get("servers", [])
            servers.append(data)
            reg["servers"] = servers
            repo.save_servers(reg)
            ErrorHandler.handle_success(self, "成功", "MCP已添加到清单")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "添加MCP失败", e)
        finally:
            self._refresh_right_mcp_tab()

    def _remove_selected_mcp(self):
        item = self.right_mcp_list.currentItem()
        if not item:
            ErrorHandler.handle_warning(self, "提示", "请选择要移除的MCP")
            return
        name = item.text().split("  (")[0]
        try:
            from repositories.mcp_repo import MCPRepository
            repo = MCPRepository()
            reg = repo.get_servers()
            servers = [s for s in reg.get("servers", []) if s.get("name") != name]
            reg["servers"] = servers
            repo.save_servers(reg)
            ErrorHandler.handle_success(self, "成功", f"已从清单移除：{name}")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "移除MCP失败", e)
        finally:
            self._refresh_right_mcp_tab()

    # Agent Detail Tab
    def _adjust_config_preview_height(self):
        """根据内容自动调整配置预览框高度"""
        try:
            if not hasattr(self, 'asst_mem_config_preview') or not hasattr(self, 'config_panel'):
                return
                
            # 获取当前文本内容
            text = self.asst_mem_config_preview.toPlainText()
            if not text.strip():
                # 内容为空，使用最小高度
                self.asst_mem_config_preview.setMinimumHeight(80)
                return
                
            # 计算行数
            line_count = text.count('\n') + 1
            
            # 估算所需高度 (每行约20像素 + 额外边距)
            font_metrics = self.asst_mem_config_preview.fontMetrics()
            line_height = font_metrics.lineSpacing()
            padding = 30  # 上下边距
            
            # 计算最佳高度 (限制在100-600像素之间)
            ideal_height = min(max(line_count * line_height + padding, 100), 600)
            
            # 更新文本框最小高度
            self.asst_mem_config_preview.setMinimumHeight(ideal_height)
            
            # 通知折叠面板更新高度
            self.config_panel._update_heights()
            
            try:
                self.logger.debug(f"[CONFIG_PREVIEW] 已自适应高度: {ideal_height}px (行数: {line_count})")
            except Exception:
                pass
                
        except Exception as e:
            try:
                self.logger.warning(f"[CONFIG_PREVIEW] 自适应高度失败: {str(e)}")
            except Exception:
                pass
    
    def _copy_config_to_clipboard(self):
        """将配置文件内容复制到剪贴板"""
        try:
            # 获取文本内容
            content = self.asst_mem_config_preview.toPlainText()
            if not content.strip():
                ErrorHandler.handle_warning(self, "复制失败", "配置文件内容为空，请先生成内存配置")
                return
                
            # 将内容复制到剪贴板
            from PySide6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(content)
            
            # 提示用户复制成功
            ErrorHandler.handle_success(self, "复制成功", "已将配置文件内容复制到剪贴板")
            
            # 记录日志
            try:
                self.logger.info("[MEMCFG] 用户复制了配置内容到剪贴板")
            except Exception:
                pass
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "复制失败", e)
    
    def _refresh_right_agent_detail_tab(self):
        """根据 self.agent_data 回填中部详情表单与右侧清单（tools/memory/mcp）。"""
        try:
            data = getattr(self, 'agent_data', None) or {}

            # 名称
            try:
                if hasattr(self, 'det_name') and self.det_name is not None:
                    # 优先使用运行期 config.name，其次回退到顶层 name
                    _runtime_cfg = data.get('config') if isinstance(data.get('config'), dict) else None
                    _name_val = None
                    if isinstance(_runtime_cfg, dict) and 'name' in _runtime_cfg and _runtime_cfg.get('name') not in (None, ''):
                        _name_val = _runtime_cfg.get('name')
                    else:
                        _name_val = data.get('name', '')
                    self.det_name.setText(str(_name_val or ''))
            except Exception:
                pass

            # 字段：description/system_message/reflect_on_tool_use/tool_call_summary_format/
            #       model_client_stream/max_tool_iterations/model_context/metadata/structured_message_factory
            try:
                if hasattr(self, 'det_description') and self.det_description is not None:
                    self.det_description.setPlainText(str(data.get('description', '')))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_system_message') and self.det_system_message is not None:
                    self.det_system_message.setPlainText(str(data.get('system_message', '')))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_reflect_on_tool_use') and self.det_reflect_on_tool_use is not None:
                    self.det_reflect_on_tool_use.setChecked(bool(data.get('reflect_on_tool_use', False)))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_tool_call_summary_format') and self.det_tool_call_summary_format is not None:
                    self.det_tool_call_summary_format.setPlainText(str(data.get('tool_call_summary_format', '')))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_model_client_stream') and self.det_model_client_stream is not None:
                    self.det_model_client_stream.setChecked(bool(data.get('model_client_stream', False)))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_max_tool_iterations') and self.det_max_tool_iterations is not None:
                    v = int(data.get('max_tool_iterations', 1) or 1)
                    self.det_max_tool_iterations.setValue(max(1, min(99, v)))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_model_context') and self.det_model_context is not None:
                    self.det_model_context.setText(str(data.get('model_context', '')))
            except Exception:
                pass
            try:
                if hasattr(self, 'det_metadata') and self.det_metadata is not None:
                    import json as _json
                    meta = data.get('metadata', '')
                    if isinstance(meta, (dict, list)):
                        self.det_metadata.setPlainText(_json.dumps(meta, ensure_ascii=False, indent=2))
                    else:
                        self.det_metadata.setPlainText(str(meta or ''))
            except Exception:
                try:
                    if hasattr(self, 'det_metadata') and self.det_metadata is not None:
                        self.det_metadata.setPlainText(str(data.get('metadata', '')))
                except Exception:
                    pass
            try:
                if hasattr(self, 'det_structured_message_factory') and self.det_structured_message_factory is not None:
                    self.det_structured_message_factory.setText(str(data.get('structured_message_factory', '')))
            except Exception:
                pass

            # 模型候选与选择
            try:
                try:
                    self._refresh_det_model_candidates()
                except Exception:
                    pass
                cfg = (data.get('model_client', {}) or {}).get('config', {})
                model = cfg.get('model') or ''
                try:
                    self.det_model.blockSignals(True)
                except Exception:
                    pass
                try:
                    idx = self.det_model.findText(model)
                    if idx != -1:
                        self.det_model.setCurrentIndex(idx)
                    else:
                        self.det_model.setCurrentText(model)
                except Exception:
                    pass
                try:
                    self.det_model.blockSignals(False)
                except Exception:
                    pass
            except Exception:
                pass

            # Tools 回填
            try:
                if hasattr(self, 'det_tools_list') and isinstance(self.det_tools_list, QListWidget):
                    self.det_tools_list.clear()
                    for t in (data.get('tools') or []):
                        if isinstance(t, dict):
                            try:
                                label = t.get('id') or t.get('name') or json.dumps({k: t[k] for k in list(t.keys())[:2]}, ensure_ascii=False)
                            except Exception:
                                label = str(t)
                        else:
                            label = str(t)
                        self.det_tools_list.addItem(label)
            except Exception:
                pass

            # Memory 回填
            try:
                if hasattr(self, 'det_vs_list') and isinstance(self.det_vs_list, QListWidget):
                    self.det_vs_list.clear()
                    mounted_names = []
                    for mem in (data.get('memory') or []):
                        if isinstance(mem, dict):
                            cfg1 = mem.get('config') or {}
                            inner_cfg = cfg1.get('config') or {}
                            cn = inner_cfg.get('collection_name') or cfg1.get('collection_name') or mem.get('name') or mem.get('id')
                            if cn:
                                mounted_names.append(str(cn))
                        else:
                            mounted_names.append(str(mem))
                    for name in mounted_names:
                        self.det_vs_list.addItem(name)
            except Exception:
                pass

            # MCP 回填
            try:
                if hasattr(self, 'det_mcp_list') and isinstance(self.det_mcp_list, QListWidget):
                    self.det_mcp_list.clear()
                    for s in (data.get('mcp') or []):
                        if isinstance(s, dict):
                            label = s.get('name') or s.get('id') or json.dumps({k: s[k] for k in list(s.keys())[:2]}, ensure_ascii=False)
                        else:
                            label = str(s)
                        self.det_mcp_list.addItem(label)
            except Exception:
                pass
        except Exception as e:
            try:
                self.logger.warning(f"加载Agent详情失败: {e}")
            except Exception:
                pass

    def _save_agent_detail_edit(self):
        try:
            # 将表单回写到 agent_data（不写盘，仅内存）
            self._sync_agent_form_to_json()
            # 左侧名称/角色显示联动
            if hasattr(self, 'agent_name_edit'):
                self.agent_name_edit.setText(self.agent_data.get("name", ""))
            if hasattr(self, 'agent_role_edit'):
                self.agent_role_edit.setText(self.agent_data.get("role", ""))
            ErrorHandler.handle_success(self, "成功", "Agent参数已保存到内存（请使用左侧保存导出到文件）")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "保存失败", e)

    
    def on_save_agent_json(self):
        """保存Agent JSON（显式写盘：前端只做参数同步与写文件，不做隐式归一化）"""
        if not hasattr(self, 'agent_data') or not self.agent_data:
            ErrorHandler.handle_warning(self, "提示", "请先导入或生成Agent配置")
            return
        # 方案C：直接保存，不做任何修改（仅保留文件保存对话框与重复覆盖确认）

        from PySide6.QtWidgets import QFileDialog
        # 默认保存目录与文件名：config/agents/<agent_name>.json
        try:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            default_dir = os.path.join(base_dir, 'config', 'agents')
        except Exception:
            default_dir = os.getcwd()
        try:
            os.makedirs(default_dir, exist_ok=True)
        except Exception:
            pass
        agent_name = str((self.agent_data or {}).get('name') or 'agent').strip() or 'agent'
        for ch in '\\/:*?"<>|':
            agent_name = agent_name.replace(ch, '_')
        initial_path = os.path.join(default_dir, f"{agent_name}.json")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存Agent JSON",
            initial_path,
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        # 强制使用 .json 扩展名
        try:
            root, ext = os.path.splitext(path)
            if ext.lower() != '.json':
                path = root + '.json'
        except Exception:
            pass
        # 写盘
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.agent_data, f, ensure_ascii=False, indent=2)
            if hasattr(self, 'agent_path'):
                self.agent_path.setText(path)
            ErrorHandler.handle_success(self, "成功", "Agent配置已保存")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "保存失败", e)
    
    def on_agent_advanced(self):
        """Agent高级参数"""
        if not hasattr(self, 'agent_data') or not self.agent_data:
            ErrorHandler.handle_warning(self, "提示", "请先导入Agent配置")
            return
        
        from app.ui.dialogs.advanced_json_dialog import AdvancedJsonDialog
        dialog = AdvancedJsonDialog(self, "Agent高级参数", self.agent_data)
        if dialog.exec() == dialog.Accepted:
            self.agent_data = dialog.get_data()
    
    def on_save_agent(self):
        """保存Agent配置（别名方法）"""
        self.on_save_agent_json()
    
    def on_export_agent(self):
        """导出Agent配置（别名方法）"""
        self.on_export_agent_json()
    
    def on_generate_team(self):
        """生成Team模板"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "Team模板生成功能待实现")
    
    def on_import_team(self):
        """导入Team配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "Team导入功能待实现")
    
    def on_export_team(self):
        """导出Team配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "Team导出功能待实现")
    
    def on_add_member(self):
        """添加团队成员"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "添加成员功能待实现")
    
    def on_remove_member(self):
        """移除团队成员"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "移除成员功能待实现")
    
    def on_team_debug(self):
        """团队调试"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "团队调试功能待实现")
    
    def on_save_team_json(self):
        """保存Team JSON配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "Team保存功能待实现")
    
    def on_export_team_json(self):
        """导出Team JSON配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "Team导出功能待实现")
    
    def on_team_advanced(self):
        """团队高级参数"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "团队高级参数功能待实现")
    
    def on_browse_team(self):
        """浏览Team文件"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择Team JSON文件", os.getcwd(), "JSON Files (*.json)"
        )
        if path:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", f"已选择文件: {path}")
    
    def on_run_team(self):
        """运行Team"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "Team运行功能待实现")
    
    def on_team_clear(self):
        """清空Team输入与输出"""
        if hasattr(self, 'team_input') and getattr(self, 'team_input', None) is not None:
            self.team_input.clear()
        if hasattr(self, 'team_output') and getattr(self, 'team_output', None) is not None:
            self.team_output.clear()

    def on_refresh_agent_tools(self):
        """刷新Agent工具列表（接入右侧Tabs）"""
        try:
            t = getattr(self, "_agent_tools_type", "tool") or "tool"
            # 根据类型切换Tab并刷新
            if hasattr(self, 'right_tabs'):
                if t == "mcp":
                    # 切到 MCP
                    self.right_tabs.setCurrentIndex(2)
                    self._refresh_right_mcp_tab()
                elif t in ("vector", "vectorstore", "vs"):
                    # 切到 向量库
                    self.right_tabs.setCurrentIndex(1)
                    self._refresh_right_vectorstores_tab()
                else:
                    # 切到 工具
                    self.right_tabs.setCurrentIndex(0)
                    self._refresh_right_tools_tab()
            else:
                # 兼容：右侧Tabs尚未创建时，不做任何输出
                self.logger.info("右侧选项卡未初始化，跳过UI刷新")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "刷新失败", e)

    
    def on_mount_tool(self):
        """挂载工具"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "挂载工具功能待实现")

    def on_clear(self):
        """清空模型页输入与输出框"""
        if hasattr(self, 'input_box') and getattr(self, 'input_box', None) is not None:
            self.input_box.clear()
        if hasattr(self, 'output_box') and getattr(self, 'output_box', None) is not None:
            self.output_box.clear()

    def on_apply_team_basic(self):
        """应用团队基本配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "应用团队基本配置功能待实现")

    def on_apply_agent_basic(self):
        """应用Agent基本配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "应用Agent基本配置功能待实现")

    def on_apply_model_basic(self):
        """应用模型基本配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "应用模型基本配置功能待实现")

    def on_export_model(self):
        """导出模型配置"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "导出模型配置功能待实现")

    def on_refresh_models(self):
        """刷新模型列表"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "刷新模型列表功能待实现")

    def on_test_model(self):
        """测试模型连接"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "测试模型连接功能待实现")

    def on_refresh_warehouse(self):
        """刷新仓库"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "刷新仓库功能待实现")

    def on_member_add(self):
        """添加团队成员"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "添加团队成员功能待实现")

    def on_member_remove(self):
        """移除团队成员"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "移除团队成员功能待实现")

    def on_member_edit(self):
        """编辑团队成员"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "编辑团队成员功能待实现")

    def on_member_up(self):
        """成员上移"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "成员上移功能待实现")

    def on_member_down(self):
        """成员下移"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "成员下移功能待实现")
    
    def on_member_apply(self):
        """应用成员变更"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "提示", "应用成员变更功能待实现")

    def closeEvent(self, event):
        """窗口关闭时清理工作线程与资源"""
        try:
            self._log_thread_states("closeEvent:enter")
        except Exception:
            pass
        try:
            if getattr(self, "_agent_thread", None):
                try:
                    self._agent_thread.quit()
                    self._agent_thread.wait(2000)
                except Exception:
                    pass
        finally:
            self._agent_thread = None
            self._agent_worker = None
        try:
            if getattr(self, "_script_thread", None):
                try:
                    self._script_thread.quit()
                    self._script_thread.wait(2000)
                except Exception:
                    pass
        finally:
            self._script_thread = None
            self._script_worker = None
        try:
            super().closeEvent(event)
        except Exception:
            pass
        try:
            self._log_thread_states("closeEvent:exit")
        except Exception:
            pass
    
    # Agent相关方法
    def on_browse_agent(self):
        """浏览Agent文件"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "选择Agent JSON文件", os.getcwd(), "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            # 1) 加载到内存并更新路径框
            self.agent_data = self.agent_service.load_agent_from_file(path)
            try:
                if hasattr(self, 'agent_path') and self.agent_path is not None:
                    self.agent_path.setText(path)
            except Exception:
                pass

            # 2) 将原始 JSON 写入右侧“配置文件预览”抽屉
            try:
                if hasattr(self, 'asst_mem_config_preview') and hasattr(self, 'config_panel'):
                    with open(path, 'r', encoding='utf-8') as f:
                        raw_txt = f.read()
                    try:
                        self.config_panel.setTitle(f"配置文件预览 - {os.path.basename(path)}")
                        self.config_panel.expand()
                    except Exception:
                        pass
                    try:
                        self.asst_mem_config_preview.blockSignals(True)
                    except Exception:
                        pass
                    self.asst_mem_config_preview.setPlainText(raw_txt)
                    try:
                        self.asst_mem_config_preview.blockSignals(False)
                    except Exception:
                        pass
                    try:
                        self._adjust_config_preview_height()
                    except Exception:
                        pass
            except Exception:
                pass

            # 3) 回填右侧详情表单（使用现有刷新函数）
            try:
                if hasattr(self, '_refresh_right_agent_detail_tab'):
                    self._refresh_right_agent_detail_tab()
            except Exception as _e:
                try:
                    self.logger.warning(f"回填右侧详情表单失败: {_e}")
                except Exception:
                    pass

            # 4) 同步右侧导入器清单（如存在）
            try:
                if hasattr(self, 'agent_import_list') and self.agent_import_list is not None:
                    self.agent_import_list.clear()
                    data = self.agent_data or {}
                    # 工具
                    try:
                        for t in (data.get('tools') or []):
                            label = ''
                            if isinstance(t, dict):
                                label = str(t.get('id') or t.get('name') or t.get('tool') or 'unnamed')
                            else:
                                label = str(t)
                            self.agent_import_list.addItem(f"[工具] {label}")
                    except Exception:
                        pass
                    # MCP
                    try:
                        for m in (data.get('workbench') or []):
                            if isinstance(m, dict) and (m.get('provider') or '').lower().find('mcp') >= 0:
                                name = str(m.get('label') or m.get('provider') or 'MCP')
                                self.agent_import_list.addItem(f"[MCP] {name}")
                    except Exception:
                        pass
                    # 模型（model_client）
                    try:
                        mc = (data.get('model_client') or {}) if isinstance(data.get('model_client'), dict) else {}
                        if mc:
                            label = str(mc.get('label') or mc.get('provider') or 'Model')
                            self.agent_import_list.addItem(f"[模型] {label}")
                    except Exception:
                        pass
                    # 向量库（memory）
                    try:
                        mem = self.agent_data.get('memory')
                        mem_items = mem if isinstance(mem, list) else ([mem] if mem else [])
                        for it in mem_items:
                            name = 'unnamed'
                            if isinstance(it, dict):
                                name = str(it.get('label') or it.get('name') or it.get('provider') or it.get('class') or 'unnamed')
                            else:
                                name = str(it)
                            self.agent_import_list.addItem(f"[向量库] {name}")
                    except Exception:
                        pass
            except Exception:
                pass

            # 5) 将 Agent 的模型配置映射到模型页（可选，失败不影响导入流程）
            try:
                if hasattr(self, '_agent_to_model_data'):
                    self.model_data = self._agent_to_model_data(self.agent_data)
                if hasattr(self, '_apply_capability_preset_if_any'):
                    self._apply_capability_preset_if_any()
                if hasattr(self, '_refresh_model_right_panel'):
                    self._refresh_model_right_panel()
            except Exception as map_e:
                try:
                    self.logger.warning(f"回填模型右栏失败: {map_e}")
                except Exception:
                    pass

            ErrorHandler.handle_success(self, "成功", "Agent配置已导入")
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "导入失败", e)
    
    def on_run_agent(self):
        """内部运行机制已封存，统一使用脚本运行。"""
        ErrorHandler.handle_info(self, "提示", "内部运行机制已封存，请使用“运行（脚本）”。")

    def _finalize_agent_thread(self):
        """清理Agent推理线程与临时资源"""
        try:
            self._log_thread_states("_finalize_agent_thread:enter")
        except Exception:
            pass
        try:
            # 关闭内存资源（如后端支持）
            if self.agent_backend and hasattr(self.agent_backend, "_close_memories_if_needed"):
                memories = getattr(self.agent_backend, "_memory_objects", []) or []
                try:
                    self.agent_backend._close_memories_if_needed(memories)
                except Exception as e:
                    self.logger.warning(f"清理内存资源失败: {e}")
        finally:
            try:
                if self._agent_thread:
                    self._agent_thread.quit()
                    self._agent_thread.wait(3000)
            except Exception:
                pass
            self._agent_worker = None
            self._agent_thread = None
        try:
            self._log_thread_states("_finalize_agent_thread:exit")
        except Exception:
            pass
    
    def _on_agent_finished(self, resp: str):
        try:
            # 获取用户输入内容
            user_text = self.agent_chat_input.toPlainText().strip()
            
            # 将用户输入写入输出框
            self.agent_chat_output.append(f"User: {user_text}\n")
            
            # 将回复写入输出框
            self.agent_chat_output.append(f"Agent: {resp}")
            
            # 添加MD分隔符
            self.agent_chat_output.append("\n---\n")
            
            # 清空输入框
            self.agent_chat_input.clear()
        except Exception as e:
            self.logger.warning(f"写入Agent输出失败: {e}")

    def _on_agent_failed(self, friendly_error: str):
        ErrorHandler.handle_warning(self, "推理失败", friendly_error)

    def on_run_agent_script(self):
        """脚本模式运行Agent（使用 ScriptInferWorker）"""
        if not hasattr(self, 'agent_data') or not self.agent_data:
            ErrorHandler.handle_warning(self, "提示", "请先导入Agent配置")
            return
        prompt = self.agent_input_box.toPlainText().strip()
        if not prompt:
            ErrorHandler.handle_warning(self, "提示", "请输入内容")
            return
        try:
            # 运行前预检（与普通运行一致）
            ok, msg = self.agent_service.preflight_check(self.agent_data)
            if not ok:
                ErrorHandler.handle_warning(self, "运行前检查未通过", msg)
                return

            # 获取配置来源并根据来源选择配置路径
            src = getattr(self, '_exec_config_source', 'local')
            cfg_path = ''

            # 根据配置来源选择合适的配置文件路径
            if src == 'memory':
                mem_path = getattr(self, '_mem_agent_config_path', '')
                if mem_path and os.path.exists(mem_path):
                    cfg_path = mem_path
                else:
                    # 内存配置不存在，重置来源为本地
                    self._exec_config_source = 'local'
                    src = 'local'
                    print(f"[DEBUG] 内存配置不存在，已切换来源为local")
            
            # 如果来源是local或内存配置不存在
            if src == 'local' or not cfg_path:
                # 获取本地配置路径
                cfg_path = self.agent_path.text().strip() if hasattr(self, 'agent_path') else ''
                
            if not cfg_path or not os.path.exists(cfg_path):
                ErrorHandler.handle_warning(self, "提示", "未找到可用的Agent配置路径，请先保存或选择JSON文件")
                return
                
            # 输出诊断日志
            try:
                self.logger.info(f"[SCRIPT_RUN] 使用{src}配置: {cfg_path}")
                print(f"[SCRIPT_RUN] 使用{src}配置来源: {cfg_path}")
                # 在界面上显示配置来源信息
                if hasattr(self, 'agent_chat_output') and self.agent_chat_output is not None:
                    self.agent_chat_output.append(f"[信息] 使用{src}配置: {os.path.basename(cfg_path)}")
            except Exception as e:
                print(f"[ERROR] 输出配置信息失败: {e}")

            # 并发保护
            if self._script_thread and self._script_thread.isRunning():
                ErrorHandler.handle_info(self, "提示", "脚本运行进行中，请稍候…")
                return

            # 多轮：先记录用户消息并清空输入
            try:
                if hasattr(self, 'agent_chat_output') and self.agent_chat_output is not None:
                    self.agent_chat_output.append(f"User: {prompt}")
                    self.agent_chat_output.append("---")
                self.agent_input_box.clear()
            except Exception:
                pass

            # 传递 memory_write_policy（与内部运行保持一致）
            policy = None
            try:
                policy = (self.agent_data or {}).get("memory_write_policy")
            except Exception:
                policy = None

            # 启动脚本线程
            self._script_thread = QThread(self)
            self._script_worker = ScriptInferWorker(cfg_path, prompt, memory_policy=policy, verbose=False, timeout=300)
            self._script_worker.moveToThread(self._script_thread)
            self._script_thread.started.connect(self._script_worker.run)
            self._script_worker.finished.connect(self._on_script_finished)
            self._script_worker.failed.connect(self._on_script_failed)
            self._script_worker.finished.connect(self._finalize_script_thread)
            self._script_worker.failed.connect(self._finalize_script_thread)
            try:
                # 仅诊断：线程启动前后状态
                self._log_thread_states("on_run_agent_script:before_start")
                self._script_thread.finished.connect(lambda: self._log_thread_states("script_thread:finished"))
            except Exception:
                pass
            self._script_thread.start()
            try:
                self._log_thread_states("on_run_agent_script:after_start")
            except Exception:
                pass
        except Exception as e:
            ErrorHandler.handle_ui_error(self, "脚本运行失败", e)

    def _on_script_finished(self, output: str):
        try:
            if hasattr(self, 'agent_chat_output') and self.agent_chat_output is not None:
                self.agent_chat_output.append(f"[Script] Agent: {output}")
                self.agent_chat_output.append("---")
        except Exception as e:
            self.logger.warning(f"写入脚本输出失败: {e}")
        try:
            self._log_thread_states("_on_script_finished")
        except Exception:
            pass

    def _on_script_failed(self, friendly_error: str):
        ErrorHandler.handle_warning(self, "脚本运行失败", friendly_error)

    def _finalize_script_thread(self):
        try:
            self._log_thread_states("_finalize_script_thread:enter")
        except Exception:
            pass
        try:
            if self._script_thread:
                self._script_thread.quit()
                self._script_thread.wait(3000)
        except Exception:
            pass
        self._script_worker = None
        self._script_thread = None
        try:
            self._log_thread_states("_finalize_script_thread:exit")
        except Exception:
            pass

    # 工具方法
    def _append_history(self, prompt: str, reply: str):
        """添加历史记录"""
        try:
            import json
            from datetime import datetime
            
            history_file = Paths.get_absolute_path(Paths.LOGS_DIR) / "history.jsonl"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            
            entry = {
                "ts": datetime.now().isoformat(),
                "model": self.model_data.get("name", "") if self.model_data else "",
                "prompt": prompt,
                "reply": reply
            }
            
            with history_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                
        except Exception as e:
            self.logger.warning(f"写入历史记录失败: {e}")

    def _debug_log_model_env(self):
        """打印当前模型配置与关键环境变量快照（掩码显示），便于在终端排错。"""
        try:
            import os
            data = getattr(self, 'model_data', {}) or {}
            cfg = dict(data.get('config') or {})
            name = str(data.get('name') or '')
            provider = str(data.get('provider') or '')
            base_url = str(cfg.get('base_url') or data.get('base_url') or '')
            model = str(cfg.get('model') or '')
            api_key_env = str(cfg.get('api_key_env') or '')
            # 精简输出：仅打印三项（model/base_url/环境变量是否存在）
            present = bool(api_key_env and os.environ.get(api_key_env))
            masked = ((os.environ.get(api_key_env) or '')[:4] + '...') if present else '未设置'
            simple = f"Model={model or name} | BaseURL={base_url or '-'} | Env {api_key_env}={masked}"
            try:
                print(simple)
            except Exception:
                pass
            try:
                self.logger.info(simple)
            except Exception:
                pass
        except Exception as _e:
            try:
                self.logger.warning(f"_debug_log_model_env 失败: {_e}")
            except Exception:
                pass
