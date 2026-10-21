# jianying-assets-handsfree

**剪映官方素材库 + 剪映配音，交给 AI 在后台调用，全程不接管你的电脑。**

让 AI 助手（Claude Code、Codex 等支持 MCP 或 skill 的工具）在 Windows 本机后台操作**剪映专业版**：搜索并使用剪映官方素材、调用剪映自带配音（含会员音色）、修改已加密的草稿，再无头导出成 MP4。不截屏、不模拟鼠标键盘、不需要把剪映窗口切到前台，你可以照常用电脑（配音和在线素材要求剪映在后台开着并已登录）。

> 社区项目，与字节跳动和剪映官方无关。它调用的是你本机已安装的剪映自带组件，不分发剪映的任何程序或文件。只在剪映专业版 **11.5.0.14471（Windows）** 上验证过。

## 能做什么

| 能力 | 谁实现的 | 状态 |
|---|---|---|
| 调用**剪映自带配音**，含会员音色（账号本身要有权限） | 本项目 `native`，通过已登录的剪映客户端 | 可用 |
| 搜索、下载并使用**剪映官方素材库**：特效、转场、滤镜、贴纸、音效、背景音乐、字幕模板、官方视频等九类 | 本项目 `native` | 部分可用，见下 |
| 读写剪映 11.5 的**加密草稿**，读取时间线 | 本项目 `native`，直接调用剪映自带原生组件 | 可用 |
| 在加密草稿上批量改字幕、加素材、调位置和音量，输出到新目录，原稿不动 | 本项目 `native` | 可用 |
| 改画幅、加图片、从源视频抽帧、读音频波形 | 本项目 `native` | 可用 |
| 成片响度统一到 −14 LUFS、登记进剪映草稿列表、一条命令从草稿到成片 | 本项目 `jy_pipeline.py` | 可用 |
| 用代码从零生成新草稿：视频、音频、字幕、特效、转场、滤镜、关键帧 | 第三方 pyJianYingDraft | 可用 |
| 不打开剪映界面导出 MP4 | 第三方 jy-draftc，由 `jy_pipeline.py` 调用 | 可用 |
| 后台渲染草稿预览帧 | — | 未接通 |
| 文字模板、智能包装、数字人、自动字幕识别、花字、LUT | — | 未接通 |

各项的实测数据和已知边界见 [native/docs/VALIDATION.md](native/docs/VALIDATION.md)。

## 和其他开源项目的区别

据我们 2026 年 10 月对 18 个同类开源项目的核查，本项目是**首个**把剪映自带配音（含会员音色）和官方在线素材库开放给 AI 调用的开源工具：AI 可以按关键词搜索官方素材，下载后直接写进已加密的剪映草稿，再接上无头导出和响度处理，从配音、选素材到出成片串成一条流程。

其他项目大多停在"生成草稿"这一步：素材只能用本地文件，或者用写死的素材 ID 表；配音靠第三方 TTS、导入现成音频，或直接调用字节的语音接口，但没有确认能用剪映会员音色。也有项目能读写加密草稿、无头导出，本项目的加密草稿读写是自己实现的，无头导出则直接使用了 jy-draftc。

## 目录

```
native/          剪映后台接入：配音、官方素材、加密草稿编辑；17 个 MCP 工具 + CLI
skill/jianying/  给 AI 助手的 skill：生成草稿、加密、导出、响度、登记的完整流程
```

## 快速开始

1. 安装剪映专业版 11.5.0.14471，登录账号，关闭自动更新。
2. 安装 Python 3.11+（在 3.14 上验证过）、ffmpeg 和 ffprobe；下载 [jy-draftc](https://github.com/wenshui330/jy-draftc) 的 11.5.0.14471 版本。
3. 按 [native/README.md](native/README.md) 安装依赖，把 `jianying-native` 注册成 MCP。
4. 把 `skill/jianying` 放进你的 AI 助手的 skills 目录（例如 `~/.claude/skills/jianying`），把文中的 `<repo>` 换成本仓库路径。
5. 运行检查：

```powershell
python -X utf8 skill\jianying\scripts\jy_pipeline.py status
python -X utf8 native\cli.py host-status
```

## 使用须知

- 会员音色和会员素材只在你自己的账号有对应权益时可用。本项目不绕过会员校验，也不绕过剪映宿主的权限拒绝。
- 生成配音、下载素材会创建真实的线上请求，可能消耗你账号的额度。
- 请遵守剪映的用户协议，以及素材、音乐、音色的使用许可。用剪映官方素材做的成片能否商用，以剪映的规定为准。
- 剪映更新版本后，原生接口可能变化、失效。

## 许可与第三方组件

本项目自有代码（`native/` 全部、`skill/jianying/SKILL.md`、`skill/jianying/scripts/jy_pipeline.py`）以 [MIT](LICENSE) 发布。

为了让流程开箱即用，仓库附带或调用了以下第三方组件，按其许可要求列出，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：

- [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)（Apache-2.0）：附带一份副本，用于从零生成草稿。
- [luoluoluo22/jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill)（MIT）：附带其中的草稿检查、素材 ID 检索脚本和素材表。
- [wenshui330/jy-draftc](https://github.com/wenshui330/jy-draftc)（MIT）：不附带，需自行下载，用于给生成的草稿加密和无头导出。
