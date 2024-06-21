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

# 公共变量
COMMON_HEADERS = {
    'ContentType': 'application/json; charset=UTF-8',
    'User-Agent': config.USER_AGENT
}

def load_contact(core):
    core.update_chatroom = update_chatroom
    core.update_friend = update_friend
    core.get_contact = get_contact
    core.get_friends = get_friends
    core.get_chatrooms = get_chatrooms
    core.get_mps = get_mps
    core.set_alias = set_alias
    core.set_pinned = set_pinned
    core.accept_friend = accept_friend
    core.get_head_img = get_head_img
    core.create_chatroom = create_chatroom
    core.set_chatroom_name = set_chatroom_name
    core.delete_member_from_chatroom = delete_member_from_chatroom
    core.add_member_into_chatroom = add_member_into_chatroom

def fetch_contacts(self, user_names, detailed_member=False):
    if not isinstance(user_names, list):
        user_names = [user_names]
    url = f"{self.loginInfo['url']}/webwxbatchgetcontact?type=ex&r={int(time.time())}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'Count': len(user_names),
        'List': [{'UserName': u, 'ChatRoomId': ''} for u in user_names]
    }
    response = self.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS).content.decode('utf8', 'replace')
    contact_list = json.loads(response).get('ContactList')

    if not contact_list:
        return ReturnValue({'BaseResponse': {'ErrMsg': 'No contact found', 'Ret': -1001}})

    if detailed_member:
        contact_list = get_detailed_member_info(self, contact_list)

    return contact_list

def get_detailed_member_info(self, chatroom_list):
    def fetch_detailed_member_info(encry_chatroom_id, member_list):
        url = f"{self.loginInfo['url']}/webwxbatchgetcontact?type=ex&r={int(time.time())}"
        data = {
            'BaseRequest': self.loginInfo['BaseRequest'],
            'Count': len(member_list),
            'List': [{'UserName': member['UserName'], 'EncryChatRoomId': encry_chatroom_id} for member in member_list]
        }
        response = self.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS).content.decode('utf8', 'replace')
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
    chatroom_list = fetch_contacts(self, user_names, detailed_member)
    update_local_chatrooms(self, chatroom_list)
    results = [self.storageClass.search_chatrooms(userName=chatroom['UserName']) for chatroom in chatroom_list]
    return results if len(results) > 1 else results[0]

def update_friend(self, user_names):
    friend_list = fetch_contacts(self, user_names)
    update_local_friends(self, friend_list)
    results = [self.storageClass.search_friends(userName=friend['UserName']) for friend in friend_list]
    return results if len(results) != 1 else results[0]

@contact_change
def update_local_chatrooms(core, chatrooms):
    for chatroom in chatrooms:
        format_chatroom_members(chatroom)
        old_chatroom = utils.search_dict_list(core.chatroomList, 'UserName', chatroom['UserName'])
        if old_chatroom:
            update_info_dict(old_chatroom, chatroom)
            update_chatroom_members(old_chatroom, chatroom['MemberList'])
        else:
            core.chatroomList.append(chatroom)
        update_owner_and_admin_status(core, old_chatroom or chatroom)
        update_self_info(core, old_chatroom or chatroom)

    return {
        'Type': 'System',
        'Text': [chatroom['UserName'] for chatroom in chatrooms],
        'SystemInfo': 'chatrooms',
        'FromUserName': core.storageClass.userName,
        'ToUserName': core.storageClass.userName,
    }

def format_chatroom_members(chatroom):
    utils.emoji_formatter(chatroom, 'NickName')
    for member in chatroom['MemberList']:
        for key in ['NickName', 'DisplayName', 'RemarkName']:
            if key in member:
                utils.emoji_formatter(member, key)

def update_chatroom_members(old_chatroom, new_member_list):
    old_member_list = old_chatroom['MemberList']
    for member in new_member_list:
        old_member = utils.search_dict_list(old_member_list, 'UserName', member['UserName'])
        if old_member:
            update_info_dict(old_member, member)
        else:
            old_member_list.append(member)

    if len(new_member_list) != len(old_member_list):
        existing_user_names = [member['UserName'] for member in new_member_list]
        old_chatroom['MemberList'] = [member for member in old_member_list if member['UserName'] in existing_user_names]

def update_owner_and_admin_status(core, chatroom):
    if 'ChatRoomOwner' in chatroom:
        owner = utils.search_dict_list(chatroom['MemberList'], 'UserName', chatroom['ChatRoomOwner'])
        chatroom['OwnerUin'] = owner.get('Uin', 0) if owner else 0
        chatroom['IsAdmin'] = chatroom['OwnerUin'] == int(core.loginInfo['wxuin'])
    else:
        chatroom['IsAdmin'] = None

def update_self_info(core, chatroom):
    new_self = utils.search_dict_list(chatroom['MemberList'], 'UserName', core.storageClass.userName)
    chatroom['Self'] = new_self or copy.deepcopy(core.loginInfo['User'])

@contact_change
def update_local_friends(core, friends):
    for friend in friends:
        format_friend_info(friend)
        old_info = utils.search_dict_list(core.memberList + core.mpList, 'UserName', friend['UserName'])
        if old_info is None:
            old_info = copy.deepcopy(friend)
            if old_info['VerifyFlag'] & 8 == 0:
                core.memberList.append(old_info)
            else:
                core.mpList.append(old_info)
        else:
            update_info_dict(old_info, friend)

def format_friend_info(friend):
    for key in ['NickName', 'DisplayName', 'RemarkName']:
        if key in friend:
            utils.emoji_formatter(friend, key)

@contact_change
def update_local_uin(core, msg):
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
                full_contact = core.memberList + core.chatroomList + core.mpList
                user_dict = utils.search_dict_list(full_contact, 'UserName', username)
                if user_dict:
                    if user_dict.get('Uin', 0) == 0:
                        user_dict['Uin'] = uin
                        username_changed_list.append(username)
                        logger.debug('Uin fetched: %s, %s' % (username, uin))
                    elif user_dict['Uin'] != uin:
                        logger.debug('Uin changed: %s, %s' % (user_dict['Uin'], uin))
                else:
                    add_user_by_type(core, username, uin)
                    username_changed_list.append(username)
                    logger.debug('Uin fetched: %s, %s' % (username, uin))
        else:
            logger.debug('Wrong length of uins & usernames: %s, %s' % (len(uins), len(usernames)))
    else:
        logger.debug('No uins in 51 message')
        logger.debug(msg['Content'])

    return r

def add_user_by_type(core, username, uin):
    if '@@' in username:
        core.storageClass.updateLock.release()
        update_chatroom(core, username)
        core.storageClass.updateLock.acquire()
        new_chatroom = utils.search_dict_list(core.chatroomList, 'UserName', username) or {
            'UserName': username, 'Uin': uin, 'Self': copy.deepcopy(core.loginInfo['User'])
        }
        core.chatroomList.append(new_chatroom)
    elif '@' in username:
        core.storageClass.updateLock.release()
        update_friend(core, username)
        core.storageClass.updateLock.acquire()
        new_friend = utils.search_dict_list(core.memberList, 'UserName', username) or {
            'UserName': username, 'Uin': uin
        }
        core.memberList.append(new_friend)

def get_contact(self, update=False):
    if not update:
        return utils.contact_deep_copy(self, self.chatroomList)

    def fetch_contact(seq=0):
        url = f"{self.loginInfo['url']}/webwxgetcontact?r={int(time.time())}&seq={seq}&skey={self.loginInfo['skey']}"
        try:
            response = self.s.get(url, headers=COMMON_HEADERS)
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
        update_local_chatrooms(self, chatroom_list)
    if other_list:
        update_local_friends(self, other_list)
    return utils.contact_deep_copy(self, chatroom_list)

def get_friends(self, update=False):
    if update:
        self.get_contact(update=True)
    return utils.contact_deep_copy(self, self.memberList)

def get_chatrooms(self, update=False, contact_only=False):
    if contact_only:
        return self.get_contact(update=True)
    else:
        if update:
            self.get_contact(True)
        return utils.contact_deep_copy(self, self.chatroomList)

def get_mps(self, update=False):
    if update:
        self.get_contact(update=True)
    return utils.contact_deep_copy(self, self.mpList)

def set_alias(self, user_name, alias):
    old_friend_info = utils.search_dict_list(self.memberList, 'UserName', user_name)
    if old_friend_info is None:
        return ReturnValue({'BaseResponse': {'Ret': -1001}})
    url = f"{self.loginInfo['url']}/webwxoplog?lang=zh_CN&pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'UserName': user_name,
        'CmdId': 2,
        'RemarkName': alias,
        'BaseRequest': self.loginInfo['BaseRequest']
    }
    response = self.s.post(url, json.dumps(data, ensure_ascii=False).encode('utf8'), headers=COMMON_HEADERS)
    result = ReturnValue(rawResponse=response)
    if result:
        old_friend_info['RemarkName'] = alias
    return result

def set_pinned(self, user_name, is_pinned=True):
    url = f"{self.loginInfo['url']}/webwxoplog?pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'UserName': user_name,
        'CmdId': 3,
        'OP': int(is_pinned),
        'BaseRequest': self.loginInfo['BaseRequest']
    }
    response = self.s.post(url, json=data, headers=COMMON_HEADERS)
    return ReturnValue(rawResponse=response)

def accept_friend(self, user_name, v4='', auto_update=True):
    url = f"{self.loginInfo['url']}/webwxverifyuser?r={int(time.time())}&pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'Opcode': 3,
        'VerifyUserListSize': 1,
        'VerifyUserList': [{'Value': user_name, 'VerifyUserTicket': v4}],
        'VerifyContent': '',
        'SceneListCount': 1,
        'SceneList': [33],
        'skey': self.loginInfo['skey']
    }
    response = self.s.post(url, headers=COMMON_HEADERS, data=json.dumps(data, ensure_ascii=False).encode('utf8', 'replace'))
    if auto_update:
        self.update_friend(user_name)
    return ReturnValue(rawResponse=response)

def get_head_img(self, user_name=None, chatroom_user_name=None, pic_dir=None):
    params = {
        'userName': user_name or chatroom_user_name or self.storageClass.userName,
        'skey': self.loginInfo['skey'],
        'type': 'big'
    }
    url = f"{self.loginInfo['url']}/webwxgeticon"
    if chatroom_user_name is None:
        info_dict = self.storageClass.search_friends(userName=user_name)
        if info_dict is None:
            return ReturnValue({'BaseResponse': {'ErrMsg': 'No friend found', 'Ret': -1001}})
    else:
        if user_name is None:
            url = f"{self.loginInfo['url']}/webwxgetheadimg"
        else:
            chatroom = self.storageClass.search_chatrooms(userName=chatroom_user_name)
            if chatroom is None:
                return ReturnValue({'BaseResponse': {'ErrMsg': 'No chatroom found', 'Ret': -1001}})
            if 'EncryChatRoomId' in chatroom:
                params['chatroomid'] = chatroom['EncryChatRoomId']
            params['chatroomid'] = params.get('chatroomid') or chatroom['UserName']
    response = self.s.get(url, params=params, stream=True, headers=COMMON_HEADERS)
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
    url = f"{self.loginInfo['url']}/webwxcreatechatroom?pass_ticket={self.loginInfo['pass_ticket']}&r={int(time.time())}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'MemberCount': len(member_list.split(',')),
        'MemberList': [{'UserName': member} for member in member_list.split(',')],
        'Topic': topic
    }
    response = self.s.post(url, headers=COMMON_HEADERS, data=json.dumps(data, ensure_ascii=False).encode('utf8', 'ignore'))
    return ReturnValue(rawResponse=response)

def set_chatroom_name(self, chatroom_user_name, name):
    url = f"{self.loginInfo['url']}/webwxupdatechatroom?fun=modtopic&pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'ChatRoomName': chatroom_user_name,
        'NewTopic': name
    }
    response = self.s.post(url, headers=COMMON_HEADERS, data=json.dumps(data, ensure_ascii=False).encode('utf8', 'ignore'))
    return ReturnValue(rawResponse=response)

def delete_member_from_chatroom(self, chatroom_user_name, member_list):
    url = f"{self.loginInfo['url']}/webwxupdatechatroom?fun=delmember&pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'ChatRoomName': chatroom_user_name,
        'DelMemberList': ','.join([member['UserName'] for member in member_list])
    }
    response = self.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS)
    return ReturnValue(rawResponse=response)

def add_member_into_chatroom(self, chatroom_user_name, member_list, use_invitation=False):
    chatroom = self.storageClass.search_chatrooms(userName=chatroom_user_name) or self.update_chatroom(chatroom_user_name)
    if not use_invitation and len(chatroom['MemberList']) > self.loginInfo['InviteStartCount']:
        use_invitation = True
    fun, member_key_name = ('invitemember', 'InviteMemberList') if use_invitation else ('addmember', 'AddMemberList')
    url = f"{self.loginInfo['url']}/webwxupdatechatroom?fun={fun}&pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'ChatRoomName': chatroom_user_name,
        member_key_name: member_list
    }
    response = self.s.post(url, data=json.dumps(data), headers=COMMON_HEADERS)
    return ReturnValue(rawResponse=response)
