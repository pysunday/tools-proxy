# 插件描述

sunday的抓包辅助插件，功能非常强大，用于代理请求保存及代理请求回放

# 使用方式

```
usage: sd_proxy [-v] [-h] [-c FILE] [-n NAME] [-H HOST] [-p PORT] [-d DATA_PATH]

辅助代理工具

Optional:
  -v, --version                        当前程序版本
  -h, --help                           打印帮助说明
  -c FILE, --config-file FILE          需要处理链接的json配置文件, closeList配置的链接请求会被中止，proxyList配置的链接将通过sunday fetch重新发起请求并返回结果，collectList配置收集与回放的链接，
                                       不配置则为所有符合setting用于根据url个性化配置，如superkey用于根 据入参区别文件加载，jsonp配置用于修改全局函数, format配置用于同时保存为format文件
  -n NAME, --name NAME                 需要执行的任务名称，collect(收集)或playback(回放), 默认：playback
  -H HOST, --host HOST                 代理的主机名，默认：0.0.0.0
  -p PORT, --port PORT                 代理的端口名，默认：7758
  -d DATA_PATH, --data-path DATA_PATH  数据目录

使用案例:
    sd_proxy -c config.json -n collect -h 0.0.0.0 -p 7758
```

案例一(代理请求保存, 监听端口7756，配置文件./config.json, 操作目录./dirname)：`sd_proxy -H 0.0.0.0 -p 7756 -n collect -d dirname -c config.json`

案例二(代理请求回放, 监听端口7758，配置文件./config.json, 操作目录./dirname)：`sd_proxy -H 0.0.0.0 -p 7756 -n playback -d dirname -c config.json`

# config文件配置

config文件可以完善并提供程序强大的功能，配置项包括：collectList、closeList、proxyList、setting

## collectList

不配置或配置为空数组则监听处理所有请求，如果配置了则只监听处理这些配置的链接

## closeList

配置了则相应请求直接被终止, 链接请求返回400

## proxyList

配置的链接请求通过sunday的fetch发起并将结果返回

## setting

setting用户个性化配置

格式如：

```
{
  "setting": {
    "host:port/path": {
      "format": true,
      "superkey": ["key1", "key2"],
      "jsonp": "key"
    }
  }
}
```

### setting.format

配置为true则请求结果同时保存到format文件

### setting.superkey

superkey配置的值包括请求体、请求方法组成的对象，通过值不能映射为不同的文件，当再次请求时，代理会根据配置的superkey值返回不同的内容文件

### setting.jsonp

同uperkey的取值，自动将jsonp文本的函数名改为请求入参指定的名称
