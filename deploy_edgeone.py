#!/usr/bin/env python3
"""
EdgeOne 边缘函数自动部署脚本

通过腾讯云 OpenAPI 自动部署/更新 EdgeOne 边缘函数代码。
读取 meting-api.txt（或 proxy.txt）的内容，部署到指定 EdgeOne 站点。

使用方式：
    # 部署 meting-api
    python deploy_edgeone.py meting-api

    # 部署 proxy
    python deploy_edgeone.py proxy

    # 部署自定义文件
    python deploy_edgeone.py --file /path/to/code.js --name my-function

环境变量（必须）：
    TENCENTCLOUD_SECRET_ID     腾讯云 API SecretId
    TENCENTCLOUD_SECRET_KEY    腾讯云 API SecretKey
    EDGEONE_ZONE_ID            EdgeOne 站点 ID（如 zone-xxxxxxxx）

环境变量（可选）：
    EDGEONE_HOST               触发规则匹配的 Host（默认 meting-api.646474.xyz）

前置条件：
    pip install tencentcloud-sdk-python

获取 SecretId/SecretKey：
    https://console.cloud.tencent.com/cam/capi
获取 ZoneId：
    EdgeOne 控制台 → 站点列表 → 复制站点 ID
"""

import os
import sys
import json
import time
import argparse

try:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.teo.v20220901 import teo_client, models
except ImportError:
    print("错误：缺少腾讯云 SDK，请运行：pip install tencentcloud-sdk-python")
    sys.exit(1)


# 预设部署配置：文件名 → (函数名, 触发Host, 描述)
PRESETS = {
    'meting-api': {
        'file': 'meting-api.txt',
        'name': 'meting-api',
        'host': 'meting-api.646474.xyz',
        'remark': 'Meting API - 网易云音乐接口（playlist/song/url/pic/lrc）',
    },
    'proxy': {
        'file': 'proxy.txt',
        'name': 'proxy',
        'host': 'proxy.646474.xyz',
        'remark': '通用 CORS 代理',
    },
}


def get_credentials():
    """从环境变量获取腾讯云凭证"""
    secret_id = os.environ.get('TENCENTCLOUD_SECRET_ID')
    secret_key = os.environ.get('TENCENTCLOUD_SECRET_KEY')
    if not secret_id or not secret_key:
        print("错误：请设置环境变量 TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY")
        print("获取地址：https://console.cloud.tencent.com/cam/capi")
        sys.exit(1)
    return secret_id, secret_key


def get_zone_id():
    """从环境变量获取 EdgeOne ZoneId"""
    zone_id = os.environ.get('EDGEONE_ZONE_ID')
    if not zone_id:
        print("错误：请设置环境变量 EDGEONE_ZONE_ID")
        print("获取方式：EdgeOne 控制台 → 站点列表 → 复制站点 ID")
        sys.exit(1)
    return zone_id


def create_client(secret_id, secret_key):
    """创建 EdgeOne API 客户端"""
    cred = credential.Credential(secret_id, secret_key)
    http_profile = HttpProfile()
    http_profile.endpoint = "teo.tencentcloudapi.com"
    http_profile.reqTimeout = 30
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    client_profile.signMethod = "TC3-HMAC-SHA256"
    return teo_client.TeoClient(cred, "", client_profile)


def find_function_by_name(client, zone_id, function_name):
    """按名称查找已存在的函数，返回 FunctionId 或 None"""
    req = models.DescribeFunctionsRequest()
    req.ZoneId = zone_id
    req.Filters = [
        models.Filter(
            Name="name",
            Values=[function_name]
        )
    ]
    req.Offset = 0
    req.Limit = 20
    resp = client.DescribeFunctions(req)
    for func in resp.Functions:
        if func.Name == function_name:
            return func.FunctionId
    return None


def deploy_function(client, zone_id, function_name, content, remark):
    """部署函数：已存在则 ModifyFunction，不存在则 CreateFunction"""
    existing_id = find_function_by_name(client, zone_id, function_name)

    if existing_id:
        print(f"  函数已存在 (FunctionId={existing_id})，执行 ModifyFunction 更新代码...")
        req = models.ModifyFunctionRequest()
        req.ZoneId = zone_id
        req.FunctionId = existing_id
        req.Content = content
        req.Remark = remark
        client.ModifyFunction(req)
        print(f"  OK 代码已更新并重新部署")
        return existing_id
    else:
        print(f"  函数不存在，执行 CreateFunction 创建...")
        req = models.CreateFunctionRequest()
        req.ZoneId = zone_id
        req.Name = function_name
        req.Content = content
        req.Remark = remark
        resp = client.CreateFunction(req)
        func_id = resp.FunctionId
        print(f"  OK 函数已创建 (FunctionId={func_id})")
        return func_id


def find_rule_for_function(client, zone_id, function_id):
    """查找已绑定到该函数的触发规则"""
    req = models.DescribeFunctionRulesRequest()
    req.ZoneId = zone_id
    resp = client.DescribeFunctionRules(req)
    for rule in resp.FunctionRules:
        if rule.FunctionId == function_id:
            return rule.RuleId
    return None


def ensure_trigger_rule(client, zone_id, function_id, host, remark):
    """确保触发规则存在：Host == host → 执行该函数"""
    existing_rule_id = find_rule_for_function(client, zone_id, function_id)

    # 构造规则条件：HOST == host
    condition = models.FunctionRuleCondition()
    condition.RuleConditions = [
        models.RuleCondition(
            Operator="equal",
            Values=[host],
            Target="host"
        )
    ]

    if existing_rule_id:
        print(f"  触发规则已存在 (RuleId={existing_rule_id})，执行 ModifyFunctionRule 更新...")
        req = models.ModifyFunctionRuleRequest()
        req.ZoneId = zone_id
        req.RuleId = existing_rule_id
        req.FunctionRuleConditions = [condition]
        req.FunctionId = function_id
        req.TriggerType = "direct"
        req.Remark = remark
        client.ModifyFunctionRule(req)
        print(f"  OK 触发规则已更新：Host == {host}")
    else:
        print(f"  触发规则不存在，执行 CreateFunctionRule 创建...")
        req = models.CreateFunctionRuleRequest()
        req.ZoneId = zone_id
        req.FunctionId = function_id
        req.FunctionRuleConditions = [condition]
        req.Remark = remark
        resp = client.CreateFunctionRule(req)
        print(f"  OK 触发规则已创建 (RuleId={resp.RuleId})：Host == {host}")


def deploy_preset(preset_name, file_override=None, name_override=None, host_override=None):
    """部署预设配置"""
    if preset_name not in PRESETS:
        print(f"错误：未知预设 '{preset_name}'，可选：{', '.join(PRESETS.keys())}")
        sys.exit(1)

    preset = PRESETS[preset_name]
    file_path = file_override or preset['file']
    function_name = name_override or preset['name']
    host = host_override or os.environ.get('EDGEONE_HOST', preset['host'])
    remark = preset['remark']

    # 读取代码文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    code_path = os.path.join(script_dir, file_path)
    if not os.path.exists(code_path):
        print(f"错误：代码文件不存在：{code_path}")
        sys.exit(1)

    with open(code_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"部署 {preset_name}：")
    print(f"  代码文件：{file_path} ({len(content)} 字符)")
    print(f"  函数名称：{function_name}")
    print(f"  触发Host：{host}")
    print()

    # 初始化客户端
    secret_id, secret_key = get_credentials()
    zone_id = get_zone_id()
    client = create_client(secret_id, secret_key)

    print(f"ZoneId: {zone_id}")
    print()

    # 部署函数代码
    print("[1/2] 部署函数代码...")
    func_id = deploy_function(client, zone_id, function_name, content, remark)

    # 等待部署生效
    time.sleep(2)

    # 确保触发规则
    print()
    print("[2/2] 配置触发规则...")
    ensure_trigger_rule(client, zone_id, func_id, host, remark)

    print()
    print(f"OK 部署完成！")
    print(f"  访问地址：https://{host}/")
    return func_id


def main():
    parser = argparse.ArgumentParser(
        description='EdgeOne 边缘函数自动部署脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python deploy_edgeone.py meting-api          # 部署 meting-api
  python deploy_edgeone.py proxy               # 部署 proxy
  python deploy_edgeone.py meting-api --host api.example.com  # 自定义触发Host
        """
    )
    parser.add_argument('preset', choices=list(PRESETS.keys()),
                        help='部署预设名称')
    parser.add_argument('--file', help='自定义代码文件路径')
    parser.add_argument('--name', help='自定义函数名称')
    parser.add_argument('--host', help='自定义触发Host（覆盖默认值）')

    args = parser.parse_args()

    deploy_preset(
        preset_name=args.preset,
        file_override=args.file,
        name_override=args.name,
        host_override=args.host,
    )


if __name__ == '__main__':
    main()
