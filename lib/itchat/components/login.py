import io
import json
import logging
import os
import random
import re
import threading
import time
import traceback
from http.client import BadStatusLine

import requests
from pyqrcode import QRCode

from .contact import ContactManager
from .messages import MessageManager
from .. import config, utils
from ..returnvalues import ReturnValue
from ..storage.templates import wrap_user_dict

logger = logging.getLogger('itchat')


class LoginManager:
    def __init__(self, core):
        self.core = core
        core.login = self.login
        core.get_QRuuid = self.get_QRuuid
        core.get_QR = self.get_QR
        core.check_login = self.check_login
        core.web_init = self.web_init
        core.show_mobile_login = self.show_mobile_login
        core.start_receiving = self.start_receiving
        core.get_msg = self.get_msg
        core.logout = self.logout

        self.contact_massager = ContactManager(core)
        self.message_massager = MessageManager(core)

    def login(self, enableCmdQR=False, picDir=None, qrCallback=None,
              loginCallback=None, exitCallback=None):
        if self.core.alive or self.core.isLogging:
            logger.warning('itchat has already logged in.')
            return
        self.core.isLogging = True
        logger.info('Ready to login.')
        while self.core.isLogging:
            uuid = self.push_login()
            if uuid:
                qrStorage = io.BytesIO()
            else:
                logger.info('Getting uuid of QR code.')
                while not self.get_QRuuid():
                    time.sleep(1)
                logger.info('Downloading QR code.')
                qrStorage = self.get_QR(enableCmdQR=enableCmdQR,
                                        picDir=picDir, qrCallback=qrCallback)
            isLoggedIn = False
            while not isLoggedIn:
                status = self.check_login()
                if callable(qrCallback):
                    qrCallback(uuid=self.core.uuid, status=status,
                               qrcode=qrStorage.getvalue())
                if status == '200':
                    isLoggedIn = True
                elif status == '201':
                    if isLoggedIn is not None:
                        logger.info('Please press confirm on your phone.')
                        isLoggedIn = None
                        time.sleep(7)
                    time.sleep(0.5)
                elif status != '408':
                    break
            if isLoggedIn:
                break
            elif self.core.isLogging:
                logger.info('Log in time out, reloading QR code.')
        else:
            return  # log in process is stopped by user
        logger.info('Loading the contact, this may take a little while.')
        self.web_init()
        self.show_mobile_login()
        self.core.get_contact(True)
        if callable(loginCallback):
            loginCallback()
        else:
            if os.path.exists(picDir or config.DEFAULT_QR):
                os.remove(picDir or config.DEFAULT_QR)
            logger.info('Login successfully as %s' % self.core.storageClass.nickName)
        self.start_receiving(exitCallback)
        self.core.isLogging = False

    def push_login(self):
        cookiesDict = self.core.s.cookies.get_dict()
        if 'wxuin' in cookiesDict:
            url = '%s/cgi-bin/mmwebwx-bin/webwxpushloginurl?uin=%s' % (
                config.BASE_URL, cookiesDict['wxuin'])
            headers = {'User-Agent': config.USER_AGENT}
            r = self.core.s.get(url, headers=headers).json()
            if 'uuid' in r and r.get('ret') in (0, '0'):
                self.core.uuid = r['uuid']
                return r['uuid']
        return False

    def get_QRuuid(self):
        url = '%s/jslogin' % config.BASE_URL
        params = {
            'appid': 'wx782c26e4c19acffb',
            'fun': 'new',
            'redirect_uri': 'https://wx.qq.com/cgi-bin/mmwebwx-bin/webwxnewloginpage?mod=desktop',
            'lang': 'zh_CN'}
        headers = {'User-Agent': config.USER_AGENT}
        r = self.core.s.get(url, params=params, headers=headers)
        regx = r'window.QRLogin.code = (\d+); window.QRLogin.uuid = "(\S+?)";'
        data = re.search(regx, r.text)
        if data and data.group(1) == '200':
            self.core.uuid = data.group(2)
            return self.core.uuid

    def get_QR(self, uuid=None, enableCmdQR=False, picDir=None, qrCallback=None):
        uuid = uuid or self.core.uuid
        picDir = picDir or config.DEFAULT_QR
        qrStorage = io.BytesIO()
        qrCode = QRCode('https://login.weixin.qq.com/l/' + uuid)
        qrCode.png(qrStorage, scale=10)
        if callable(qrCallback):
            qrCallback(uuid=uuid, status='0', qrcode=qrStorage.getvalue())
        else:
            with open(picDir, 'wb') as f:
                f.write(qrStorage.getvalue())
            if enableCmdQR:
                utils.print_cmd_qr(qrCode.text(1), enableCmdQR=enableCmdQR)
            else:
                utils.print_qr(picDir)
        return qrStorage

    def check_login(self, uuid=None):
        uuid = uuid or self.core.uuid
        url = '%s/cgi-bin/mmwebwx-bin/login' % config.BASE_URL
        localTime = int(time.time())
        params = 'loginicon=true&uuid=%s&tip=1&r=%s&_=%s' % (
            uuid, int(-localTime / 1579), localTime)
        headers = {'User-Agent': config.USER_AGENT}
        r = self.core.s.get(url, params=params, headers=headers)
        regx = r'window.code=(\d+)'
        data = re.search(regx, r.text)
        if data and data.group(1) == '200':
            if self.process_login_info(r.text):
                return '200'
            else:
                return '400'
        elif data:
            return data.group(1)
        else:
            return '400'

    def process_login_info(self, loginContent):
        ''' when finish login (scanning qrcode)
         * syncUrl and fileUploadingUrl will be fetched
         * deviceid and msgid will be generated
         * skey, wxsid, wxuin, pass_ticket will be fetched
        '''
        regx = r'window.redirect_uri="(\S+)";'
        self.core.loginInfo['url'] = re.search(regx, loginContent).group(1)
        headers = {'User-Agent': config.USER_AGENT,
                   'client-version': config.UOS_PATCH_CLIENT_VERSION,
                   'extspam': config.UOS_PATCH_EXTSPAM,
                   'referer': 'https://wx.qq.com/?&lang=zh_CN&target=t'}
        r = self.core.s.get(self.core.loginInfo['url'],
                            headers=headers, allow_redirects=False)
        self.core.loginInfo['url'] = self.core.loginInfo['url'][:self.core.loginInfo['url'].rfind('/')]
        for indexUrl, detailedUrl in (
                ("wx2.qq.com", ("file.wx2.qq.com", "webpush.wx2.qq.com")),
                ("wx8.qq.com", ("file.wx8.qq.com", "webpush.wx8.qq.com")),
                ("qq.com", ("file.wx.qq.com", "webpush.wx.qq.com")),
                ("web2.wechat.com", ("file.web2.wechat.com", "webpush.web2.wechat.com")),
                ("wechat.com", ("file.web.wechat.com", "webpush.web.wechat.com"))):
            fileUrl, syncUrl = ['https://%s/cgi-bin/mmwebwx-bin' % url for url in detailedUrl]
            if indexUrl in self.core.loginInfo['url']:
                self.core.loginInfo['fileUrl'], self.core.loginInfo['syncUrl'] = fileUrl, syncUrl
                break
        else:
            self.core.loginInfo['fileUrl'] = self.core.loginInfo['syncUrl'] = self.core.loginInfo['url']
        self.core.loginInfo['deviceid'] = 'e' + repr(random.random())[2:17]
        self.core.loginInfo['logintime'] = int(time.time() * 1e3)
        self.core.loginInfo['BaseRequest'] = {}
        cookies = self.core.s.cookies.get_dict()
        res = re.findall('<skey>(.*?)</skey>', r.text, re.S)
        skey = res[0] if res else None
        res = re.findall('<pass_ticket>(.*?)</pass_ticket>', r.text, re.S)
        pass_ticket = res[0] if res else None
        if skey is not None:
            self.core.loginInfo['skey'] = self.core.loginInfo['BaseRequest']['Skey'] = skey
        self.core.loginInfo['wxsid'] = self.core.loginInfo['BaseRequest']['Sid'] = cookies["wxsid"]
        self.core.loginInfo['wxuin'] = self.core.loginInfo['BaseRequest']['Uin'] = cookies["wxuin"]
        if pass_ticket is not None:
            self.core.loginInfo['pass_ticket'] = pass_ticket
        if not all([key in self.core.loginInfo for key in ('skey', 'wxsid', 'wxuin', 'pass_ticket')]):
            logger.error(
                'Your wechat account may be LIMITED to log in WEB wechat, error info:\n%s' % r.text)
            self.core.isLogging = False
            return False
        return True

    def web_init(self):
        url = '%s/webwxinit' % self.core.loginInfo['url']
        params = {
            'r': int(-time.time() / 1579),
            'pass_ticket': self.core.loginInfo['pass_ticket']}
        data = {'BaseRequest': self.core.loginInfo['BaseRequest']}
        headers = {
            'ContentType': 'application/json; charset=UTF-8',
            'User-Agent': config.USER_AGENT}
        r = self.core.s.post(url, params=params, data=json.dumps(data), headers=headers)
        dic = json.loads(r.content.decode('utf-8', 'replace'))
        utils.emoji_formatter(dic['User'], 'NickName')
        self.core.loginInfo['InviteStartCount'] = int(dic['InviteStartCount'])
        self.core.loginInfo['User'] = wrap_user_dict(
            utils.struct_friend_info(dic['User']))
        self.core.memberList.append(self.core.loginInfo['User'])
        self.core.loginInfo['SyncKey'] = dic['SyncKey']
        self.core.loginInfo['synckey'] = '|'.join(['%s_%s' % (item['Key'], item['Val'])
                                                   for item in dic['SyncKey']['List']])
        self.core.storageClass.userName = dic['User']['UserName']
        self.core.storageClass.nickName = dic['User']['NickName']
        contactList = dic.get('ContactList', [])
        chatroomList, otherList = [], []
        for m in contactList:
            if m['Sex'] != 0:
                otherList.append(m)
            elif '@@' in m['UserName']:
                m['MemberList'] = []
                chatroomList.append(m)
            elif '@' in m['UserName']:
                otherList.append(m)
        if chatroomList:
            self.contact_massager.update_local_chatrooms(self.core, chatroomList)
        if otherList:
            self.contact_massager.update_local_friends(self.core, otherList)
        return dic

    def show_mobile_login(self):
        url = '%s/webwxstatusnotify?lang=zh_CN&pass_ticket=%s' % (
            self.core.loginInfo['url'], self.core.loginInfo['pass_ticket'])
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Code': 3,
            'FromUserName': self.core.storageClass.userName,
            'ToUserName': self.core.storageClass.userName,
            'ClientMsgId': int(time.time())}
        headers = {
            'ContentType': 'application/json; charset=UTF-8',
            'User-Agent': config.USER_AGENT}
        r = self.core.s.post(url, data=json.dumps(data), headers=headers)
        return ReturnValue(rawResponse=r)

    def start_receiving(self, exitCallback=None, getReceivingFnOnly=False):
        self.core.alive = True

        def maintain_loop():
            retryCount = 0
            while self.core.alive:
                try:
                    i = self.sync_check()
                    if i is None:
                        self.core.alive = False
                    elif i == '0':
                        pass
                    else:
                        msgList, contactList = self.core.get_msg()
                        if msgList:
                            msgList = self.message_massager.produce_msg(self.core, msgList)
                            for msg in msgList:
                                self.core.msgList.put(msg)
                        if contactList:
                            chatroomList, otherList = [], []
                            for contact in contactList:
                                if '@@' in contact['UserName']:
                                    chatroomList.append(contact)
                                else:
                                    otherList.append(contact)
                            chatroomMsg = self.contact_massager.update_local_chatrooms(self.core, chatroomList)
                            chatroomMsg['User'] = self.core.loginInfo['User']
                            self.core.msgList.put(chatroomMsg)
                            self.contact_massager.update_local_friends(self.core, otherList)
                    retryCount = 0
                except requests.exceptions.ReadTimeout:
                    pass
                except:
                    retryCount += 1
                    logger.error(traceback.format_exc())
                    if self.core.receivingRetryCount < retryCount:
                        logger.error("Having tried %s times, but still failed. " % (
                            retryCount) + "Stop trying...")
                        self.core.alive = False
                    else:
                        time.sleep(1)
            self.core.logout()
            if callable(exitCallback):
                exitCallback()
            else:
                logger.info('LOG OUT!')

        if getReceivingFnOnly:
            return maintain_loop
        else:
            maintainThread = threading.Thread(target=maintain_loop)
            maintainThread.setDaemon(True)
            maintainThread.start()

    def sync_check(self):
        url = '%s/synccheck' % self.core.loginInfo.get('syncUrl', self.core.loginInfo['url'])
        params = {
            'r': int(time.time() * 1000),
            'skey': self.core.loginInfo['skey'],
            'sid': self.core.loginInfo['wxsid'],
            'uin': self.core.loginInfo['wxuin'],
            'deviceid': self.core.loginInfo['deviceid'],
            'synckey': self.core.loginInfo['synckey'],
            '_': self.core.loginInfo['logintime']}
        headers = {'User-Agent': config.USER_AGENT}
        self.core.loginInfo['logintime'] += 1
        try:
            r = self.core.s.get(url, params=params, headers=headers,
                                timeout=config.TIMEOUT)
        except requests.exceptions.ConnectionError as e:
            try:
                if not isinstance(e.args[0].args[1], BadStatusLine):
                    raise
                return '2'
            except:
                raise
        r.raise_for_status()
        regx = r'window.synccheck={retcode:"(\d+)",selector:"(\d+)"}'
        pm = re.search(regx, r.text)
        if pm is None or pm.group(1) != '0':
            logger.error('Unexpected sync check result: %s' % r.text)
            return None
        return pm.group(2)

    def get_msg(self):
        self.core.loginInfo['deviceid'] = 'e' + repr(random.random())[2:17]
        url = '%s/webwxsync?sid=%s&skey=%s&pass_ticket=%s' % (
            self.core.loginInfo['url'], self.core.loginInfo['wxsid'],
            self.core.loginInfo['skey'], self.core.loginInfo['pass_ticket'])
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'SyncKey': self.core.loginInfo['SyncKey'],
            'rr': ~int(time.time())}
        headers = {
            'ContentType': 'application/json; charset=UTF-8',
            'User-Agent': config.USER_AGENT}
        r = self.core.s.post(url, data=json.dumps(data),
                             headers=headers, timeout=config.TIMEOUT)
        dic = json.loads(r.content.decode('utf-8', 'replace'))
        if dic['BaseResponse']['Ret'] != 0:
            return None, None
        self.core.loginInfo['SyncKey'] = dic['SyncKey']
        self.core.loginInfo['synckey'] = '|'.join(['%s_%s' % (item['Key'], item['Val'])
                                                   for item in dic['SyncCheckKey']['List']])
        return dic['AddMsgList'], dic['ModContactList']

    def logout(self):
        if self.core.alive:
            url = '%s/webwxlogout' % self.core.loginInfo['url']
            params = {
                'redirect': 1,
                'type': 1,
                'skey': self.core.loginInfo['skey']}
            headers = {'User-Agent': config.USER_AGENT}
            self.core.s.get(url, params=params, headers=headers)
            self.core.alive = False
        self.core.isLogging = False
        self.core.s.cookies.clear()
        del self.core.chatroomList[:]
        del self.core.memberList[:]
        del self.core.mpList[:]
        return ReturnValue({'BaseResponse': {
            'ErrMsg': 'logout successfully.',
            'Ret': 0}})


def load_login(core):
    LoginManager(core)
