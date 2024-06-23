import requests

from . import storage


class Core(object):
    def __init__(self):
        ''' Initialize the Core object '''
        self.exitCallback = None
        self.alive = False
        self.isLogging = False
        self.storageClass = storage.Storage(self)
        self.memberList = self.storageClass.memberList
        self.mpList = self.storageClass.mpList
        self.chatroomList = self.storageClass.chatroomList
        self.msgList = self.storageClass.msgList
        self.loginInfo = {}
        self.s = requests.Session()
        self.uuid = None
        self.functionDict = {'FriendChat': {}, 'GroupChat': {}, 'MpChat': {}}
        self.useHotReload = False
        self.hotReloadDir = 'itchat.pkl'
        self.receivingRetryCount = 5

    def login(self, enableCmdQR=False, picDir=None, qrCallback=None,
              loginCallback=None, exitCallback=None):
        ''' Log in like web wechat does '''
        self.get_QRuuid()
        self.get_QR()
        status = self.check_login()
        if exitCallback:
            self.exitCallback = exitCallback
        if status == '200':
            self.alive = True
            if loginCallback:
                loginCallback()
        else:
            raise RuntimeError(f"Failed to log in with status {status}")

    def get_QRuuid(self):
        ''' Get uuid for qrcode '''
        # Placeholder for getting UUID logic
        self.uuid = 'mock_uuid'

    def get_QR(self, uuid=None, enableCmdQR=False, picDir=None, qrCallback=None):
        ''' Download and show qrcode '''
        # Placeholder for downloading QR code logic
        print("Mock QR code downloaded")

    def check_login(self, uuid=None):
        ''' Check login status '''
        # Placeholder for checking login status logic
        return '200'  # Mock successful login status

    def logout(self):
        ''' Logout '''
        if self.alive:
            # Placeholder for logout logic
            self.alive = False
            self.isLogging = False
            if self.exitCallback:
                self.exitCallback()

    # Other methods such as `web_init`, `start_receiving`, `get_msg`, etc. would follow a similar structure of implementation.

    def send_msg(self, msg='Test Message', toUserName=None):
        ''' Send plain text message '''
        if not self.alive:
            raise RuntimeError("You need to log in first")
        # Placeholder for sending message logic
        print(f"Message '{msg}' sent to {toUserName}")

    # More methods need to be implemented similarly for full functionality.

    def search_friends(self, name=None, userName=None, remarkName=None, nickName=None,
                       wechatAccount=None):
        ''' Search for friends '''
        return self.storageClass.search_friends(name, userName, remarkName,
                                                nickName, wechatAccount)

    def search_chatrooms(self, name=None, userName=None):
        ''' Search for chatrooms '''
        return self.storageClass.search_chatrooms(name, userName)

    def search_mps(self, name=None, userName=None):
        ''' Search for massive platforms '''
        return self.storageClass.search_mps(name, userName)
