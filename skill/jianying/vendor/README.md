# vendor

- `pyJianYingDraft/`：[GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) 的副本（Apache-2.0，见该目录 `LICENSE`），取自 [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) v1.5.0 自带的版本。固定在这个版本，因为它写 `draft_content.json`，适合剪映 11.5 + jy-draftc；后来的版本改为默认写 `draft_info.json`。
- `../scripts/draft_inspector.py`、`asset_search.py`、`utils/` 和 `../data/*.csv` 取自 jianying-editor-skill v1.7.0（MIT，见 `../LICENSE-jianying-editor-MIT.txt`）。`data/` 里的云音乐和视频素材表去掉了会过期的签名下载链接，只保留 ID 和元数据。
