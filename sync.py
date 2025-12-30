#!/usr/bin/env python3
"""
自动同步GitHub Release及Action Artifact文件的脚本
"""

import os
import yaml
import requests
import json
import re
from datetime import datetime
from pathlib import Path
import shutil
import time

def load_config():
    """加载配置文件"""
    with open('projects.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_github_headers():
    """获取GitHub API请求头（包含认证）"""
    headers = {'Accept': 'application/vnd.github.v3+json'}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'token {token}'
    return headers

def get_latest_release(repo, include_prerelease=False):
    """获取最新Release信息"""
    headers = get_github_headers()
    
    if include_prerelease:
        url = f"https://api.github.com/repos/{repo}/releases"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            releases = response.json()
            if releases:
                return releases[0]
    else:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
    
    print(f"  警告：无法获取 {repo} 的Release信息，状态码：{response.status_code}")
    return None

def get_latest_action_artifact(repo, workflow_filename=None):
    """
    获取最新的Action Artifact信息
    repo: 格式如 "JingMatrix/LSPosed"
    workflow_filename: 可选的workflow文件名，如 "core.yml"
    """
    headers = get_github_headers()
    base_url = f"https://api.github.com/repos/{repo}/actions"
    
    # 1. 获取最新的workflow运行记录
    runs_url = f"{base_url}/runs"
    params = {'status': 'completed', 'per_page': 5}
    if workflow_filename:
        params['event'] = 'push'
    
    response = requests.get(runs_url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"  无法获取 {repo} 的workflow运行记录，状态码：{response.status_code}")
        return None
    
    runs = response.json().get('workflow_runs', [])
    if not runs:
        print(f"  {repo} 没有找到已完成的workflow运行")
        return None
    
    # 2. 获取最新运行中的artifacts
    latest_run = runs[0]
    artifacts_url = latest_run['artifacts_url']
    
    artifacts_response = requests.get(artifacts_url, headers=headers)
    if artifacts_response.status_code != 200:
        print(f"  无法获取 {repo} 的artifacts，状态码：{artifacts_response.status_code}")
        return None
    
    artifacts = artifacts_response.json().get('artifacts', [])
    if not artifacts:
        print(f"  {repo} 的最新运行中没有找到artifacts")
        return None
    
    # 构建类似release的返回结构，保持接口一致
    return {
        'type': 'action',
        'id': latest_run['id'],
        'run_number': latest_run['run_number'],
        'created_at': latest_run['created_at'],
        'updated_at': latest_run['updated_at'],
        'html_url': latest_run['html_url'],
        'artifacts': artifacts,
        'workflow_name': latest_run['name']
    }

def should_download_asset(asset_name, patterns):
    """判断文件是否需要下载"""
    for pattern in patterns:
        if re.match(pattern.replace('*', '.*'), asset_name):
            return True
    return False

def download_file(url, save_path):
    """下载文件（支持GitHub API认证）"""
    headers = get_github_headers()
    
    # 对于GitHub API的下载链接，需要特殊处理
    if 'api.github.com' in url and 'artifacts' in url:
        # GitHub artifact下载需要特殊的Accept头
        headers['Accept'] = 'application/vnd.github.v3+json'
    
    response = requests.get(url, headers=headers, stream=True)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    
    print(f"  下载失败，状态码：{response.status_code}")
    return False

def get_version_info_path(target_dir):
    """获取版本信息文件路径"""
    return os.path.join(target_dir, '.version.json')

def save_version_info(target_dir, info, info_type='release'):
    """保存版本信息"""
    if info_type == 'release':
        version_info = {
            'type': 'release',
            'tag_name': info['tag_name'],
            'published_at': info['published_at'],
            'sync_time': datetime.now().isoformat(),
            'assets': []
        }
        
        for asset in info.get('assets', []):
            version_info['assets'].append({
                'name': asset['name'],
                'size': asset['size'],
                'download_url': asset['browser_download_url']
            })
    else:  # action类型
        version_info = {
            'type': 'action',
            'run_id': info['id'],
            'run_number': info['run_number'],
            'created_at': info['created_at'],
            'sync_time': datetime.now().isoformat(),
            'workflow_name': info['workflow_name'],
            'artifacts': []
        }
        
        for artifact in info.get('artifacts', []):
            version_info['artifacts'].append({
                'name': artifact['name'],
                'size': artifact['size_in_bytes'],
                'download_url': artifact['archive_download_url']
            })
    
    version_path = get_version_info_path(target_dir)
    with open(version_path, 'w', encoding='utf-8') as f:
        json.dump(version_info, f, indent=2, ensure_ascii=False)

def needs_update(target_dir, latest_info, info_type='release'):
    """检查是否需要更新"""
    version_path = get_version_info_path(target_dir)
    
    if not os.path.exists(version_path):
        return True
    
    with open(version_path, 'r', encoding='utf-8') as f:
        current_info = json.load(f)
    
    # 如果类型不同，需要更新
    if current_info.get('type') != info_type:
        return True
    
    if info_type == 'release':
        current_time = datetime.fromisoformat(current_info['published_at'].replace('Z', '+00:00'))
        latest_time = datetime.fromisoformat(latest_info['published_at'].replace('Z', '+00:00'))
        return latest_time > current_time
    else:  # action类型
        current_run_id = current_info.get('run_id')
        latest_run_id = latest_info['id']
        # 如果run_id不同，说明有新的运行
        return current_run_id != latest_run_id

def sync_release_project(project_config):
    """同步传统的Release项目"""
    repo = project_config['repo']
    target_dir = project_config['target_dir']
    asset_patterns = project_config.get('asset_patterns', ['.*'])
    include_prerelease = project_config.get('include_prerelease', False)
    
    print(f"正在同步Release项目 {project_config['name']} ({repo})...")
    
    # 获取最新Release
    release = get_latest_release(repo, include_prerelease)
    if not release:
        return False
    
    # 创建目标目录
    os.makedirs(target_dir, exist_ok=True)
    
    # 检查是否需要更新
    if os.path.exists(os.path.join(target_dir, '.version.json')):
        if not needs_update(target_dir, release, 'release'):
            print(f"  已是最新版本: {release['tag_name']}")
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
    downloaded_count = 0
    for asset in release.get('assets', []):
        asset_name = asset['name']
        
        if should_download_asset(asset_name, asset_patterns):
            print(f"  正在下载: {asset_name}")
            save_path = os.path.join(target_dir, asset_name)
            
            if download_file(asset['browser_download_url'], save_path):
                downloaded_count += 1
                print(f"    下载完成 ({asset['size'] / 1024 / 1024:.2f} MB)")
            else:
                print(f"    下载失败")
    
    # 保存版本信息
    save_version_info(target_dir, release, 'release')
    
    print(f"  同步完成: {release['tag_name']} ({downloaded_count} 个文件)")
    return True

def sync_action_project(project_config):
    """同步Action Artifact项目"""
    repo = project_config['repo']
    target_dir = project_config['target_dir']
    asset_patterns = project_config.get('asset_patterns', ['.*'])
    workflow_file = project_config.get('workflow_file')
    
    print(f"正在同步Action项目 {project_config['name']} ({repo})...")
    
    # 获取最新Action Artifact
    action_info = get_latest_action_artifact(repo, workflow_file)
    if not action_info:
        return False
    
    # 创建目标目录
    os.makedirs(target_dir, exist_ok=True)
    
    # 检查是否需要更新
    if os.path.exists(os.path.join(target_dir, '.version.json')):
        if not needs_update(target_dir, action_info, 'action'):
            print(f"  已是最新Action运行: #{action_info['run_number']}")
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
    downloaded_count = 0
    for artifact in action_info.get('artifacts', []):
        artifact_name = artifact['name']
        
        if should_download_asset(artifact_name, asset_patterns):
            print(f"  正在下载: {artifact_name}")
            
            # *** 核心修改：构建最终保存的文件名 ***
            # 如果原始名称没有.zip后缀，则添加；如果已有，则保留。
            if not artifact_name.lower().endswith('.zip'):
                final_filename = f"{artifact_name}.zip"
            else:
                final_filename = artifact_name
            
            save_path = os.path.join(target_dir, final_filename)
            
            # GitHub Artifact 下载URL
            download_url = artifact['archive_download_url']
            
            if download_file(download_url, save_path):
                downloaded_count += 1
                # 注意：这里显示的size是原始JSON里的size，可能与实际文件大小略有差异
                print(f"    下载完成 ({artifact['size_in_bytes'] / 1024 / 1024:.2f} MB)")
                # 成功下载后，打印文件保存的确切路径，便于你查找
                print(f"    文件已保存为: {final_filename}")
            else:
                print(f"    下载失败")
    
    # 保存版本信息
    save_version_info(target_dir, action_info, 'action')
    
    print(f"  同步完成: Action运行 #{action_info['run_number']} ({downloaded_count} 个artifacts)")
    return True

def sync_project(project_config):
    """同步单个项目（根据类型分发）"""
    # 默认为release类型，兼容旧配置
    project_type = project_config.get('type', 'release')
    
    if project_type == 'release':
        return sync_release_project(project_config)
    elif project_type == 'action':
        return sync_action_project(project_config)
    else:
        print(f"  未知的项目类型: {project_type}")
        return False

def main():
    """主函数"""
    print("开始同步GitHub文件...")
    print("=" * 50)
    
    config = load_config()
    updated_projects = []
    
    for project in config['projects']:
        try:
            if sync_project(project):
                updated_projects.append(project['name'])
        except Exception as e:
            print(f"同步 {project.get('name', '未知项目')} 时出错: {e}")
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
    has_updates = main()
    exit(0 if not has_updates else 1)
