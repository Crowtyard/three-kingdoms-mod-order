"""Restore this user's screenshot order in the official CA launcher."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime


HERE = Path(__file__).resolve().parent
GAME = 'threekingdoms'


def read_list(raw):
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, list) or not all(isinstance(m, dict) for m in data):
        raise ValueError('配置必须是 JSON mod 数组。')
    return data


def load_profile(path):
    profile = read_list(path.read_bytes())
    if len(profile) != 55 or [m['order'] for m in profile] != list(range(1, 56)):
        raise ValueError('固定顺序必须完整包含第 1–55 项。')
    if len({m['uuid'].casefold() for m in profile}) != 55:
        raise ValueError('固定顺序存在重复 mod 标识。')
    for m in profile:
        if m['game'] != GAME or type(m['active']) is not bool:
            raise ValueError('固定顺序中的游戏或开关字段不正确。')
        for key in ('uuid', 'packfile', 'name'):
            if not isinstance(m[key], str) or not m[key]:
                raise ValueError(f'固定顺序缺少有效字段：{key}')
    return profile


def plan_order(current, profile):
    result = copy.deepcopy(current)
    known = {m['uuid'].casefold() for m in profile}
    index = {}
    for m in result:
        if m['game'] != GAME:
            continue
        key = m['uuid'].casefold()
        if key in index:
            raise ValueError(f'启动器配置存在重复 mod：{key}')
        index[key] = m
        # Keep old, uninstalled records untouched; a newly installed mod needs
        # an explicit position rather than an invented placement.
        if key not in known and Path(m['packfile']).is_file():
            raise ValueError(f'发现截图之外的已安装 mod，请先指定位置：{m["name"]}')
    for target in profile:
        key = target['uuid'].casefold()
        if key in index:
            m = index[key]
        else:
            m = copy.deepcopy(target)
            result.append(m)
        if not Path(m['packfile']).is_file():
            raise FileNotFoundError(f'找不到第 {target["order"]} 项：{target["name"]}\n{m["packfile"]}')
        m['order'] = target['order']
        m['active'] = target['active']
    return result


def require_closed():
    command = (
        "Get-Process -Name launcher,Three_Kingdoms -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty ProcessName; exit 0"
    )
    checked = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if checked.stdout.strip():
        raise RuntimeError('请先正常关闭全战启动器和《全面战争：三国》，再运行本操作。')


def write_change(path, before, after):
    require_closed()
    if path.read_bytes() != before:
        raise RuntimeError('配置刚被其他程序修改，本次未写入，请重新运行。')
    backup_dir = path.parent / 'three-kingdoms-order-backups'
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / (path.name + '.' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.bak')
    with backup.open('xb') as file:
        file.write(before)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='mod-order-', suffix='.tmp', delete=False) as file:
            temp = Path(file.name)
            file.write(after)
            file.flush()
            os.fsync(file.fileno())
        require_closed()
        if path.read_bytes() != before:
            raise RuntimeError('写入前配置发生变化，已停止。')
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    if path.read_bytes() != after:
        raise RuntimeError(f'写入后的校验失败，请使用备份恢复：{backup}')
    return backup


def run(action, config, profile_path):
    if action != 'preview':
        require_closed()
    before = config.read_bytes()
    current = read_list(before)
    if action == 'restore':
        backup_dir = config.parent / 'three-kingdoms-order-backups'
        backups = sorted(backup_dir.glob(config.name + '.*.bak'))
        if not backups:
            raise FileNotFoundError('还没有本脚本创建的备份。')
        source = backups[-1]
        after = source.read_bytes()
        read_list(after)
        backup = write_change(config, before, after)
        print(f'已恢复：{source}\n恢复前的配置也已备份：{backup}')
        return
    profile = load_profile(profile_path)
    result = plan_order(current, profile)
    print('截图固定顺序（1–55）：')
    for m in profile:
        print(f'{m["order"]:02d}. [{"开启" if m["active"] else "关闭"}] {m["name"]}')
    changed = sum(
        not any(m['game'] == GAME and m['uuid'].casefold() == p['uuid'].casefold()
                and m['order'] == p['order'] and m['active'] == p['active'] for m in current)
        for p in profile
    )
    print(f'\n共 55 项，开启 {sum(m["active"] for m in profile)} 项，需要更新 {changed} 项。')
    if action == 'preview':
        print('仅预览，未修改启动器配置。')
    elif result == current:
        print('已经与截图一致，无需修改。')
    else:
        after = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        backup = write_change(config, before, after)
        print(f'排序已保存并校验。请重新打开启动器。\n备份：{backup}')


def main():
    parser = argparse.ArgumentParser(description='按截图固定顺序恢复三国的 55 个 mod。')
    parser.add_argument('action', choices=['preview', 'apply', 'restore'], nargs='?', default='preview')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--profile', type=Path, default=HERE / 'order.json')
    args = parser.parse_args()
    config = args.config
    if config is None:
        config = Path(os.environ['APPDATA']) / 'The Creative Assembly/Launcher/20190104-moddata.dat'
    try:
        run(args.action, config, args.profile)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'操作失败：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
