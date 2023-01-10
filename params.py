import argparse

CMDINFO = {
    "version": '0.0.1',
    "description": "辅助代理工具",
    "epilog": """
使用案例:
    %(prog)s -c config.json -n collect -h 0.0.0.0 -p 7758
    """,
    'params': {
        'DEFAULT': [
            {
                'name': ['-c', '--config-file'],
                'dest': 'configFile',
                'metavar': 'FILE',
                'help': ('需要处理链接的json配置文件, closeList配置的链接请求会被中止，'
                    'proxyList配置的链接将通过sunday fetch重新发起请求并返回结果，'
                    'collectList配置收集与回放的链接，不配置则为所有符合'
                    'setting用于根据url个性化配置，如superkey用于根据入参区别文件加载，jsonp配置用于修改全局函数'),
                'nargs': 1,
                'type': argparse.FileType('r'),
                # 'required': True
            },
            {
                'name': ['-n', '--name'],
                'dest': 'name',
                'help': '需要执行的任务名称，collect(收集)或playback(回放), 默认：playback',
                'default': 'playback'
            },
            {
                'name': ['-H', '--host'],
                'dest': 'host',
                'help': '代理的主机名，默认：0.0.0.0',
                'default': '0.0.0.0'
            },
            {
                'name': ['-p', '--port'],
                'dest': 'port',
                'help': '代理的端口名，默认：7758',
                'default': 7758,
                'type': int
            },
            {
                'name': ['-d', '--data-path'],
                'dest': 'dataPath',
                'help': '数据目录',
                'default': 'datas/default'
            },
            {
                'name': ['--log'],
                'dest': 'isLog',
                'help': '是否展示日志',
                'default': False,
                'action': 'store_true'
            },
        ]
    }
}

