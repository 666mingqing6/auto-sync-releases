#!/usr/bin/env python3
"""
自动同步GitHub Release文件的脚本
"""

import os
import yaml
import requests
import json
import re
from datetime import datetime
from pathlib import Path
import shutil
import sys

def load_config():
    """加载配置文件"""
    with open('projects.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_latest_release(repo, include_prerelease=False):
    """获取最新Release信息"""
    if include_prerelease:
        url = f"https://api.github.com/repos/{repo}/releases"
        response = requests.get(url)
        if response.status_code == 200:
            releases = response.json()
            if releases:
                return releases[0]  # 第一个是最新的
    else:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    return None

def should_download_asset(asset_name, patterns):
    """判断文件是否需要下载"""
    for pattern in patterns:
        if re.match(pattern.replace('*', '.*'), asset_name):
            return True
    return False

def download_file(url, save_path):
    """下载文件"""
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    return False

def get_version_info_path(target_dir):
    """获取版本信息文件路径"""
    return os.path.join(target_dir, '.version.json')

def save_version_info(target_dir, release_info, downloaded_files):
    """保存版本信息"""
    version_info = {
        'tag_name': release_info['tag_name'],
        'published_at': release_info['published_at'],
        'sync_time': datetime.now().isoformat(),
        'assets': [],
        'downloaded_files': downloaded_files  # 记录实际下载的文件列表
    }
    
    for asset in release_info.get('assets', []):
        version_info['assets'].append({
            'name': asset['name'],
            'size': asset['size'],
            'download_url': asset['browser_download_url']
        })
    
    version_path = get_version_info_path(target_dir)
    with open(version_path, 'w', encoding='utf-8') as f:
        json.dump(version_info, f, indent=2, ensure_ascii=False)

def check_file_integrity(target_dir, version_info):
    """检查文件完整性：确保版本信息中记录的文件都存在"""
    if not version_info or 'downloaded_files' not in version_info:
        return False
    
    downloaded_files = version_info.get('downloaded_files', [])
    
    # 如果没有记录下载的文件，视为不完整
    if not downloaded_files:
        return False
    
    # 检查每个文件是否存在
    for filename in downloaded_files:
        file_path = os.path.join(target_dir, filename)
        if not os.path.exists(file_path):
            print(f"  文件缺失: {filename}")
            return False
    
    return True

def needs_update(target_dir, latest_release, asset_patterns):
    """检查是否需要更新"""
    version_path = get_version_info_path(target_dir)
    
    # 如果版本信息文件不存在，需要更新
    if not os.path.exists(version_path):
        print(f"  版本信息文件不存在，需要更新")
        return True
    
    try:
        with open(version_path, 'r', encoding='utf-8') as f:
            current_info = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"  版本信息文件损坏，需要更新")
        return True
    
    # 检查文件完整性
    if not check_file_integrity(target_dir, current_info):
        print(f"  文件不完整，需要更新")
        return True
    
    # 检查发布时间
    if 'published_at' in current_info and 'published_at' in latest_release:
        try:
            current_time = datetime.fromisoformat(current_info['published_at'].replace('Z', '+00:00'))
            latest_time = datetime.fromisoformat(latest_release['published_at'].replace('Z', '+00:00'))
            
            if latest_time > current_time:
                print(f"  有新版本: {latest_release['tag_name']} > {current_info['tag_name']}")
                return True
            else:
                print(f"  已是最新版本: {current_info['tag_name']}")
                return False
        except ValueError as e:
            print(f"  解析日期时出错: {e}，需要更新")
            return True
    
    # 如果没有发布日期信息，比较tag_name
    if 'tag_name' in current_info and 'tag_name' in latest_release:
        if current_info['tag_name'] != latest_release['tag_name']:
            print(f"  标签不同: {latest_release['tag_name']} != {current_info['tag_name']}")
            return True
    
    # 检查是否有新的匹配文件需要下载
    if 'downloaded_files' in current_info:
        downloaded_files = set(current_info['downloaded_files'])
        # 检查最新release中是否有新的匹配文件
        for asset in latest_release.get('assets', []):
            if should_download_asset(asset['name'], asset_patterns):
                if asset['name'] not in downloaded_files:
                    print(f"  有新的匹配文件: {asset['name']}")
                    return True
    
    return False

def sync_project(project_config):
    """同步单个项目"""
    repo = project_config['repo']
    target_dir = project_config['target_dir']
    asset_patterns = project_config.get('asset_patterns', ['.*'])
    include_prerelease = project_config.get('include_prerelease', False)
    
    print(f"正在同步 {project_config['name']} ({repo})...")
    
    # 获取最新Release
    release = get_latest_release(repo, include_prerelease)
    if not release:
        print(f"  警告：无法获取 {repo} 的Release信息")
        return False
    
    # 创建目标目录
    os.makedirs(target_dir, exist_ok=True)
    
    # 检查是否需要更新
    if not needs_update(target_dir, release, asset_patterns):
        print(f"  已是最新版本，无需更新")
        return False
    
    # 记录将要下载的文件
    files_to_download = []
    for asset in release.get('assets', []):
        if should_download_asset(asset['name'], asset_patterns):
            files_to_download.append(asset['name'])
    
    if not files_to_download:
        print(f"  警告：没有匹配的文件可下载")
        return False
    
    # 清空目录（保留版本信息文件）
    version_files = ['.version.json']
    for item in os.listdir(target_dir):
        item_path = os.path.join(target_dir, item)
        if item not in version_files and os.path.isfile(item_path):
            os.remove(item_path)
        elif item not in version_files and os.path.isdir(item_path):
            shutil.rmtree(item_path)
    
    # 下载文件
    downloaded_files = []
    for asset in release.get('assets', []):
        asset_name = asset['name']
        
        if should_download_asset(asset_name, asset_patterns):
            print(f"  正在下载: {asset_name}")
            save_path = os.path.join(target_dir, asset_name)
            
            if download_file(asset['browser_download_url'], save_path):
                downloaded_files.append(asset_name)
                print(f"    下载完成 ({asset['size'] / 1024 / 1024:.2f} MB)")
            else:
                print(f"    下载失败")
    
    # 保存版本信息
    if downloaded_files:
        save_version_info(target_dir, release, downloaded_files)
        print(f"  同步完成: {release['tag_name']} ({len(downloaded_files)} 个文件)")
        return True
    else:
        print(f"  警告：没有文件被下载")
        return False

def main():
    """主函数"""
    print("开始同步 GitHub Release 文件...")
    print("=" * 50)
    
    config = load_config()
    updated_projects = []
    
    for project in config['projects']:
        try:
            if sync_project(project):
                updated_projects.append(project['name'])
        except Exception as e:
            print(f"同步 {project['name']} 时出错: {e}")
            import traceback
            traceback.print_exc()
    
    print("=" * 50)
    if updated_projects:
        print(f"同步完成！更新了 {len(updated_projects)} 个项目:")
        for name in updated_projects:
            print(f"  - {name}")
    else:
        print("所有项目都已是最新版本")
    
    return len(updated_projects) > 0

if __name__ == '__main__':
    try:
        has_updates = main()
        # 退出码用于GitHub Actions判断
        sys.exit(0 if not has_updates else 1)
    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"主程序出错: {e}")
        sys.exit(1)
