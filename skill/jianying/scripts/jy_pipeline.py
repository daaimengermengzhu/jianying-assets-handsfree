"""剪映 11.5 出片流水线小工具：登记草稿、加密、无头导出、两遍响度。

用法（python -X utf8 jy_pipeline.py <命令> ...）：
  status                               检查 jy-draftc / 剪映安装 / ffmpeg 路径
  register  DRAFT_DIR [--dry-run]      把草稿登记进 root_meta_info.json（先备份，原子替换，不动其他条目）
  encrypt   DRAFT_DIR                  jy-draftc 加密；确认草稿已不是明文
  export    DRAFT_DIR -o RAW.mp4 [--size 1080x1920 --fps 30 --timeout 900]
  loudnorm  IN.mp4 OUT.mp4 [--i -14 --tp -1.3 --lra 11]   两遍 linear loudnorm，视频流直接复制
  deliver   DRAFT_DIR -o FINAL.mp4 [...] 加密 → 导出 → 响度 → 登记，一步完成

路径可用环境变量覆盖：JY_DRAFTC、JY_INSTALL_DIR、JY_DRAFT_ROOT、FFMPEG。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

JY_DRAFTC = Path(os.environ.get('JY_DRAFTC') or shutil.which('jy-draftc') or 'jy-draftc.exe')
JY_INSTALL_DIR = Path(os.environ.get('JY_INSTALL_DIR', r'C:\Program Files\JianyingPro\Apps\11.5.0.14471'))
DRAFT_ROOT = Path(os.environ.get('JY_DRAFT_ROOT', Path(os.environ.get('LOCALAPPDATA', '')) / 'JianyingPro/User Data/Projects/com.lveditor.draft'))
FFMPEG = Path(os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'ffmpeg.exe')
IDLE_SECONDS = 30


def log(msg: str) -> None:
    print(f'[jy_pipeline] {msg}', flush=True)


def run(args: list, logfile: Path | None = None) -> str:
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = (proc.stdout or '') + (proc.stderr or '')
    if logfile:
        logfile.write_text(out, encoding='utf-8')
    if proc.returncode != 0:
        raise RuntimeError(f'{Path(str(args[0])).name} 退出码 {proc.returncode}\n{out[-2000:]}')
    return out


def is_plaintext(path: Path) -> bool:
    return path.read_bytes().lstrip().startswith(b'{')


def wait_export_idle(seconds: int = IDLE_SECONDS) -> None:
    """等到连续 seconds 秒没有 jy-draftc 进程（多个任务不能同时导出）。只等待，不结束任何进程。"""
    quiet_since = None
    while True:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq jy-draftc.exe', '/FO', 'CSV', '/NH'],
                             capture_output=True).stdout.lower()
        if b'jy-draftc.exe' in out:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= seconds:
            return
        time.sleep(2)


# ---------------------------------------------------------------- commands
def cmd_status(_: argparse.Namespace) -> None:
    for name, p in [('jy-draftc', JY_DRAFTC), ('剪映安装', JY_INSTALL_DIR / 'videoeditor.dll'), ('草稿目录', DRAFT_ROOT), ('ffmpeg', FFMPEG)]:
        log(f'{name}: {p} {"✓" if p.exists() else "✗ 不存在"}')
    env = JY_DRAFTC.parent / '.env'
    if env.exists():
        has_bom = env.read_bytes().startswith(b'\xef\xbb\xbf')
        log(f'jy-draftc .env 带 BOM: {has_bom}（必须为 False）')


def cmd_register(a: argparse.Namespace) -> None:
    folder = Path(a.draft).resolve()
    root_path = folder.parent / 'root_meta_info.json'
    meta_path = folder / 'draft_meta_info.json'
    content = folder / 'draft_content.json'
    if not meta_path.exists():
        raise SystemExit(f'缺少 {meta_path}（用 DraftFolder.create_draft 建草稿会自动带上）')
    plain = json.loads(content.read_text(encoding='utf-8')) if content.exists() and is_plaintext(content) else None
    for _ in range(10):
        before = root_path.read_bytes()
        root = json.loads(before)
        entries = root['all_draft_store']
        others = copy.deepcopy([e for e in entries if e.get('draft_name') != folder.name])
        existing = next((e for e in entries if e.get('draft_name') == folder.name), None)
        if not existing and not entries:
            raise SystemExit('root_meta_info.json 里没有任何条目可作模板，请先在剪映里新建一个草稿')
        now = time.time_ns() // 1000
        e = copy.deepcopy(existing or entries[0])
        e.update(draft_name=folder.name, draft_fold_path=folder.as_posix(), draft_root_path=folder.parent.as_posix(),
                 draft_json_file=content.as_posix(), draft_cover=(folder / 'draft_cover.jpg').as_posix(),
                 draft_id=(plain or {}).get('id') or (existing or {}).get('draft_id') or str(uuid.uuid4()).upper(),
                 tm_duration=(plain or {}).get('duration', (existing or {}).get('tm_duration', 0)),
                 tm_draft_create=(existing or {}).get('tm_draft_create', now), tm_draft_modified=now,
                 tm_draft_removed=0, draft_is_invisible=False)
        if a.dry_run:
            log('dry-run，将写入的条目：\n' + json.dumps(e, ensure_ascii=False, indent=1))
            return
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        for k in ['draft_name', 'draft_id', 'draft_fold_path', 'draft_root_path', 'draft_cover', 'tm_duration', 'tm_draft_create', 'tm_draft_modified']:
            meta[k] = e[k]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        if existing:
            entries[entries.index(existing)] = e
        else:
            entries.insert(0, e)
            root['draft_ids'] = root.get('draft_ids', 0) + 1
        assert [x for x in entries if x.get('draft_name') != folder.name] == others
        backup = folder / f'root_meta_info.before_register_{time.strftime("%Y%m%d_%H%M%S")}.json'
        backup.write_bytes(before)
        tmp = root_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(root, ensure_ascii=False), encoding='utf-8')
        if root_path.read_bytes() != before:  # 剪映或别的任务刚改过，重读再来
            tmp.unlink()
            continue
        os.replace(tmp, root_path)
        log(f'已登记 {folder.name}（备份 {backup.name}）；剪映要重开或刷新列表才看得到')
        return
    raise RuntimeError('root_meta_info.json 一直在被改动，登记放弃')


def cmd_encrypt(a: argparse.Namespace) -> None:
    folder = Path(a.draft).resolve()
    content = folder / 'draft_content.json'
    wait_export_idle()
    run([JY_DRAFTC, '-ec', folder, '-f', '--jy-dir', JY_INSTALL_DIR], folder / 'jy_encrypt.log')
    enc = folder.parent / (folder.name + '-enc') / 'draft_content.json'
    if is_plaintext(content) and enc.exists() and not is_plaintext(enc):
        shutil.copy2(enc, content)
    if is_plaintext(content):
        raise RuntimeError('加密后 draft_content.json 仍是明文')
    log(f'已加密 {folder.name}（旁边的 -enc 副本跟随正式版保留）')


def cmd_export(a: argparse.Namespace) -> Path:
    folder = Path(a.draft).resolve()
    out = Path(a.output).resolve()
    if is_plaintext(folder / 'draft_content.json'):
        raise SystemExit('草稿还是明文，先 encrypt')
    wait_export_idle()
    run([JY_DRAFTC, '-ex', folder, '-o', out, '--size', a.size, '--fps', a.fps, '--timeout', a.timeout, '-f', '--jy-dir', JY_INSTALL_DIR],
        out.with_suffix('.export.log'))
    log(f'已导出 {out}')
    return out


def measure(path: Path, i: float, tp: float, lra: float, pre: str = '') -> dict:
    out = run([FFMPEG, '-hide_banner', '-i', path, '-vn', '-af', f'{pre}loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json', '-f', 'null', '-'])
    return json.loads(out[out.rfind('{'):out.rfind('}') + 1])


def limiter(limit_db: float) -> str:
    """真峰值预压限：升采样到 192k 再限幅，避免 loudnorm 因峰值不够而退化成 dynamic。"""
    amp = min(1.0, 10 ** (limit_db / 20))
    return f'aresample=192000,alimiter=limit={amp:.4f}:level=false:attack=5:release=50:latency=true,aresample=48000,'


def loudnorm_pass(src: Path, dst: Path, a: argparse.Namespace, pre: str) -> tuple[dict, dict]:
    m = measure(src, a.i, a.tp, a.lra, pre)
    af = (f"{pre}loudnorm=I={a.i}:TP={a.tp}:LRA={a.lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    out = run([FFMPEG, '-y', '-hide_banner', '-i', src, '-map', '0:v', '-map', '0:a', '-c:v', 'copy', '-af', af,
               '-ar', 48000, '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', dst])
    return m, json.loads(out[out.rfind('{'):out.rfind('}') + 1])


def cmd_loudnorm(a: argparse.Namespace) -> None:
    src, dst = Path(a.input).resolve(), Path(a.output).resolve()
    m, second = loudnorm_pass(src, dst, a, '')
    pre = ''
    if second.get('normalization_type') != 'linear':
        gain = a.i - float(m['input_i'])  # 线性提升量；峰值需先压到 TP 目标 - 提升量，再留 0.3 dB 余量
        pre = limiter(a.tp - gain - 0.3)
        log(f'峰值不够提升 {gain:.2f} dB，先压限到 {a.tp - gain - 0.3:.2f} dBFS 再做一次')
        m, second = loudnorm_pass(src, dst, a, pre)
    final = measure(dst, a.i, a.tp, a.lra)
    note = '' if second.get('normalization_type') == 'linear' else '（仍为 dynamic，请检查素材）'
    log(f"响度 {m['input_i']} → {final['input_i']} LUFS，真峰值 {final['input_tp']} dBTP，模式 {second.get('normalization_type')}{note}")


def cmd_deliver(a: argparse.Namespace) -> None:
    cmd_encrypt(a)
    final = Path(a.output).resolve()
    raw = final.with_name(final.stem + '_jyraw.mp4')
    cmd_export(argparse.Namespace(draft=a.draft, output=raw, size=a.size, fps=a.fps, timeout=a.timeout))
    cmd_loudnorm(argparse.Namespace(input=raw, output=final, i=a.i, tp=a.tp, lra=a.lra))
    cmd_register(argparse.Namespace(draft=a.draft, dry_run=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status').set_defaults(fn=cmd_status)
    p = sub.add_parser('register'); p.add_argument('draft'); p.add_argument('--dry-run', action='store_true'); p.set_defaults(fn=cmd_register)
    p = sub.add_parser('encrypt'); p.add_argument('draft'); p.set_defaults(fn=cmd_encrypt)
    for name, fn in [('export', cmd_export), ('deliver', cmd_deliver)]:
        p = sub.add_parser(name); p.add_argument('draft'); p.add_argument('-o', '--output', required=True)
        p.add_argument('--size', default='1080x1920'); p.add_argument('--fps', default='30'); p.add_argument('--timeout', default='900')
        if name == 'deliver':
            p.add_argument('--i', type=float, default=-14); p.add_argument('--tp', type=float, default=-1.3); p.add_argument('--lra', type=float, default=11)
        p.set_defaults(fn=fn)
    p = sub.add_parser('loudnorm'); p.add_argument('input'); p.add_argument('output')
    p.add_argument('--i', type=float, default=-14); p.add_argument('--tp', type=float, default=-1.3); p.add_argument('--lra', type=float, default=11)
    p.set_defaults(fn=cmd_loudnorm)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
