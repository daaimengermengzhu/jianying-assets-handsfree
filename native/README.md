# 剪映原生后台接入

Windows 本机工具，通过已安装的剪映专业版组件读写加密草稿，通过已登录客户端查询官方素材、生成短配音，并对已保存草稿进行批量编辑。提供 Python CLI 和 17 个 stdio MCP 工具，不接管鼠标键盘，不打包剪映二进制。

这是针对 **11.5.0.14471** 验证的非官方接口。**不能后台导出 MP4**；使用者需要在剪映中打开、检查并导出草稿。其他版本的兼容性未验证。

## 安装与前提

- Windows，已安装并登录剪映专业版 11.5.0.14471。在线素材、配音、素材抽帧和波形需要客户端保持运行；会员资源需要当前账号具有对应权益。
- Python **3.11 或更新版本**：代码使用 `hashlib.file_digest`。MCP SDK 自身要求 Python ≥3.10，但不足以满足本项目全部功能。
- 不需要单独安装 Node.js：Python 启动剪映安装目录自带的 `bun.exe` 执行 `.cjs`，并加载 `videoeditor_addon.node`；素材模型也来自该安装包。
- 追加官方视频需要已有 `ffprobe.exe`，本项目不附带。其余 CLI 功能只使用 Python 标准库；MCP 需要安装锁定的 `mcp==2.2.0`。

以下命令在 `<repo>/native` 执行，`<repo>` 代表仓库绝对路径；所有尖括号占位符都应替换。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python cli.py doctor
python cli.py host-status
python cli.py inspect '<草稿目录>'
python cli.py make-portrait --source '<草稿目录>' --output '<不存在的新目录>' --image '<图片路径>'
```

`doctor` 检查原生组件，不代表线上权益、渲染或导出可用。草稿操作生成新目录，既有输出拒绝覆盖；不要直接改写正在剪映中打开的项目。输出没有通用 GUI 项目列表登记功能，保留草稿和引用资源的原位置。

## 环境变量

| 变量 | 实际用途与默认值 |
| --- | --- |
| `JY_INSTALL_DIR` | CLI/MCP 原生组件目录；默认 `C:/Program Files/JianyingPro/Apps/11.5.0.14471`。CLI 可在子命令前用 `--install` 覆盖 |
| `JY_OUTPUT_ROOT` | 仅 MCP 输出根目录，默认 `<repo>/native/output`；CLI 使用各命令的 `--output` 或 `--output-root` |
| `JY_FFPROBE` | 追加官方视频时用的 ffprobe；不设时从 `PATH` 查找。CLI 对应 `--ffprobe` |
| `PYTHONUTF8` | Python 解释器标准变量，可设 `1`，也可用 `python -X utf8` |

程序还继承系统 `PATH`，原生子进程会将安装目录加入其中。宿主桥接使用 Python `tempfile.gettempdir()` 定位客户端发现文件，不需要手填端口或 token；没有额外的项目账号环境变量。

## CLI 命令

公共形式：`python cli.py [--install '<安装目录>'] <命令> ...`。以下列出全部 17 个子命令；完整帮助使用 `<命令> --help`。时间参数单位为毫秒。

| 命令 | 作用及关键参数 |
| --- | --- |
| `doctor` | 初始化原生组件并报告能力边界 |
| `host-status` | 查询宿主健康状态、会员和积分；不生成内容 |
| `voice-categories` | 查询音色分类 |
| `search-voices` | `keyword [--limit 5]`，最多 20 条公开音色 |
| `material-categories` | `kind`：filter、sticker、text-template |
| `list-materials` | `category_id [--limit 5] [--offset 0]`，分类素材和权益 |
| `search-materials` | `kind keyword [--limit 5] [--offset 0]`，九类检索，见下文 |
| `synthesize` | `text [--voice 解说小帅] [--output-root <目录>]`；默认 native/output/audio，另支持真人播客男，1–120 字 |
| `inspect` | `draft`，读取草稿摘要和主媒体缺失情况 |
| `make-portrait` | `--source --output [--image] [--ratio 9:16]`；画幅可选 9:16、16:9、1:1、4:3、3:4 |
| `add-catalog-asset` | `--source --output --kind --resource-id [--resource-source 1] [--start-ms 0] [--duration-ms 2000] [--segment-id]`；获取并写入 effect、sound、music、transition |
| `replace-caption` | `--source --output --segment-id --text`；替换 1–200 字单一完整样式字幕，保留配音 |
| `apply-cached-asset` | `--source --output --kind --asset-manifest [--segment-id] [--start-ms 0] [--duration-ms 2000] [--font-manifest] [--source-start-ms 0] [--ffprobe]`；应用 sticker、subtitle-template、stock-video |
| `timeline` | `source [--offset 0] [--limit 30]`；分页返回片段 ID、布局、音量及依赖检查，limit 1–100 |
| `edit-batch` | `--source --output --operations-file [--ffprobe]`；UTF-8 JSON 数组，文件至多 1 MB，1–100 项操作 |
| `extract-frame` | `media [--timestamp-ms 0] [--width 320] [--height 180] [--output-root <目录>]`；默认 native/output/frames，读取源视频单帧 |
| `audio-waveform` | `media [--start-ms 0] [--duration-ms 5000] [--max-points 128]`；读取现有媒体波形 |

搜索 kind：`effect`、`transition`、`subtitle-template`、`material`（视频/图片素材）、`sound`、`music`、`sticker`、`text-template`、`recipe`（素材组合）。搜索成功不代表已下载、可应用或已验证渲染。

`resource_source` 应使用搜索结果的 source；音乐常为 3。转场需要同轨有后续相邻画面的 segment_id，时长不得超过较短画面的一半。

缓存素材清单是 `asset_resources.retrieve_asset` 生成的 `verification.json`。当前没有独立的通用下载 CLI/MCP；不要把搜索结果 JSON 当清单。字幕模板还需要目标字幕和匹配字体清单。视频仅追加到草稿末尾，时长至多 30 秒。批量参数见 [协议说明](docs/NATIVE_PROTOCOL.md#批量编辑)。

## MCP 工具

`mcp_server.py` 使用 stdio，由客户端按需启动，不监听网络端口。`output_name` 只能是一个新文件夹名，输出限定在 `JY_OUTPUT_ROOT` 下。下表参数使用代码名称；可选参数默认值与上述 CLI 对应。

| 工具名 | 作用、关键参数 |
| --- | --- |
| `jianying_native_status` | 原生初始化及能力检查，无参数 |
| `jianying_host_status` | 宿主、会员和积分查询，无参数 |
| `jianying_voice_categories` | 音色分类，无参数 |
| `jianying_search_voices` | 公开音色：keyword、limit=5 |
| `jianying_material_categories` | 素材分类：kind |
| `jianying_list_materials` | 分类条目：category_id、limit=5、offset=0 |
| `jianying_search_materials` | 九类检索：kind、keyword、limit=5、offset=0 |
| `jianying_synthesize` | 短配音：text、voice_name='解说小帅'，另支持真人播客男 |
| `jianying_inspect_draft` | 草稿摘要：draft_path |
| `jianying_make_portrait` | 新画幅/图片草稿：source_draft、output_name、image_path=''、ratio='9:16' |
| `jianying_add_catalog_asset` | 获取并添加四类素材：source_draft、output_name、kind、resource_id、resource_source=1、start_ms=0、duration_ms=2000、segment_id='' |
| `jianying_replace_caption` | 普通字幕改字：source_draft、output_name、segment_id、text |
| `jianying_apply_cached_asset` | 三类缓存素材：source_draft、output_name、kind、asset_manifest、segment_id=''、start_ms=0、duration_ms=2000、font_manifest=''、source_start_ms=0 |
| `jianying_timeline` | 时间线分页：source_draft、offset=0、limit=30 |
| `jianying_edit_batch` | 批量修改：source_draft、output_name、operations |
| `jianying_extract_video_frame` | 源视频 PNG：media_path、timestamp_ms=0、width=320、height=180 |
| `jianying_audio_waveform` | 完整波形：media_path、start_ms=0、duration_ms=5000、max_points=128 |

配音会创建真实线上任务，素材写入会获取资源；不自动重复创建配音任务。余额观察不能证明单次价格或无限使用，搜索到会员音色也不等于已获生成权限。配音和在线素材工具应允许至少 120 秒调用等待。

### Claude Code

在项目 `.mcp.json` 合并以下配置（不要覆盖已有服务器），替换绝对路径；Windows 路径可使用 `/`。重新打开项目后在 `/mcp` 检查状态并按客户端提示启用。配置格式见 [Claude Code MCP 文档](https://code.claude.com/docs/en/mcp)。

```json
{
  "mcpServers": {
    "jianying-native": {
      "type": "stdio",
      "command": "<repo>/native/.venv/Scripts/python.exe",
      "args": ["-X", "utf8", "<repo>/native/mcp_server.py"],
      "env": {
        "JY_INSTALL_DIR": "<剪映安装目录>",
        "JY_OUTPUT_ROOT": "<草稿输出根目录>",
        "JY_FFPROBE": "<ffprobe绝对路径>"
      }
    }
  }
}
```

### Codex

在用户 `~/.codex/config.toml` 合并以下配置，重新启动会话后用 `codex mcp get jianying-native` 检查。配置格式见 [Codex MCP 文档](https://developers.openai.com/codex/mcp/)。

```toml
[mcp_servers.jianying-native]
command = "<repo>/native/.venv/Scripts/python.exe"
args = ["-X", "utf8", "<repo>/native/mcp_server.py"]
tool_timeout_sec = 120

[mcp_servers.jianying-native.env]
JY_INSTALL_DIR = "<剪映安装目录>"
JY_OUTPUT_ROOT = "<草稿输出根目录>"
JY_FFPROBE = "<ffprobe绝对路径>"
```

## 已验证与边界

历史实测包括加密草稿完整读写、图片/画幅修改、短配音、九类素材搜索、四类在线素材写入、三类缓存素材应用，以及“剪映保存 → 后台编辑 → 客户端继续编辑 → 后台再次编辑”。批量编辑五轮平均 1.403 秒，仅为短草稿及已缓存资源，不含下载、配音、预览和导出。详见 [验证记录](docs/VALIDATION.md)。

未接通或未完整验证：后台时间线预览/MP4 导出、通用 GUI 草稿登记、前台项目热修改、文字模板（不同于字幕模板）、识别字幕、花字、智能包装、完整模板、调节/LUT、数字人和其他 AI 成片流程。滤镜仅有资源绑定实测，未验证画面。长草稿、持续压力和跨版本兼容未验证。

输出通常依赖绝对资源路径，不是可任意搬移的自包含工程。批量、改字和缓存素材工具有临时写入、完整读回及最终目录改名保护；旧 make-portrait/add-catalog-asset 失败可能留下工作目录，没有成功校验不能当成成稿。

## 测试

```powershell
python -X utf8 -m unittest discover -p "test_*.py" -v
```

单元测试不需要启动剪映。真实剪映上的端到端验证需要你自己的测试草稿，记录见 [验证记录](docs/VALIDATION.md)。

技术字段与失败码见 [NATIVE_PROTOCOL.md](docs/NATIVE_PROTOCOL.md)。本仓库不提供剪映安装包、用户素材、账号凭据或私人实验附件。
