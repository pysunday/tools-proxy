#!/bin/env python
import asyncio
import json
import gzip
import copy
import re
import chardet
from sunday.core import Logger, Fetch, getException, getParser
from sunday.utils import currentTimestamp, mergeObj, image
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

imageTypeList = ['png', 'gif', 'jpg', 'ico']

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


class BaseClass:
    def __init__(self, dataPath, collectList, closeList, proxyList, setting, port):
        self.dataPath = dataPath
        self.collectList = collectList
        self.closeList = closeList
        self.proxyList = proxyList
        self.setting = setting
        self.port = port

    def getSetting(self, url, key, defval=None):
        if url not in self.setting: return None
        return self.setting[url].get(key, defval)

    def getParams(self, flow):
        params = mergeObj(
                dict(flow.request.query),
                dict(flow.request.urlencoded_form),
                { 'header_method': flow.request.method })
        try:
            if flow.request.text: params.update(flow.request.json())
        except Exception as e:
            pass
        return params

    def checkUrlInclude(self, url, urlarr):
        for urlitem in urlarr:
            if urlitem == url: return True
            try:
                if re.search(urlitem, url):
                    return True
            except Exception as e:
                logger.error(f'匹配{url}失败，请检查{urlitem}是否为正则表达式')
        return False


class Collect(BaseClass):
    def __init__(self, *args, **kwargs):
        super(Collect, self).__init__(*args, **kwargs)
        logger.info(f'采集接口 => {self.dataPath}')

    def parseData(self, urlInfo, flow):
        url = grenPath(urlInfo)
        logger.warning('处理链接%s' % url)
        filecwd = path.join(self.dataPath, url)
        # info/main/format
        nowtime = datetime.today().isoformat()
        filecwdInfo = path.join(filecwd, 'info')
        filecwdFormat = path.join(filecwd, 'format')
        filecwdMain = path.join(filecwd, 'main')
        filecwdCurr = path.join(filecwd, nowtime)
        filecwdCurrInfo = f"{filecwdCurr}.info"
        if not path.exists(filecwd): makedirs(filecwd)
        content = flow.response.content
        try:
            if url.split('.').pop() in imageTypeList:
                with open(filecwdCurr, 'wb+') as currf, open(filecwdMain, 'wb+') as mainf:
                    currf.write(content)
                    mainf.write(content)
            else:
                encodeCfg = chardet.detect(content)
                if encodeCfg['confidence'] >= 0.8:
                    content = content.decode(encodeCfg['encoding'])
                else:
                    content = content.decode('utf-8')
                with open(filecwdCurr, 'w+') as currf, open(filecwdMain, 'w+') as mainf:
                    currf.write(content)
                    mainf.write(content)
        except Exception as e:
            logger.error(f'{url}返回内容解析失败')
            with open(filecwdCurr, 'wb+') as currf, open(filecwdMain, 'wb+') as mainf:
                currf.write(content)
                mainf.write(content)
        params = self.getParams(flow)
        skeys = self.getSetting(url, 'superkey', None)
        if skeys is not None:
            # 根据入参做文件映射
            superkeyCfg = path.join(filecwd, 'config')
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
        with open(filecwdCurrInfo, 'w+') as infof:
            infof.write(json.dumps(info, indent=4, cls=BytesEncoder))
        if self.getSetting(url, 'format', None):
            copyfile(filecwdCurr, filecwdFormat)
        if not path.exists(filecwdInfo):
            copyfile(filecwdCurrInfo, filecwdInfo)
        logger.info('文件写入成功!')

    def response(self, flow):
        urlInfo = urlparse(flow.request.url)
        if urlInfo.netloc: 
            url = grenPath(urlInfo)
            if len(self.collectList) == 0 or url in self.collectList:
                try:
                    self.parseData(urlInfo, flow)
                except Exception as e:
                    __import__('ipdb').set_trace()

class Playback(BaseClass):
    def __init__(self, *args, **kwargs):
        super(Playback, self).__init__(*args, **kwargs)
        logger.info(f'回放接口 => {self.dataPath}')
        self.fetch = Fetch()
        self.headerList = [
                'Set-Cookie', 'set-cookie',
                'Server', 'server',
                'Cache-Control', 'cache-control',
                'Pragma', 'pragma',
                'Connection', 'connection',
                'Location', 'location',
                'Content-Type', 'content-type',
                'Content-Encoding', 'content-encoding',
                'Cache-Control', 'cache-control']
        self.responseHandle = {}

    def getCollectPath(self, url):
        if len(self.collectList) == 0 or url in self.collectList: return url
        for coll in self.collectList:
            if url.find(coll) > -1 and url.find(coll) + len(coll) == len(url):
                return coll
        return False

    def response(self, flow):
        urlInfo = urlparse(flow.request.url)
        url = grenPath(urlInfo)
        if url not in self.responseHandle: return
        filepath = self.responseHandle[url]
        logger.info('本地: ' + filepath)
        with open(filepath, 'r') as ff:
            # content = bytes(ff.read(), 'utf-8')
            content = ff.read()
            if content:
                jsonpKey = self.getSetting(url, 'jsonp')
                if jsonpKey is not None:
                    params = self.getParams(flow)
                    content = re.sub(r'\b(.*?)\(', f'{params.get(jsonpKey, jsonpKey)}(', content, 1)
                flow.response.headers.update({'sunday_flag': 'proxy'})
                flow.response.content = bytes(content, 'utf-8')

    def request(self, flow):
        urlInfo = urlparse(flow.request.url)
        url = grenPath(urlInfo)
        collectPath = self.getCollectPath(url)
        # logger.warning('链接: ' + url)
        # if url in self.closeList or url.split('.').pop() in ['png', 'gif']:
        if not collectPath:
            logger.debug('网络: ' + url)
            return
        if self.checkUrlInclude(url, self.closeList):
            logger.error('拦截: ' + url)
            flow.response = http.Response.make(400, str.encode(''))
        elif url.split('.').pop() in imageTypeList:
            logger.info('图片: ' + url)
            mode = url.split('.').pop().lower()
            if mode == 'jpg': mode = 'jpeg'
            img_byte = getattr(image, f'grenImage{mode.title()}')(150)
            flow.response = http.Response.make(200, img_byte, {
                'Content-Type': f'image/{mode}'
                })
        else:
            filepath = ''
            filepath_tmp = path.join(self.dataPath, collectPath)
            if path.isdir(filepath_tmp):
                filepath_format_none = path.join(filepath_tmp, 'format')
                filepath_format_port = f'{filepath_format_none}-{self.port}'
                filepath_format = filepath_format_port if path.exists(filepath_format_port) else filepath_format_none
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
            skeys = self.getSetting(url, 'superkey', None)
            if skeys is not None and path.exists(superkeyCfg):
                # 根据入参做文件映射
                params = self.getParams(flow)
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
                flow.response = http.Response.make(res.status_code, res.content, { **dict(res.headers), "sunday_flag": "proxy" })
            elif filepath:
                if self.getSetting(url, 'response', None):
                    self.responseHandle[url] = filepath
                    return
                logger.info('本地: ' + filepath)
                info = {}
                content = ''
                content_type = 'str'
                try:
                    with open(filepath, 'r') as ff: content = ff.read()
                except Exception as e:
                    content_type = 'bin'
                    with open(filepath, 'rb') as ff: content = ff.read()
                if content:
                    with open(filepath_info, 'r') as fi: info = json.load(fi)
                    jsonpKey = self.getSetting(url, 'jsonp')
                    if jsonpKey is not None:
                        params = self.getParams(flow)
                        content = re.sub(r'\b(.*?)\(', f'{params.get(jsonpKey, jsonpKey)}(', content, 1)
                    fields = [(key, self.fields_parse(key, val)) for key, val in copy.deepcopy(get(info, 'response.headers.fields')) if key in self.headerList]
                    fields.extend([
                        ("sunday_flag", "proxy"),
                        ("Access-Control-Allow-Origin", "*"),
                    ])
                    status_code = get(info, 'response.status_code')
                    if type(content) != bytes: content = bytes(content, 'utf-8')
                    flow.response = http.Response.make(status_code, content, [(bytes(key, 'utf-8'), bytes(val, 'utf-8')) for key, val in fields])
            else:
                logger.debug('网络: ' + url)

    def fields_parse(self, key, val):
        if key in ['content_type', 'Content-Type']:
            return re.sub(r'charset=[A-Za-z0-9-_]*\b', 'charset=UTF8', val)
        return val


class Proxy():
    def __init__(self, name='playback', host='0.0.0.0', port=7758, collectList=None, closeList=None, proxyList=None, dataPath=None, setting=None, isLog=False, **kwargs):
        self.name = name
        self.host = host
        self.port = int(port)
        self.collectList = collectList or []
        self.closeList = closeList or []
        self.proxyList = proxyList or []
        self.setting = setting or {}
        self.configFile = None
        self.dataPath = dataPath
        self.runpath = path.realpath(path.curdir)
        self.isLog = isLog

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
                self.setting = configObj.get('setting', {})
            except Exception as e:
                raise SundayException(-1, '配置文件解析失败，请检查文件%s内容是否为JSON格式' % self.configFile.name)

    async def run(self):
        self.init()
        logger.info('捕获处理的链接有: %s' % self.collectList)
        logger.info('拦截处理的链接有: %s' % self.closeList)
        logger.info('代理处理的链接有: %s' % self.proxyList)
        logger.info('特定链接强化配置: %s' % self.setting)
        opts = options.Options(
            listen_host=self.host,
            listen_port=self.port,
        )
        master = dump.DumpMaster(
            opts,
            with_termlog=self.isLog,
            with_dumper=False,
        )
        if self.name not in ['collect', 'playback']:
            raise SundayException(-1, '传入name值不正确，请检查')
        Addon = Collect if self.name == 'collect' else Playback
        master.addons.add(
            Addon(path.join(self.runpath, self.dataPath), self.collectList, self.closeList, self.proxyList, self.setting, self.port),
            )
        await master.run()


def runcmd():
    parser = getParser(**CMDINFO)
    handle = parser.parse_args(namespace=Proxy())
    asyncio.run(handle.run())

if __name__ == '__main__':
    runcmd()
