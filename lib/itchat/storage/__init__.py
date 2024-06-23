import os
import time
import copy
from threading import Lock
from .messagequeue import Queue
from .templates import (
    ContactList, User, MassivePlatform, Chatroom
)

def contact_change(fn):
    def _contact_change(core, *args, **kwargs):
        with core.storageClass.updateLock:
            return fn(core, *args, **kwargs)
    return _contact_change

class Storage:
    def __init__(self, core):
        self.userName = None
        self.nickName = None
        self.updateLock = Lock()
        self.memberList = self._init_contact_list(core, User)
        self.mpList = self._init_contact_list(core, MassivePlatform)
        self.chatroomList = self._init_contact_list(core, Chatroom)
        self.msgList = Queue(-1)
        self.lastInputUserName = None

    @staticmethod
    def _init_contact_list(core, contact_class):
        contact_list = ContactList()
        contact_list.set_default_value(contactClass=contact_class)
        contact_list.core = core
        return contact_list

    def dumps(self):
        return {
            'userName': self.userName,
            'nickName': self.nickName,
            'memberList': self.memberList,
            'mpList': self.mpList,
            'chatroomList': self.chatroomList,
            'lastInputUserName': self.lastInputUserName,
        }

    def loads(self, j):
        self.userName = j.get('userName')
        self.nickName = j.get('nickName')
        self._load_contact_list(self.memberList, j.get('memberList', []))
        self._load_contact_list(self.mpList, j.get('mpList', []))
        self._load_contact_list(self.chatroomList, j.get('chatroomList', []))
        self.lastInputUserName = j.get('lastInputUserName')

    def _load_contact_list(self, contact_list, data):
        del contact_list[:]
        for item in data:
            contact_list.append(item)
        for chatroom in self.chatroomList:
            self._set_chatroom_members_core(chatroom)

    def _set_chatroom_members_core(self, chatroom):
        if 'MemberList' in chatroom:
            for member in chatroom['MemberList']:
                member.core = chatroom.core
                member.chatroom = chatroom
        if 'Self' in chatroom:
            chatroom['Self'].core = chatroom.core
            chatroom['Self'].chatroom = chatroom

    def search_friends(self, name=None, userName=None, remarkName=None, nickName=None, wechatAccount=None):
        with self.updateLock:
            if not any([name, userName, remarkName, nickName, wechatAccount]):
                return copy.deepcopy(self.memberList[0])  # my own account
            elif userName:
                return self._search_by_userName(self.memberList, userName)
            return self._search_contacts(self.memberList, name, remarkName, nickName, wechatAccount)

    def search_chatrooms(self, name=None, userName=None):
        with self.updateLock:
            if userName:
                return self._search_by_userName(self.chatroomList, userName)
            return self._search_by_name(self.chatroomList, name)

    def search_mps(self, name=None, userName=None):
        with self.updateLock:
            if userName:
                return self._search_by_userName(self.mpList, userName)
            return self._search_by_name(self.mpList, name)

    def _search_by_userName(self, contact_list, userName):
        for contact in contact_list:
            if contact['UserName'] == userName:
                return copy.deepcopy(contact)

    def _search_by_name(self, contact_list, name):
        return [copy.deepcopy(contact) for contact in contact_list if name in contact['NickName']]

    def _search_contacts(self, contact_list, name, remarkName, nickName, wechatAccount):
        matchDict = {'RemarkName': remarkName, 'NickName': nickName, 'Alias': wechatAccount}
        matchDict = {k: v for k, v in matchDict.items() if v}
        contact = [contact for contact in contact_list if any(contact.get(k) == name for k in matchDict.keys())] if name else contact_list[:]
        return [copy.deepcopy(contact) for contact in contact if all(contact.get(k) == v for k, v in matchDict.items())]
