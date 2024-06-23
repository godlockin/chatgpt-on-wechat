import copy
import io
import json
import logging
import re
import time

from .. import config, utils
from ..returnvalues import ReturnValue
from ..storage import contact_change
from ..utils import update_info_dict

logger = logging.getLogger('itchat')

COMMON_HEADERS = {
    'ContentType': 'application/json; charset=UTF-8',
    'User-Agent': config.USER_AGENT
}


class ContactManager:
    def __init__(self, core):
        self.core = core
        self.core.update_chatroom = self.update_chatroom
        self.core.update_friend = self.update_friend
        self.core.get_contact = self.get_contact
        self.core.get_friends = self.get_friends
        self.core.get_chatrooms = self.get_chatrooms
        self.core.get_mps = self.get_mps
        self.core.set_alias = self.set_alias
        self.core.set_pinned = self.set_pinned
        self.core.accept_friend = self.accept_friend
        self.core.get_head_img = self.get_head_img
        self.core.create_chatroom = self.create_chatroom
        self.core.set_chatroom_name = self.set_chatroom_name
        self.core.delete_member_from_chatroom = self.delete_member_from_chatroom
        self.core.add_member_into_chatroom = self.add_member_into_chatroom

    def fetch_contacts(self, user_names, detailed_member=False):
        user_names = user_names if isinstance(user_names, list) else [user_names]
        url = f"{self.core.loginInfo['url']}/webwxbatchgetcontact?type=ex&r={int(time.time())}"
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Count': len(user_names),
            'List': [{'UserName': u, 'ChatRoomId': ''} for u in user_names]
        }
        response = self.core.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS).content.decode('utf8',
                                                                                                       'replace')
        contact_list = json.loads(response).get('ContactList')

        if not contact_list:
            return ReturnValue({'BaseResponse': {'ErrMsg': 'No contact found', 'Ret': -1001}})

        if detailed_member:
            contact_list = self.get_detailed_member_info(contact_list)

        return contact_list

    def get_detailed_member_info(self, chatroom_list):
        def fetch_detailed_member_info(encry_chatroom_id, member_list):
            url = f"{self.core.loginInfo['url']}/webwxbatchgetcontact?type=ex&r={int(time.time())}"
            data = {
                'BaseRequest': self.core.loginInfo['BaseRequest'],
                'Count': len(member_list),
                'List': [{'UserName': member['UserName'], 'EncryChatRoomId': encry_chatroom_id} for member in
                         member_list]
            }
            response = self.core.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS).content.decode('utf8',
                                                                                                           'replace')
            return json.loads(response)['ContactList']

        MAX_GET_NUMBER = 50
        for chatroom in chatroom_list:
            total_member_list = []
            for i in range(0, len(chatroom['MemberList']), MAX_GET_NUMBER):
                member_list = chatroom['MemberList'][i:i + MAX_GET_NUMBER]
                total_member_list.extend(fetch_detailed_member_info(chatroom['EncryChatRoomId'], member_list))
            chatroom['MemberList'] = total_member_list

        return chatroom_list

    def update_chatroom(self, user_names, detailed_member=False):
        chatroom_list = self.fetch_contacts(user_names, detailed_member)
        self.update_local_chatrooms(chatroom_list)
        results = [self.core.storageClass.search_chatrooms(userName=chatroom['UserName']) for chatroom in chatroom_list]
        return results if len(results) > 1 else results[0]

    def update_friend(self, user_names):
        friend_list = self.fetch_contacts(user_names)
        self.update_local_friends(friend_list)
        results = [self.core.storageClass.search_friends(userName=friend['UserName']) for friend in friend_list]
        return results if len(results) != 1 else results[0]

    @contact_change
    def update_local_chatrooms(self, chatrooms):
        for chatroom in chatrooms:
            self.format_chatroom_members(chatroom)
            old_chatroom = utils.search_dict_list(self.core.chatroomList, 'UserName', chatroom['UserName'])
            if old_chatroom:
                update_info_dict(old_chatroom, chatroom)
                self.update_chatroom_members(old_chatroom, chatroom['MemberList'])
            else:
                self.core.chatroomList.append(chatroom)
            self.update_owner_and_admin_status(old_chatroom or chatroom)
            self.update_self_info(old_chatroom or chatroom)

        return {
            'Type': 'System',
            'Text': [chatroom['UserName'] for chatroom in chatrooms],
            'SystemInfo': 'chatrooms',
            'FromUserName': self.core.storageClass.userName,
            'ToUserName': self.core.storageClass.userName,
        }

    def format_chatroom_members(self, chatroom):
        utils.emoji_formatter(chatroom, 'NickName')
        for member in chatroom['MemberList']:
            for key in ['NickName', 'DisplayName', 'RemarkName']:
                if key in member:
                    utils.emoji_formatter(member, key)

    def update_chatroom_members(self, old_chatroom, new_member_list):
        old_member_list = old_chatroom['MemberList']
        for member in new_member_list:
            old_member = utils.search_dict_list(old_member_list, 'UserName', member['UserName'])
            if old_member:
                update_info_dict(old_member, member)
            else:
                old_member_list.append(member)

        if len(new_member_list) != len(old_member_list):
            existing_user_names = [member['UserName'] for member in new_member_list]
            old_chatroom['MemberList'] = [member for member in old_member_list if
                                          member['UserName'] in existing_user_names]

    def update_owner_and_admin_status(self, chatroom):
        if 'ChatRoomOwner' in chatroom:
            owner = utils.search_dict_list(chatroom['MemberList'], 'UserName', chatroom['ChatRoomOwner'])
            chatroom['OwnerUin'] = owner.get('Uin', 0) if owner else 0
            chatroom['IsAdmin'] = chatroom['OwnerUin'] == int(self.core.loginInfo['wxuin'])
        else:
            chatroom['IsAdmin'] = None

    def update_self_info(self, chatroom):
        new_self = utils.search_dict_list(chatroom['MemberList'], 'UserName', self.core.storageClass.userName)
        chatroom['Self'] = new_self or copy.deepcopy(self.core.loginInfo['User'])

    @contact_change
    def update_local_friends(self, friends):
        for friend in friends:
            self.format_friend_info(friend)
            old_info = utils.search_dict_list(self.core.memberList + self.core.mpList, 'UserName', friend['UserName'])
            if old_info is None:
                old_info = copy.deepcopy(friend)
                if old_info['VerifyFlag'] & 8 == 0:
                    self.core.memberList.append(old_info)
                else:
                    self.core.mpList.append(old_info)
            else:
                update_info_dict(old_info, friend)

    def format_friend_info(self, friend):
        for key in ['NickName', 'DisplayName', 'RemarkName']:
            if key in friend:
                utils.emoji_formatter(friend, key)

    @contact_change
    def update_local_uin(self, msg):
        uins = re.search('<username>([^<]*?)<', msg['Content'])
        username_changed_list = []
        r = {'Type': 'System', 'Text': username_changed_list, 'SystemInfo': 'uins'}

        if uins:
            uins = uins.group(1).split(',')
            usernames = msg['StatusNotifyUserName'].split(',')
            if len(uins) == len(usernames) > 0:
                for uin, username in zip(uins, usernames):
                    if '@' not in username:
                        continue
                    full_contact = self.core.memberList + self.core.chatroomList + self.core.mpList
                    user_dict = utils.search_dict_list(full_contact, 'UserName', username)
                    if user_dict:
                        if user_dict.get('Uin', 0) == 0:
                            user_dict['Uin'] = uin
                            username_changed_list.append(username)
                            logger.debug('Uin fetched: %s, %s' % (username, uin))
                        elif user_dict['Uin'] != uin:
                            logger.debug('Uin changed: %s, %s' % (user_dict['Uin'], uin))
                    else:
                        self.add_user_by_type(username, uin)
                        username_changed_list.append(username)
                        logger.debug('Uin fetched: %s, %s' % (username, uin))
            else:
                logger.debug('Wrong length of uins & usernames: %s, %s' % (len(uins), len(usernames)))
        else:
            logger.debug('No uins in 51 message')
            logger.debug(msg['Content'])

        return r

    def add_user_by_type(self, username, uin):
        if '@@' in username:
            self.core.storageClass.updateLock.release()
            self.update_chatroom(username)
            self.core.storageClass.updateLock.acquire()
            new_chatroom = utils.search_dict_list(self.core.chatroomList, 'UserName', username) or {
                'UserName': username, 'Uin': uin, 'Self': copy.deepcopy(self.core.loginInfo['User'])
            }
            self.core.chatroomList.append(new_chatroom)
        elif '@' in username:
            self.core.storageClass.updateLock.release()
            self.update_friend(username)
            self.core.storageClass.updateLock.acquire()
            new_friend = utils.search_dict_list(self.core.memberList, 'UserName', username) or {
                'UserName': username, 'Uin': uin
            }
            self.core.memberList.append(new_friend)

    def get_contact(self, update=False):
        if not update:
            return utils.contact_deep_copy(self.core, self.core.chatroomList)

        def fetch_contact(seq=0):
            url = f"{self.core.loginInfo['url']}/webwxgetcontact?r={int(time.time())}&seq={seq}&skey={self.core.loginInfo['skey']}"
            try:
                response = self.core.s.get(url, headers=COMMON_HEADERS)
            except:
                logger.info('Failed to fetch contact, possibly due to chatroom amount')
                for chatroom in self.get_chatrooms():
                    self.update_chatroom(chatroom['UserName'], detailedMember=True)
                return 0, []
            json_response = json.loads(response.content.decode('utf-8', 'replace'))
            return json_response.get('Seq', 0), json_response.get('MemberList', [])

        seq, member_list = 0, []
        while True:
            seq, batch_member_list = fetch_contact(seq)
            member_list.extend(batch_member_list)
            if seq == 0:
                break

        chatroom_list, other_list = [], []
        for member in member_list:
            if member['Sex'] != 0:
                other_list.append(member)
            elif '@@' in member['UserName']:
                chatroom_list.append(member)
            else:
                other_list.append(member)

        if chatroom_list:
            self.update_local_chatrooms(chatroom_list)
        if other_list:
            self.update_local_friends(other_list)
        return utils.contact_deep_copy(self.core, chatroom_list)

    def get_friends(self, update=False):
        if update:
            self.get_contact(update=True)
        return utils.contact_deep_copy(self.core, self.core.memberList)

    def get_chatrooms(self, update=False, contact_only=False):
        if contact_only:
            return self.get_contact(update=True)
        else:
            if update:
                self.get_contact(True)
            return utils.contact_deep_copy(self.core, self.core.chatroomList)

    def get_mps(self, update=False):
        if update:
            self.get_contact(update=True)
        return utils.contact_deep_copy(self.core, self.core.mpList)

    def set_alias(self, user_name, alias):
        old_friend_info = utils.search_dict_list(self.core.memberList, 'UserName', user_name)
        if old_friend_info is None:
            return ReturnValue({'BaseResponse': {'Ret': -1001}})
        url = f"{self.core.loginInfo['url']}/webwxoplog?lang=zh_CN&pass_ticket={self.core.loginInfo['pass_ticket']}"
        data = {
            'UserName': user_name,
            'CmdId': 2,
            'RemarkName': alias,
            'BaseRequest': self.core.loginInfo['BaseRequest']
        }
        response = self.core.s.post(url, json.dumps(data, ensure_ascii=False).encode('utf8'), headers=COMMON_HEADERS)
        result = ReturnValue(rawResponse=response)
        if result:
            old_friend_info['RemarkName'] = alias
        return result

    def set_pinned(self, user_name, is_pinned=True):
        url = f"{self.core.loginInfo['url']}/webwxoplog?pass_ticket={self.core.loginInfo['pass_ticket']}"
        data = {
            'UserName': user_name,
            'CmdId': 3,
            'OP': int(is_pinned),
            'BaseRequest': self.core.loginInfo['BaseRequest']
        }
        response = self.core.s.post(url, json=data, headers=COMMON_HEADERS)
        return ReturnValue(rawResponse=response)

    def accept_friend(self, user_name, v4='', auto_update=True):
        url = f"{self.core.loginInfo['url']}/webwxverifyuser?r={int(time.time())}&pass_ticket={self.core.loginInfo['pass_ticket']}"
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Opcode': 3,
            'VerifyUserListSize': 1,
            'VerifyUserList': [{'Value': user_name, 'VerifyUserTicket': v4}],
            'VerifyContent': '',
            'SceneListCount': 1,
            'SceneList': [33],
            'skey': self.core.loginInfo['skey']
        }
        response = self.core.s.post(url, headers=COMMON_HEADERS,
                                    data=json.dumps(data, ensure_ascii=False).encode('utf8', 'replace'))
        if auto_update:
            self.update_friend(user_name)
        return ReturnValue(rawResponse=response)

    def get_head_img(self, user_name=None, chatroom_user_name=None, pic_dir=None):
        params = {
            'userName': user_name or chatroom_user_name or self.core.storageClass.userName,
            'skey': self.core.loginInfo['skey'],
            'type': 'big'
        }
        url = f"{self.core.loginInfo['url']}/webwxgeticon"
        if chatroom_user_name is None:
            info_dict = self.core.storageClass.search_friends(userName=user_name)
            if info_dict is None:
                return ReturnValue({'BaseResponse': {'ErrMsg': 'No friend found', 'Ret': -1001}})
        else:
            if user_name is None:
                url = f"{self.core.loginInfo['url']}/webwxgetheadimg"
            else:
                chatroom = self.core.storageClass.search_chatrooms(userName=chatroom_user_name)
                if chatroom is None:
                    return ReturnValue({'BaseResponse': {'ErrMsg': 'No chatroom found', 'Ret': -1001}})
                if 'EncryChatRoomId' in chatroom:
                    params['chatroomid'] = chatroom['EncryChatRoomId']
                params['chatroomid'] = params.get('chatroomid') or chatroom['UserName']
        response = self.core.s.get(url, params=params, stream=True, headers=COMMON_HEADERS)
        temp_storage = io.BytesIO()
        for block in response.iter_content(1024):
            temp_storage.write(block)
        if pic_dir is None:
            return temp_storage.getvalue()
        with open(pic_dir, 'wb') as f:
            f.write(temp_storage.getvalue())
        temp_storage.seek(0)
        return ReturnValue({'BaseResponse': {'ErrMsg': 'Successfully downloaded', 'Ret': 0},
                            'PostFix': utils.get_image_postfix(temp_storage.read(20))})

    def create_chatroom(self, member_list, topic=''):
        url = f"{self.core.loginInfo['url']}/webwxcreatechatroom?pass_ticket={self.core.loginInfo['pass_ticket']}&r={int(time.time())}"
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'MemberCount': len(member_list.split(',')),
            'MemberList': [{'UserName': member} for member in member_list.split(',')],
            'Topic': topic
        }
        response = self.core.s.post(url, headers=COMMON_HEADERS,
                                    data=json.dumps(data, ensure_ascii=False).encode('utf8', 'ignore'))
        return ReturnValue(rawResponse=response)

    def set_chatroom_name(self, chatroom_user_name, name):
        url = f"{self.core.loginInfo['url']}/webwxupdatechatroom?fun=modtopic&pass_ticket={self.core.loginInfo['pass_ticket']}"
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'ChatRoomName': chatroom_user_name,
            'NewTopic': name
        }
        response = self.core.s.post(url, headers=COMMON_HEADERS,
                                    data=json.dumps(data, ensure_ascii=False).encode('utf8', 'ignore'))
        return ReturnValue(rawResponse=response)

    def delete_member_from_chatroom(self, chatroom_user_name, member_list):
        url = f"{self.core.loginInfo['url']}/webwxupdatechatroom?fun=delmember&pass_ticket={self.core.loginInfo['pass_ticket']}"
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'ChatRoomName': chatroom_user_name,
            'DelMemberList': ','.join([member['UserName'] for member in member_list])
        }
        response = self.core.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS)
        return ReturnValue(rawResponse=response)

    def add_member_into_chatroom(self, chatroom_user_name, member_list, use_invitation=False):
        chatroom = self.core.storageClass.search_chatrooms(userName=chatroom_user_name) or self.update_chatroom(
            chatroom_user_name)
        if not use_invitation and len(chatroom['MemberList']) > self.core.loginInfo['InviteStartCount']:
            use_invitation = True
        fun, member_key_name = ('invitemember', 'InviteMemberList') if use_invitation else (
        'addmember', 'AddMemberList')
        url = f"{self.core.loginInfo['url']}/webwxupdatechatroom?fun={fun}&pass_ticket={self.core.loginInfo['pass_ticket']}"
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'ChatRoomName': chatroom_user_name,
            member_key_name: member_list
        }
        response = self.core.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS)
        return ReturnValue(rawResponse=response)


def load_contact(core):
    return ContactManager(core)
