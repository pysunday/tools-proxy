#!/bin/env python
import asyncio
import json
from sunday.core import Logger, Fetch, getException, getParser
from os import path, makedirs
from mitmproxy import options, http
from mitmproxy.tools import dump
from urllib.parse import urlparse, unquote
from pydash import omit
from sunday.tools.proxy.params import CMDINFO

SundayException = getException()

logger = Logger('TOOLS PROXY').getLogger()

class BytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode()
        elif hasattr(obj, '__dict__') and type(obj.__dict__) is dict:
            return obj.__dict__
        return json.JSONEncoder.default(self, obj)

def grenPath(urlInfo):
    url = urlInfo.netloc + urlInfo.path
    if url[-1] == '/': url += 'index.html'
    return url

class Collect:
    def __init__(self, dataPath, collectList, closeList, proxyList):
        logger.info(f'采集接口 => {dataPath}')
        self.dataPath = dataPath
        self.collectList = collectList
        self.closeList = closeList
        self.proxyList = proxyList

    def parseData(self, urlInfo, flow):
        url = grenPath(urlInfo)
        logger.warning('处理链接%s' % url)
        filecwd = self.dataPath + url
        if path.exists(filecwd): return
        filedir = path.dirname(filecwd)
        if not path.exists(filedir): makedirs(filedir)
        with open(filecwd, 'w+') as f:
            f.write(flow.response.content.decode('utf-8'))
        with open(filecwd + '.info', 'w+') as f:
            info = {
                    'url': url,
                    'url_full': unquote(flow.request.url),
                    'request': flow.request.data.__dict__,
                    'response': omit(flow.response.data.__dict__, ['content']),
                    }
            f.write(json.dumps(info, indent=4, cls=BytesEncoder))
        logger.info('文件写入成功!')

    def response(self, flow):
        urlInfo = urlparse(flow.request.url)
        url = grenPath(urlInfo)
        if len(self.collectList) == 0 or url in self.collectList:
            self.parseData(urlInfo, flow)

class Playback:
    def __init__(self, dataPath, collectList, closeList, proxyList):
        logger.info(f'回放接口 => {dataPath}')
        self.fetch = Fetch()
        self.dataPath = dataPath
        self.collectList = collectList
        self.closeList = closeList
        self.proxyList = proxyList

    def getCollectPath(self, url):
        if len(self.collectList) == 0 or url in self.collectList: return url
        for coll in self.collectList:
            if url.find(coll) + len(coll) == len(url):
                return coll
        return False

    def request(self, flow):
        urlInfo = urlparse(flow.request.url)
        url = grenPath(urlInfo)
        collectPath = self.getCollectPath(url)
        # logger.warning('链接: ' + url)
        if url in self.closeList or url.split('.').pop() in ['png', 'gif']:
            logger.warning('拦截: ' + url)
            flow.response = http.Response.make(200, str.encode('sunday proxy'))
        elif collectPath:
            filepath = ''
            collectPathSplit = collectPath.split('/')
            temp = collectPathSplit[-1].split('.')
            temp[-1] = 'format.' + temp[-1]
            collectPathSplit[-1] = '.'.join(temp)
            filepath1 = path.join(self.dataPath, *collectPathSplit)
            filepath2 = path.join(self.dataPath, collectPath)
            if path.exists(filepath1) and path.isfile(filepath1):
                filepath = filepath1
            elif path.exists(filepath2) and path.isfile(filepath2):
                filepath = filepath2
            if url in self.proxyList:
                logger.warning('代理: ' + url)
                data = flow.request.data.content
                headers = dict(flow.request.headers)
                targeturl = flow.request.url
                res = getattr(self.fetch, flow.request.method.lower())(targeturl, data=data, headers=headers)
                flow.response = http.Response.make(res.status_code, res.content, { **dict(res.headers), "sunday_flag": "7758" })
            elif filepath:
                logger.warning('本地: ' + filepath)
                with open(filepath, 'r') as f:
                    content = f.read()
                    flow.response = http.Response.make(200, str.encode(content), { "sunday_flag": "7758" })

class Proxy():
    def __init__(self, name='playback', host='0.0.0.0', port=7758, collectList=None, closeList=None, proxyList=None, dataPath=None, **kwargs):
        self.name = name
        self.host = host
        self.port = int(port)
        self.collectList = collectList or []
        self.closeList = closeList or []
        self.proxyList = proxyList or []
        self.configFile = None
        self.dataPath = dataPath
        self.runpath = path.realpath(path.curdir)

    def addCloseUrl(self, url):
        if type(url) == str: url = [url]
        if type(url) != list: return
        logger.debug('add close url %s' % url)
        self.closeList.extend(list(filter(lambda item: item not in self.closeList, url)))

    def addProxyUrl(self, url):
        if type(url) == str: url = [url]
        if type(url) != list: return
        logger.debug('add proxy url %s' % url)
        self.proxyList.extend(list(filter(lambda item: item not in self.proxyList, url)))

    def addCollectUrl(self, url):
        if type(url) == str: url = [url]
        if type(url) != list: return
        logger.debug('add collect url %s' % url)
        self.collectList.extend(list(filter(lambda item: item not in self.collectList, url)))

    def init(self):
        if self.configFile:
            try:
                configStr = self.configFile[0].read()
                configObj = json.loads(configStr)
                self.collectList = configObj.get('collectList', [])
                self.proxyList = configObj.get('proxyList', [])
                self.closeList = configObj.get('closeList', [])
            except Exception as e:
                raise SundayException(-1, '配置文件解析失败，请检查文件%s内容是否为JSON格式' % self.configFile.name)

    async def run(self):
        self.init()
        logger.info('捕获处理的链接有: %s' % self.collectList)
        logger.info('拦截处理的链接有: %s' % self.closeList)
        logger.info('代理处理的链接有: %s' % self.proxyList)
        opts = options.Options(listen_host=self.host, listen_port=self.port)
        master = dump.DumpMaster(
            opts,
            with_termlog=False,
            with_dumper=False,
        )
        if self.name not in ['collect', 'playback']:
            raise SundayException(-1, '传入name值不正确，请检查')
        Addon = Collect if self.name == 'collect' else Playback
        master.addons.add(
            Addon(path.join(self.runpath, self.dataPath), self.collectList, self.closeList, self.proxyList),
            )
        await master.run()


def runcmd():
    parser = getParser(**CMDINFO)
    handle = parser.parse_args(namespace=Proxy())
    asyncio.run(handle.run())

if __name__ == '__main__':
    runcmd()
