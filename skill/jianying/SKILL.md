---
name: jianying
description: 在 Windows 本机用剪映专业版 11.5 自动出片和改片：用代码生成剪映草稿、加密、无头导出 MP4、统一响度；通过 jianying-native 调用剪映配音（含会员音色）、官方素材库，批量修改已加密的草稿。适用于用脚本批量做视频、给已有剪映工程换字或换素材、生成旁白配音。
---

# 剪映自动化（Windows，剪映专业版 11.5.0.14471）

下文的 `<repo>` 指本仓库根目录，`<skill>` 指 `<repo>\skill\jianying`。

几样东西各管一段，按需要组合：

| 要做的事 | 用什么 |
|---|---|
| 用代码搭一个新草稿（视频、音频、字幕轨） | `<skill>\vendor\pyJianYingDraft`（固定在 v1.5.0 的副本） |
| 加密、无头导出 MP4、统一响度、登记进剪映列表 | `<skill>\scripts\jy_pipeline.py`（封装 jy-draftc 和 ffmpeg） |
| 剪映配音、搜官方素材、改已加密草稿里的字幕或素材、读时间线 | `<repo>\native`：MCP 工具 `jianying_*`，或它的 CLI |
| 列草稿、看草稿结构 | `<skill>\scripts\draft_inspector.py` |
| 按中英文名查滤镜、转场、动画、云音乐的 ID | `<skill>\scripts\asset_search.py` |

## 1. 生成草稿

```python
import sys, os
sys.path.insert(0, r'<skill>\vendor')
import pyJianYingDraft as jy

root = os.path.join(os.environ['LOCALAPPDATA'], r'JianyingPro\User Data\Projects\com.lveditor.draft')
script = jy.DraftFolder(root).create_draft('我的草稿_v1', 1080, 1920)   # 30fps；同名会报错，allow_replace=True 才覆盖
script.add_track(jy.TrackType.video, '画面')
script.add_track(jy.TrackType.audio, '人声')
script.add_track(jy.TrackType.text, '字幕')
script.add_segment(jy.VideoSegment(r'D:\clip.mp4', jy.trange(0, 3_000_000)), '画面')        # 时间单位：微秒
script.add_segment(jy.AudioSegment(r'D:\voice.wav', jy.trange(0, 3_000_000)), '人声')
script.add_segment(jy.TextSegment('字幕文字', jy.trange(0, 3_000_000),
                   style=jy.TextStyle(size=10.6, align=1),
                   background=jy.TextBackground(color='#000000', alpha=.6)), '字幕')
script.save()          # 写出明文 draft_content.json，剪映 11.5 还打不开，要先加密
```

草稿必须建在剪映的草稿目录里（剪映设置里可改，默认如上），剪映才找得到。素材按绝对路径引用，素材文件不要挪。

## 2. 加密、导出、响度、登记

需要 [jy-draftc](https://github.com/wenshui330/jy-draftc)（11.5.0.14471 版）和 ffmpeg。路径用环境变量 `JY_DRAFTC`、`JY_INSTALL_DIR`、`JY_DRAFT_ROOT`、`FFMPEG` 指定，不设时从 PATH 和默认安装位置找。

```powershell
$py = '<skill>\scripts\jy_pipeline.py'
python -X utf8 $py status                                   # 检查 jy-draftc、剪映安装、ffmpeg
python -X utf8 $py deliver "<草稿目录>" -o D:\out\final.mp4  # 加密 → 导出 → 两遍响度(-14 LUFS, TP -1.3) → 登记
# 也可以分步：encrypt / export -o raw.mp4 / loudnorm raw.mp4 final.mp4 / register [--dry-run]
```

- 加密后旁边会多一个 `<草稿名>-enc` 文件夹，它跟着正式版一起保留，清理旧版时一起清。
- 导出前会等到连续 30 秒没有别的 jy-draftc 进程：几个导出同时跑会失败。
- 剪映原生导出约 −15～−17 LUFS，峰值偏高；`loudnorm` 会先压一下峰值，保证是线性响度调整。
- 登记会先备份 `root_meta_info.json` 再原子替换，不动其他条目。剪映开着时登记的新草稿，要重开剪映才看得到。
- 一个 1080×1920、100 秒的草稿，无头导出大约 50 秒。

## 3. jianying-native（配音、素材、改加密草稿）

在 `<repo>\native`，安装和注册方法见它的 README。注册成 MCP 后有 17 个 `jianying_*` 工具；没加载 MCP 时用 CLI：

```powershell
python -X utf8 '<repo>\native\cli.py' host-status
python -X utf8 '<repo>\native\cli.py' synthesize '要配音的文字' --voice '解说小帅'   # 每次 1–120 字
```

- 配音 `jianying_synthesize`：要求剪映已打开并登录。会员音色只在你的账号本身有权限时可用，工具不会绕过权限。没有语速参数，需要变速时用 ffmpeg `atempo`。
- 素材 `jianying_search_materials` → `jianying_add_catalog_asset` / `jianying_apply_cached_asset`。
- 改已加密草稿：先 `jianying_timeline` 拿片段 ID，再用 `jianying_edit_batch` 一次做完多项修改，结果输出到新目录，原稿不动。正在剪映前台打开的工程，先保存关掉再改。
- 它不能导出 MP4；需要成片时，用第 2 节的 jy-draftc 导出，或在剪映里手动导出。
- 已验证范围和已知边界：`<repo>\native\docs\VALIDATION.md`；协议细节：`<repo>\native\docs\NATIVE_PROTOCOL.md`。

## 4. 小工具

```powershell
python -X utf8 <skill>\scripts\draft_inspector.py list --limit 20
python -X utf8 <skill>\scripts\draft_inspector.py summary --name "草稿名"
python -X utf8 <skill>\scripts\asset_search.py "复古" -c filters     # 也可 -c transitions / text_animations / cloud_music_library ...
```

`draft_inspector` 读不了已加密的 `draft_content.json`。要看内容，先 `jy-draftc -dc "<草稿目录>" --jy-dir "<剪映版本目录>"` 解密出 `<草稿目录>-plain`，或者用 `jianying_timeline`。

## 环境与已知坑

- 只在剪映 11.5.0.14471 上验证过：11.6 的无头导出会崩溃，jy-draftc 的 11.5 版也只支持 11.5。建议关掉剪映自动更新。
- jy-draftc 目录下的 `.env` 只有 `JY_INSTALL_DIR` 一项，必须是 UTF-8 无 BOM，否则读不到。脚本里另外显式传了 `--jy-dir`。
- jy-draftc 退出码：0 正常 / 2 导出 / 8 dll / 11 加密 / 14 目录或版本，其余见它的 USAGE。
- 删除或移动草稿前，先完全退出剪映，包括托盘进程 `JianyingProTray`；剪映开着时删的草稿会被它写回。
- 用的是固定在 v1.5.0 的 pyJianYingDraft：它写 `draft_content.json`，适合 11.5。上游新版默认改写 `draft_info.json`。
- Windows 下 Python 加 `-X utf8`。
