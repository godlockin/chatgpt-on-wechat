import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import time
from collections import OrderedDict

from .contact import ContactManager
from .. import config, utils
from ..returnvalues import ReturnValue
from ..storage import templates

logger = logging.getLogger('itchat')


class MessageManager:
    def __init__(self, core):
        self.core = core
        core.send_raw_msg = self.send_raw_msg
        core.send_msg = self.send_msg
        core.upload_file = self.upload_file
        core.send_file = self.send_file
        core.send_image = self.send_image
        core.send_video = self.send_video
        core.send = self.send
        core.revoke = self.revoke
        self.contact_massager = ContactManager(core)

    @staticmethod
    def get_download_fn(core, url, msgId):
        def download_fn(downloadDir=None):
            params = {
                'msgid': msgId,
                'skey': core.loginInfo['skey'],
            }
            headers = {'User-Agent': config.USER_AGENT}
            r = core.s.get(url, params=params, stream=True, headers=headers)
            tempStorage = io.BytesIO()
            for block in r.iter_content(1024):
                tempStorage.write(block)
            if downloadDir is None:
                return tempStorage.getvalue()
            with open(downloadDir, 'wb') as f:
                f.write(tempStorage.getvalue())
            tempStorage.seek(0)
            return ReturnValue({
                'BaseResponse': {'ErrMsg': 'Successfully downloaded', 'Ret': 0},
                'PostFix': utils.get_image_postfix(tempStorage.read(20)),
            })

        return download_fn

    def produce_msg(self, msgList):
        ''' for messages types
         * 40 msg, 43 videochat, 50 VOIPMSG, 52 voipnotifymsg
         * 53 webwxvoipnotifymsg, 9999 sysnotice
        '''
        rl = []
        srl = [40, 43, 50, 52, 53, 9999]
        for m in msgList:
            # get actual opposite
            if m['FromUserName'] == self.core.storageClass.userName:
                actualOpposite = m['ToUserName']
            else:
                actualOpposite = m['FromUserName']
            # produce basic message
            if '@@' in m['FromUserName'] or '@@' in m['ToUserName']:
                self.produce_group_chat(m)
            else:
                utils.msg_formatter(m, 'Content')
            # set user of msg
            if '@@' in actualOpposite:
                m['User'] = self.core.search_chatrooms(userName=actualOpposite) or \
                            templates.Chatroom({'UserName': actualOpposite})
            elif actualOpposite in ('filehelper', 'fmessage'):
                m['User'] = templates.User({'UserName': actualOpposite})
            else:
                m['User'] = self.core.search_mps(userName=actualOpposite) or \
                            self.core.search_friends(userName=actualOpposite) or \
                            templates.User(userName=actualOpposite)
            m['User'].core = self.core
            msg = self._handle_msg_type(m, actualOpposite)
            m.update(msg)
            rl.append(m)
        return rl

    def produce_group_chat(self, msg):
        r = re.match('(@[0-9a-z]*?):<br/>(.*)$', msg['Content'])
        if r:
            actualUserName, content = r.groups()
            chatroomUserName = msg['FromUserName']
        elif msg['FromUserName'] == self.core.storageClass.userName:
            actualUserName = self.core.storageClass.userName
            content = msg['Content']
            chatroomUserName = msg['ToUserName']
        else:
            msg['ActualUserName'] = self.core.storageClass.userName
            msg['ActualNickName'] = self.core.storageClass.nickName
            msg['IsAt'] = False
            utils.msg_formatter(msg, 'Content')
            return
        chatroom = self.core.storageClass.search_chatrooms(userName=chatroomUserName)
        member = utils.search_dict_list((chatroom or {}).get('MemberList') or [], 'UserName', actualUserName)
        if member is None:
            chatroom = self.core.update_chatroom(chatroomUserName)
            member = utils.search_dict_list((chatroom or {}).get('MemberList') or [], 'UserName', actualUserName)
        if member is None:
            logger.debug('chatroom member fetch failed with %s' % actualUserName)
            msg['ActualNickName'] = ''
            msg['IsAt'] = False
        else:
            msg['ActualNickName'] = member.get('DisplayName', '') or member['NickName']
            atFlag = '@' + (chatroom['Self'].get('DisplayName', '') or self.core.storageClass.nickName)
            msg['IsAt'] = ((atFlag + (u'\u2005' if u'\u2005' in msg['Content'] else ' ')) in msg['Content'] or msg[
                'Content'].endswith(atFlag))
        msg['ActualUserName'] = actualUserName
        msg['Content'] = content
        utils.msg_formatter(msg, 'Content')

    def send_raw_msg(self, msgType, content, toUserName):
        url = '%s/webwxsendmsg' % self.core.loginInfo['url']
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Msg': {
                'Type': msgType,
                'Content': content,
                'FromUserName': self.core.storageClass.userName,
                'ToUserName': (toUserName if toUserName else self.core.storageClass.userName),
                'LocalID': int(time.time() * 1e4),
                'ClientMsgId': int(time.time() * 1e4),
            },
            'Scene': 0,
        }
        headers = {'ContentType': 'application/json; charset=UTF-8', 'User-Agent': config.USER_AGENT}
        r = self.core.s.post(url, headers=headers,
                             data=json.dumps(data, ensure_ascii=False).encode('utf8'))
        return ReturnValue(rawResponse=r)

    def send_msg(self, msg='Test Message', toUserName=None):
        logger.debug('Request to send a text message to %s: %s' % (toUserName, msg))
        r = self.send_raw_msg(1, msg, toUserName)
        return r

    def _prepare_file(self, fileDir, file_=None):
        fileDict = {}
        if file_:
            if hasattr(file_, 'read'):
                file_ = file_.read()
            else:
                return ReturnValue({'BaseResponse': {'ErrMsg': 'file_ param should be opened file', 'Ret': -1005}})
        else:
            if not utils.check_file(fileDir):
                return ReturnValue({'BaseResponse': {'ErrMsg': 'No file found in specific dir', 'Ret': -1002}})
            with open(fileDir, 'rb') as f:
                file_ = f.read()
        fileDict['fileSize'] = len(file_)
        fileDict['fileMd5'] = hashlib.md5(file_).hexdigest()
        fileDict['file_'] = io.BytesIO(file_)
        return fileDict

    def upload_file(self, fileDir, isPicture=False, isVideo=False, toUserName='filehelper', file_=None,
                    preparedFile=None):
        logger.debug(
            'Request to upload a %s: %s' % ('picture' if isPicture else 'video' if isVideo else 'file', fileDir))
        if not preparedFile:
            preparedFile = self._prepare_file(fileDir, file_)
            if not preparedFile:
                return preparedFile
        fileSize, fileMd5, file_ = preparedFile['fileSize'], preparedFile['fileMd5'], preparedFile['file_']
        fileSymbol = 'pic' if isPicture else 'video' if isVideo else 'doc'
        chunks = int((fileSize - 1) / 524288) + 1
        clientMediaId = int(time.time() * 1e4)
        uploadMediaRequest = json.dumps(OrderedDict([
            ('UploadType', 2),
            ('BaseRequest', self.core.loginInfo['BaseRequest']),
            ('ClientMediaId', clientMediaId),
            ('TotalLen', fileSize),
            ('StartPos', 0),
            ('DataLen', fileSize),
            ('MediaType', 4),
            ('FromUserName', self.core.storageClass.userName),
            ('ToUserName', toUserName),
            ('FileMd5', fileMd5)]
        ), separators=(',', ':'))
        r = {'BaseResponse': {'Ret': -1005, 'ErrMsg': 'Empty file detected'}}
        for chunk in range(chunks):
            r = self._upload_chunk_file(fileDir, fileSymbol, fileSize, file_, chunk, chunks, uploadMediaRequest)
        file_.close()
        if isinstance(r, dict):
            return ReturnValue(r)
        return ReturnValue(rawResponse=r)

    def _upload_chunk_file(self, fileDir, fileSymbol, fileSize, file_, chunk, chunks, uploadMediaRequest):
        url = self.core.loginInfo.get('fileUrl', self.core.loginInfo['url']) + '/webwxuploadmedia?f=json'
        cookiesList = {name: data for name, data in self.core.s.cookies.items()}
        fileType = mimetypes.guess_type(fileDir)[0] or 'application/octet-stream'
        fileName = utils.quote(os.path.basename(fileDir))
        files = OrderedDict([
            ('id', (None, 'WU_FILE_0')),
            ('name', (None, fileName)),
            ('type', (None, fileType)),
            ('lastModifiedDate', (None, time.strftime('%a %b %d %Y %H:%M:%S GMT+0800 (CST)'))),
            ('size', (None, str(fileSize))),
            ('chunks', (None, None)),
            ('chunk', (None, None)),
            ('mediatype', (None, fileSymbol)),
            ('uploadmediarequest', (None, uploadMediaRequest)),
            ('webwx_data_ticket', (None, cookiesList['webwx_data_ticket'])),
            ('pass_ticket', (None, self.core.loginInfo['pass_ticket'])),
            ('filename', (fileName, file_.read(524288), 'application/octet-stream'))])
        if chunks == 1:
            del files['chunk']
            del files['chunks']
        else:
            files['chunk'], files['chunks'] = (None, str(chunk)), (None, str(chunks))
        headers = {'User-Agent': config.USER_AGENT}
        return self.core.s.post(url, files=files, headers=headers, timeout=config.TIMEOUT)

    def send_file(self, fileDir, toUserName=None, mediaId=None, file_=None):
        logger.debug('Request to send a file(mediaId: %s) to %s: %s' % (mediaId, toUserName, fileDir))
        if hasattr(fileDir, 'read'):
            return ReturnValue(
                {'BaseResponse': {'ErrMsg': 'fileDir param should not be an opened file in send_file', 'Ret': -1005}})
        if toUserName is None:
            toUserName = self.core.storageClass.userName
        preparedFile = self._prepare_file(fileDir, file_)
        if not preparedFile:
            return preparedFile
        fileSize = preparedFile['fileSize']
        if mediaId is None:
            r = self.upload_file(fileDir, preparedFile=preparedFile)
            if r:
                mediaId = r['MediaId']
            else:
                return r
        url = '%s/webwxsendappmsg?fun=async&f=json' % self.core.loginInfo['url']
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Msg': {
                'Type': 6,
                'Content': ("<appmsg appid='wxeb7ec651dd0aefa9' sdkver=''><title>%s</title>" % os.path.basename(
                    fileDir) +
                            "<des></des><action></action><type>6</type><content></content><url></url><lowurl></lowurl>" +
                            "<appattach><totallen>%s</totallen><attachid>%s</attachid>" % (str(fileSize), mediaId) +
                            "<fileext>%s</fileext></appattach><extinfo></extinfo></appmsg>" % os.path.splitext(fileDir)[
                                1].replace('.', '')),
                'FromUserName': self.core.storageClass.userName,
                'ToUserName': toUserName,
                'LocalID': int(time.time() * 1e4),
                'ClientMsgId': int(time.time() * 1e4),
            },
            'Scene': 0,
        }
        headers = {
            'User-Agent': config.USER_AGENT,
            'Content-Type': 'application/json;charset=UTF-8',
        }
        r = self.core.s.post(url, headers=headers,
                             data=json.dumps(data, ensure_ascii=False).encode('utf8'))
        return ReturnValue(rawResponse=r)

    def send_image(self, fileDir=None, toUserName=None, mediaId=None, file_=None):
        logger.debug('Request to send a image(mediaId: %s) to %s: %s' % (mediaId, toUserName, fileDir))
        if fileDir or file_:
            if hasattr(fileDir, 'read'):
                file_, fileDir = fileDir, None
            if fileDir is None:
                fileDir = 'tmp.jpg'
        else:
            return ReturnValue({'BaseResponse': {'ErrMsg': 'Either fileDir or file_ should be specific', 'Ret': -1005}})
        if toUserName is None:
            toUserName = self.core.storageClass.userName
        if mediaId is None:
            r = self.upload_file(fileDir, isPicture=not fileDir[-4:] == '.gif', file_=file_)
            if r:
                mediaId = r['MediaId']
            else:
                return r
        url = '%s/webwxsendmsgimg?fun=async&f=json' % self.core.loginInfo['url']
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Msg': {
                'Type': 3,
                'MediaId': mediaId,
                'FromUserName': self.core.storageClass.userName,
                'ToUserName': toUserName,
                'LocalID': int(time.time() * 1e4),
                'ClientMsgId': int(time.time() * 1e4),
            },
            'Scene': 0,
        }
        if fileDir[-4:] == '.gif':
            url = '%s/webwxsendemoticon?fun=sys' % self.core.loginInfo['url']
            data['Msg']['Type'] = 47
            data['Msg']['EmojiFlag'] = 2
        headers = {
            'User-Agent': config.USER_AGENT,
            'Content-Type': 'application/json;charset=UTF-8',
        }
        r = self.core.s.post(url, headers=headers,
                             data=json.dumps(data, ensure_ascii=False).encode('utf8'))
        return ReturnValue(rawResponse=r)

    def send_video(self, fileDir=None, toUserName=None, mediaId=None, file_=None):
        logger.debug('Request to send a video(mediaId: %s) to %s: %s' % (mediaId, toUserName, fileDir))
        if fileDir or file_:
            if hasattr(fileDir, 'read'):
                file_, fileDir = fileDir, None
            if fileDir is None:
                fileDir = 'tmp.mp4'
        else:
            return ReturnValue({'BaseResponse': {'ErrMsg': 'Either fileDir or file_ should be specific', 'Ret': -1005}})
        if toUserName is None:
            toUserName = self.core.storageClass.userName
        if mediaId is None:
            r = self.upload_file(fileDir, isVideo=True, file_=file_)
            if r:
                mediaId = r['MediaId']
            else:
                return r
        url = '%s/webwxsendvideomsg?fun=async&f=json&pass_ticket=%s' % (
        self.core.loginInfo['url'], self.core.loginInfo['pass_ticket'])
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            'Msg': {
                'Type': 43,
                'MediaId': mediaId,
                'FromUserName': self.core.storageClass.userName,
                'ToUserName': toUserName,
                'LocalID': int(time.time() * 1e4),
                'ClientMsgId': int(time.time() * 1e4),
            },
            'Scene': 0,
        }
        headers = {
            'User-Agent': config.USER_AGENT,
            'Content-Type': 'application/json;charset=UTF-8',
        }
        r = self.core.s.post(url, headers=headers,
                             data=json.dumps(data, ensure_ascii=False).encode('utf8'))
        return ReturnValue(rawResponse=r)

    def send(self, msg, toUserName=None, mediaId=None):
        if not msg:
            return ReturnValue({'BaseResponse': {'ErrMsg': 'No message.', 'Ret': -1005}})
        if msg[:5] == '@fil@':
            r = self.send_file(msg[5:], toUserName) if mediaId is None else self.send_file(msg[5:], toUserName, mediaId)
        elif msg[:5] == '@img@':
            r = self.send_image(msg[5:], toUserName) if mediaId is None else self.send_image(msg[5:], toUserName,
                                                                                             mediaId)
        elif msg[:5] == '@msg@':
            r = self.send_msg(msg[5:], toUserName)
        elif msg[:5] == '@vid@':
            r = self.send_video(msg[5:], toUserName) if mediaId is None else self.send_video(msg[5:], toUserName,
                                                                                             mediaId)
        else:
            r = self.send_msg(msg, toUserName)
        return r

    def revoke(self, msgId, toUserName, localId=None):
        url = '%s/webwxrevokemsg' % self.core.loginInfo['url']
        data = {
            'BaseRequest': self.core.loginInfo['BaseRequest'],
            "ClientMsgId": localId or str(time.time() * 1e3),
            "SvrMsgId": msgId,
            "ToUserName": toUserName
        }
        headers = {
            'ContentType': 'application/json; charset=UTF-8',
            'User-Agent': config.USER_AGENT
        }
        r = self.core.s.post(url, headers=headers,
                             data=json.dumps(data, ensure_ascii=False).encode('utf8'))
        return ReturnValue(rawResponse=r)

    def _handle_msg_type(self, m, actualOpposite):
        if m['MsgType'] == 1:  # words
            if m['Url']:
                regx = r'(.+?\(.+?\))'
                data = re.search(regx, m['Content'])
                data = 'Map' if data is None else data.group(1)
                return {'Type': 'Map', 'Text': data}
            else:
                return {'Type': 'Text', 'Text': m['Content']}
        elif m['MsgType'] == 3 or m['MsgType'] == 47:  # picture
            download_fn = self.get_download_fn(self.core, '%s/webwxgetmsgimg' % self.core.loginInfo['url'],
                                               m['NewMsgId'])
            return {'Type': 'Picture', 'FileName': '%s.%s' % (
            time.strftime('%y%m%d-%H%M%S', time.localtime()), 'png' if m['MsgType'] == 3 else 'gif'),
                    'Text': download_fn}
        elif m['MsgType'] == 34:  # voice
            download_fn = self.get_download_fn(self.core, '%s/webwxgetvoice' % self.core.loginInfo['url'],
                                               m['NewMsgId'])
            return {'Type': 'Recording', 'FileName': '%s.mp3' % time.strftime('%y%m%d-%H%M%S', time.localtime()),
                    'Text': download_fn}
        elif m['MsgType'] == 37:  # friends
            m['User']['UserName'] = m['RecommendInfo']['UserName']
            return {'Type': 'Friends', 'Text': {'status': m['Status'], 'userName': m['RecommendInfo']['UserName'],
                                                'verifyContent': m['Ticket'], 'autoUpdate': m['RecommendInfo']}}
        elif m['MsgType'] == 42:  # name card
            return {'Type': 'Card', 'Text': m['RecommendInfo']}
        elif m['MsgType'] in (43, 62):  # tiny video
            msgId = m['MsgId']

            def download_video(videoDir=None):
                url = '%s/webwxgetvideo' % self.core.loginInfo['url']
                params = {
                    'msgid': msgId,
                    'skey': self.core.loginInfo['skey'],
                }
                headers = {'Range': 'bytes=0-', 'User-Agent': config.USER_AGENT}
                r = self.core.s.get(url, params=params, headers=headers, stream=True)
                tempStorage = io.BytesIO()
                for block in r.iter_content(1024):
                    tempStorage.write(block)
                if videoDir is None:
                    return tempStorage.getvalue()
                with open(videoDir, 'wb') as f:
                    f.write(tempStorage.getvalue())
                return ReturnValue({'BaseResponse': {'ErrMsg': 'Successfully downloaded', 'Ret': 0}})

            return {'Type': 'Video', 'FileName': '%s.mp4' % time.strftime('%y%m%d-%H%M%S', time.localtime()),
                    'Text': download_video}
        elif m['MsgType'] == 49:  # sharing
            if m['AppMsgType'] == 0:  # chat history
                return {'Type': 'Note', 'Text': m['Content']}
            elif m['AppMsgType'] == 6:
                rawMsg = m
                cookiesList = {name: data for name, data in self.core.s.cookies.items()}

                def download_atta(attaDir=None):
                    url = self.core.loginInfo['fileUrl'] + '/webwxgetmedia'
                    params = {
                        'sender': rawMsg['FromUserName'],
                        'mediaid': rawMsg['MediaId'],
                        'filename': rawMsg['FileName'],
                        'fromuser': self.core.loginInfo['wxuin'],
                        'pass_ticket': 'undefined',
                        'webwx_data_ticket': cookiesList['webwx_data_ticket'],
                    }
                    headers = {'User-Agent': config.USER_AGENT}
                    r = self.core.s.get(url, params=params, stream=True, headers=headers)
                    tempStorage = io.BytesIO()
                    for block in r.iter_content(1024):
                        tempStorage.write(block)
                    if attaDir is None:
                        return tempStorage.getvalue()
                    with open(attaDir, 'wb') as f:
                        f.write(tempStorage.getvalue())
                    return ReturnValue({'BaseResponse': {'ErrMsg': 'Successfully downloaded', 'Ret': 0}})

                return {'Type': 'Attachment', 'Text': download_atta}
            elif m['AppMsgType'] == 8:
                download_fn = self.get_download_fn(self.core, '%s/webwxgetmsgimg' % self.core.loginInfo['url'],
                                                   m['NewMsgId'])
                return {'Type': 'Picture', 'FileName': '%s.gif' % (time.strftime('%y%m%d-%H%M%S', time.localtime())),
                        'Text': download_fn}
            elif m['AppMsgType'] == 17:
                return {'Type': 'Note', 'Text': m['FileName']}
            elif m['AppMsgType'] == 2000:
                regx = r'\[CDATA\[(.+?)\][\s\S]+?\[CDATA\[(.+?)\]'
                data = re.search(regx, m['Content'])
                if data:
                    data = data.group(2).split(u'\u3002')[0]
                else:
                    data = 'You may found detailed info in Content key.'
                return {'Type': 'Note', 'Text': data}
            else:
                return {'Type': 'Sharing', 'Text': m['FileName']}
        elif m['MsgType'] == 51:  # phone init
            return self.contact_massager.update_local_uin(self.core, m)
        elif m['MsgType'] == 10000:
            return {'Type': 'Note', 'Text': m['Content']}
        elif m['MsgType'] == 10002:
            regx = r'\[CDATA\[(.+?)\]\]'
            data = re.search(regx, m['Content'])
            data = 'System message' if data is None else data.group(1).replace('\\', '')
            return {'Type': 'Note', 'Text': data}
        elif m['MsgType'] in srl:
            return {'Type': 'Useless', 'Text': 'UselessMsg'}
        else:
            logger.debug('Useless message received: %s\n%s' % (m['MsgType'], str(m)))
            return {'Type': 'Useless', 'Text': 'UselessMsg'}


def load_messages(core):
    MessageManager(core)
