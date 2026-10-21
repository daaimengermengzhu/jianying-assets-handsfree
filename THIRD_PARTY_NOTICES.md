# 第三方内容

| 内容 | 位置 | 来源 | 许可 |
|---|---|---|---|
| pyJianYingDraft（v1.5.0 副本） | `skill/jianying/vendor/pyJianYingDraft/` | https://github.com/GuanYixuan/pyJianYingDraft | Apache-2.0，全文见该目录 `LICENSE` |
| 草稿检查、素材检索脚本，`utils/`，素材表 `data/*.csv` | `skill/jianying/scripts/`、`skill/jianying/data/` | https://github.com/luoluoluo22/jianying-editor-skill （v1.7.0） | MIT，全文见 `skill/jianying/LICENSE-jianying-editor-MIT.txt` |
| jy-draftc | 不随本仓库分发，需自行下载 | https://github.com/wenshui330/jy-draftc | MIT |
| 剪映专业版及其自带组件（`videoeditor.dll`、`videoeditor_addon.node`、`bun.exe` 等） | 不随本仓库分发，运行时读取用户本机安装 | 字节跳动 | 剪映用户协议 |

对 pyJianYingDraft 副本的修改：本仓库未改动；该副本取自 jianying-editor-skill v1.5.0，可能包含其作者对上游的本地补丁。
对 jianying-editor-skill 脚本的修改：未改动逻辑；`data/cloud_music_library.csv` 和 `data/cloud_video_assets.csv` 删去了签名下载链接列。
