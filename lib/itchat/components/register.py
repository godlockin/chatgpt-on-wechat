import logging
import sys
import threading
import traceback

try:
    import Queue
except ImportError:
    import queue as Queue

from ..log import set_logging
from ..utils import test_connect
from ..storage import templates

logger = logging.getLogger('itchat')


class RegisterManager:
    def __init__(self, core):
        self.core = core
        core.auto_login = self.auto_login
        core.configured_reply = self.configured_reply
        core.msg_register = self.msg_register
        core.run = self.run

    def auto_login(self, hotReload=False, statusStorageDir='itchat.pkl',
                   enableCmdQR=False, picDir=None, qrCallback=None,
                   loginCallback=None, exitCallback=None):
        if not test_connect():
            logger.info("You can't get access to internet or wechat domain, so exit.")
            sys.exit()
        self.core.useHotReload = hotReload
        self.core.hotReloadDir = statusStorageDir
        if hotReload:
            rval = self.core.load_login_status(statusStorageDir,
                                               loginCallback=loginCallback, exitCallback=exitCallback)
            if rval:
                return
            logger.error('Hot reload failed, logging in normally, error={}'.format(rval))
            self.core.logout()
            self.core.login(enableCmdQR=enableCmdQR, picDir=picDir, qrCallback=qrCallback,
                            loginCallback=loginCallback, exitCallback=exitCallback)
            self.core.dump_login_status(statusStorageDir)
        else:
            self.core.login(enableCmdQR=enableCmdQR, picDir=picDir, qrCallback=qrCallback,
                            loginCallback=loginCallback, exitCallback=exitCallback)

    def configured_reply(self):
        ''' determine the type of message and reply if its method is defined '''
        try:
            msg = self.core.msgList.get(timeout=1)
        except Queue.Empty:
            pass
        else:
            if isinstance(msg['User'], templates.User):
                replyFn = self.core.functionDict['FriendChat'].get(msg['Type'])
            elif isinstance(msg['User'], templates.MassivePlatform):
                replyFn = self.core.functionDict['MpChat'].get(msg['Type'])
            elif isinstance(msg['User'], templates.Chatroom):
                replyFn = self.core.functionDict['GroupChat'].get(msg['Type'])
            else:
                replyFn = None
            if replyFn is not None:
                try:
                    r = replyFn(msg)
                    if r is not None:
                        self.core.send(r, msg.get('FromUserName'))
                except:
                    logger.warning(traceback.format_exc())

    def msg_register(self, msgType, isFriendChat=False, isGroupChat=False, isMpChat=False):
        ''' a decorator constructor '''
        if not (isinstance(msgType, list) or isinstance(msgType, tuple)):
            msgType = [msgType]

        def _msg_register(fn):
            for _msgType in msgType:
                if isFriendChat:
                    self.core.functionDict['FriendChat'][_msgType] = fn
                if isGroupChat:
                    self.core.functionDict['GroupChat'][_msgType] = fn
                if isMpChat:
                    self.core.functionDict['MpChat'][_msgType] = fn
                if not any((isFriendChat, isGroupChat, isMpChat)):
                    self.core.functionDict['FriendChat'][_msgType] = fn
            return fn

        return _msg_register

    def run(self, debug=False, blockThread=True):
        logger.info('Start auto replying.')
        if debug:
            set_logging(loggingLevel=logging.DEBUG)

        def reply_fn():
            try:
                while self.core.alive:
                    self.configured_reply()
            except KeyboardInterrupt:
                if self.core.useHotReload:
                    self.core.dump_login_status()
                self.core.alive = False
                logger.debug('itchat received an ^C and exit.')
                logger.info('Bye~')

        if blockThread:
            reply_fn()
        else:
            replyThread = threading.Thread(target=reply_fn)
            replyThread.setDaemon(True)
            replyThread.start()


def load_register(core):
    RegisterManager(core)
