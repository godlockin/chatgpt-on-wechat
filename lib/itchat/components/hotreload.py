import logging
import os
import pickle

import requests

from .contact import ContactManager
from .messages import MessageManager
from ..config import (
    VERSION,
    USER_AGENT,
)
from ..returnvalues import ReturnValue
from ..storage import templates

logger = logging.getLogger('itchat')

COMMON_HEADERS = {
    'ContentType': 'application/json; charset=UTF-8',
    'User-Agent': USER_AGENT
}


class HotReloadManager:
    def __init__(self, core):
        self.core = core
        self.contact_massager = ContactManager(core)
        self.message_massager = MessageManager(core)
        self.core.dump_login_status = self.dump_login_status
        self.core.load_login_status = self.load_login_status

    def dump_login_status(self, fileDir=None):
        fileDir = fileDir or self.core.hotReloadDir
        try:
            with open(fileDir, 'w') as f:
                f.write('itchat - DELETE THIS')
            os.remove(fileDir)
        except Exception as e:
            raise Exception('Incorrect fileDir') from e
        status = {
            'version': VERSION,
            'loginInfo': self.core.loginInfo,
            'cookies': self.core.s.cookies.get_dict(),
            'storage': self.core.storageClass.dumps()
        }
        with open(fileDir, 'wb') as f:
            pickle.dump(status, f)
        logger.debug('Dump login status for hot reload successfully.')

    def load_login_status(self, fileDir, loginCallback=None, exitCallback=None):
        try:
            with open(fileDir, 'rb') as f:
                j = pickle.load(f)
        except Exception as e:
            logger.debug('No such file, loading login status failed.')
            return ReturnValue({'BaseResponse': {
                'ErrMsg': 'No such file, loading login status failed.',
                'Ret': -1002,
            }})

        if j.get('version', '') != VERSION:
            logger.debug(('you have updated itchat from %s to %s, ' +
                          'so cached status is ignored') % (
                             j.get('version', 'old version'), VERSION))
            return ReturnValue({'BaseResponse': {
                'ErrMsg': 'cached status ignored because of version',
                'Ret': -1005,
            }})

        self._restore_login_status(j)

        try:
            msgList, contactList = self.core.get_msg()
        except:
            msgList = contactList = None

        if (msgList or contactList) is None:
            self.core.logout()
            self.load_last_login_status(self.core.s, j['cookies'])
            logger.debug('server refused, loading login status failed.')
            return ReturnValue({'BaseResponse': {
                'ErrMsg': 'server refused, loading login status failed.',
                'Ret': -1003,
            }})
        else:
            self._update_local_data(contactList, msgList)
            self.core.start_receiving(exitCallback)
            logger.debug('loading login status succeeded.')
            if callable(loginCallback):
                loginCallback()
            return ReturnValue({'BaseResponse': {
                'ErrMsg': 'loading login status succeeded.',
                'Ret': 0,
            }})

    def _restore_login_status(self, j):
        self.core.loginInfo = j['loginInfo']
        self.core.loginInfo['User'] = templates.User(self.core.loginInfo['User'])
        self.core.loginInfo['User'].core = self.core
        self.core.s.cookies = requests.utils.cookiejar_from_dict(j['cookies'])
        self.core.storageClass.loads(j['storage'])

    def _update_local_data(self, contactList, msgList):
        if contactList:
            for contact in contactList:
                if '@@' in contact['UserName']:
                    self.contact_massager.update_local_chatrooms(self.core, [contact])
                else:
                    self.contact_massager.update_local_friends(self.core, [contact])
        if msgList:
            msgList = self.message_massager.produce_msg(self.core, msgList)
            for msg in msgList:
                self.core.msgList.put(msg)

    def load_last_login_status(self, session, cookiesDict):
        try:
            session.cookies = requests.utils.cookiejar_from_dict({
                'webwxuvid': cookiesDict['webwxuvid'],
                'webwx_auth_ticket': cookiesDict['webwx_auth_ticket'],
                'login_frequency': '2',
                'last_wxuin': cookiesDict['wxuin'],
                'wxloadtime': cookiesDict['wxloadtime'] + '_expired',
                'wxpluginkey': cookiesDict['wxloadtime'],
                'wxuin': cookiesDict['wxuin'],
                'mm_lang': 'zh_CN',
                'MM_WX_NOTIFY_STATE': '1',
                'MM_WX_SOUND_STATE': '1',
            })
        except Exception as e:
            logger.info('Load status for push login failed, we may have experienced a cookies change.')
            logger.info('If you are using the newest version of itchat, you may report a bug.')


def load_hotreload(core):
    return HotReloadManager(core)
