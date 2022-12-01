#!/bin/env python
import asyncio
import json
import gzip
import re
import chardet
from sunday.core import Logger, Fetch, getException, getParser
from sunday.utils import currentTimestamp, mergeObj
from os import path, makedirs, listdir, mknod
from mitmproxy import options, http
from mitmproxy.tools import dump
from urllib.parse import urlparse, unquote
from pydash import omit, get
from sunday.tools.proxy.params import CMDINFO
from datetime import datetime
from shutil import copyfile

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
    def __init__(self, dataPath, collectList, closeList, proxyList, superkey):
        logger.info(f'采集接口 => {dataPath}')
        self.dataPath = dataPath
        self.collectList = collectList
        self.closeList = closeList
        self.proxyList = proxyList
        self.superkey = superkey

    def parseData(self, urlInfo, flow):
        url = grenPath(urlInfo)
        logger.warning('处理链接%s' % url)
        filecwd = path.join(self.dataPath, url)
        # info/main/format
        nowtime = datetime.today().isoformat()
        filecwdInfo = path.join(filecwd, 'info')
        filecwdMain = path.join(filecwd, 'main')
        filecwdCurr = path.join(filecwd, nowtime)
        filecwdCurrInfo = f"{filecwdCurr}.info"
        if not path.exists(filecwd): makedirs(filecwd)
        with open(filecwdCurr, 'w+') as currf, open(filecwdMain, 'w+') as mainf, open(filecwdCurrInfo, 'w+') as infof:
            content = flow.response.content
            encodeCfg = chardet.detect(content)
            if encodeCfg['confidence'] >= 0.8: content = content.decode(encodeCfg['encoding'])
            currf.write(content)
            mainf.write(content)
            params = mergeObj(
                    dict(flow.request.query),
                    dict(flow.request.urlencoded_form),
                    { 'method': flow.request.method })
            try:
                if flow.request.text: params.update(flow.request.json())
            except Exception as e:
                # logger.exception(e)
                pass
            if url in self.superkey:
                # 根据入参做文件映射
                superkeyCfg = path.join(filecwd, 'config')
                skeys = self.superkey.get(url, [])
                key = '@@'.join([params[skey] for skey in skeys if type(params.get(skey)) == str])
                obj = None
                if not path.exists(superkeyCfg): open(superkeyCfg, 'a').close()
                with open(superkeyCfg, 'r+') as superf:
                    text = superf.read()
                    if text:
                        obj = json.loads(text)
                        if key not in obj:
                            obj[key] = nowtime
                        else:
                            obj = None
                    else:
                        obj = { key: nowtime }
                if obj:
                    with open(superkeyCfg, 'w+') as superf:
                        superf.write(json.dumps(obj, indent=4))
            info = {
                    'url': url,
                    'url_full': unquote(flow.request.url),
                    'params': params,
                    'request': flow.request.data.__dict__,
                    'response': omit(flow.response.data.__dict__, ['content']),
                    }
            infof.write(json.dumps(info, indent=4, cls=BytesEncoder))
        if not path.exists(filecwdInfo):
            copyfile(filecwdCurrInfo, filecwdInfo)
        logger.info('文件写入成功!')

    def response(self, flow):
        urlInfo = urlparse(flow.request.url)
        if urlInfo.netloc: 
            url = grenPath(urlInfo)
            if len(self.collectList) == 0 or url in self.collectList:
                self.parseData(urlInfo, flow)

class Playback:
    def __init__(self, dataPath, collectList, closeList, proxyList, superkey):
        logger.info(f'回放接口 => {dataPath}')
        self.fetch = Fetch()
        self.dataPath = dataPath
        self.collectList = collectList
        self.closeList = closeList
        self.proxyList = proxyList
        self.superkey = superkey
        self.headerList = [
                'Content-Type', 'content-type',
                'Content-Encoding', 'content-encoding',
                'Cache-Control', 'cache-control']

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
            filepath_tmp = path.join(self.dataPath, collectPath)
            if path.isdir(filepath_tmp):
                filepath_format = path.join(filepath_tmp, 'format')
                filepath_main = path.join(filepath_tmp, 'main')
                filepath_info = path.join(filepath_tmp, 'info')
            else:
                collectPathSplit = collectPath.split('/')
                temp = collectPathSplit[-1].split('.')
                temp[-1] = 'format.' + temp[-1]
                collectPathSplit[-1] = '.'.join(temp)
                filepath_format = path.join(self.dataPath, *collectPathSplit)
                filepath_main = filepath_tmp
                filepath_info = filepath_tmp + '.info'
            superkeyCfg = path.join(filepath_tmp, 'config')
            if url in self.superkey and path.exists(superkeyCfg):
                # 根据入参做文件映射
                skeys = self.superkey.get(url, [])
                params = mergeObj(
                        dict(flow.request.query),
                        dict(flow.request.urlencoded_form),
                        { 'method': flow.request.method })
                try:
                    if flow.request.text: params.update(flow.request.json())
                except Exception as e:
                    pass
                key = '@@'.join([params[skey] for skey in skeys if type(params.get(skey)) == str])
                with open(superkeyCfg, 'r+') as superf:
                    text = superf.read()
                    if text:
                        obj = json.loads(text)
                        if key in obj:
                            filepath = path.join(filepath_tmp, obj[key])
            if filepath:
                pass
            elif path.exists(filepath_format) and path.isfile(filepath_format):
                filepath = filepath_format
            elif path.exists(filepath_main) and path.isfile(filepath_main):
                filepath = filepath_main
            elif path.exists(filepath_info) and path.isdir(filepath_tmp):
                for name in listdir(filepath_tmp):
                    try:
                        datetime.fromisoformat(name)
                        filepath = path.join(filepath_tmp, name)
                        copyfile(filepath, filepath_main)
                        break
                    except Exception as e:
                        pass
            if url in self.proxyList:
                logger.warning('代理: ' + url)
                data = flow.request.data.content
                headers = dict(flow.request.headers)
                targeturl = flow.request.url
                res = getattr(self.fetch, flow.request.method.lower())(targeturl, data=data, headers=headers)
                flow.response = http.Response.make(res.status_code, res.content, { **dict(res.headers), "sunday_flag": "7758" })
            elif filepath:
                logger.warning('本地: ' + filepath)
                with open(filepath, 'r') as ff, open(filepath_info, 'r') as fi:
                    content = bytes(ff.read(), 'utf-8')
                    if content:
                        info = json.load(fi)
                        fields = {key.lower(): val for key, val in get(info, 'response.headers.fields') if key in self.headerList}
                        if 'content-type' in fields:
                            fields['content-type'] = re.sub(r'charset=[A-Za-z0-9-_]*\b', 'charset=UTF8', fields['content-type'])
                        flow.response = http.Response.make(200, content, { "sunday_flag": "proxy", **fields })
                        # if 'gzip' in fields['Content-Encoding']:
                        #     flow.response.encode('gzip')

class Proxy():
    def __init__(self, name='playback', host='0.0.0.0', port=7758, collectList=None, closeList=None, proxyList=None, dataPath=None, superkey=None, **kwargs):
        self.name = name
        self.host = host
        self.port = int(port)
        self.collectList = collectList or []
        self.closeList = closeList or []
        self.proxyList = proxyList or []
        self.superkey = superkey or {}
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
                self.superkey = configObj.get('superkey', {})
            except Exception as e:
                raise SundayException(-1, '配置文件解析失败，请检查文件%s内容是否为JSON格式' % self.configFile.name)

    async def run(self):
        self.init()
        logger.info('捕获处理的链接有: %s' % self.collectList)
        logger.info('拦截处理的链接有: %s' % self.closeList)
        logger.info('代理处理的链接有: %s' % self.proxyList)
        logger.info('接口入参强化配置: %s' % self.superkey)
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
            Addon(path.join(self.runpath, self.dataPath), self.collectList, self.closeList, self.proxyList, self.superkey),
            )
        await master.run()


def runcmd():
    parser = getParser(**CMDINFO)
    handle = parser.parse_args(namespace=Proxy())
    asyncio.run(handle.run())

if __name__ == '__main__':
    runcmd()
