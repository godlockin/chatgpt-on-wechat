"""
channel factory
"""
from common import const
from .channel import Channel

def create_channel(channel_type) -> Channel:
    """
    Create a channel instance based on channel_type.

    :param channel_type: Type of channel to create.
    :return: Channel instance corresponding to channel_type.
    :raises RuntimeError: If an unsupported channel_type is provided.
    """
    # Dictionary mapping channel types to their corresponding classes
    channel_classes = {
        "wx": "wechat.wechat_channel.WechatChannel",
        "wxy": "wechat.wechaty_channel.WechatyChannel",
        "terminal": "terminal.terminal_channel.TerminalChannel",
        "wechatmp": "wechatmp.wechatmp_channel.WechatMPChannel",
        "wechatmp_service": "wechatmp.wechatmp_channel.WechatMPChannel",
        "wechatcom_app": "wechatcom.wechatcomapp_channel.WechatComAppChannel",
        "wework": "wework.wework_channel.WeworkChannel",
        const.FEISHU: "feishu.feishu_channel.FeiShuChannel",
        const.DINGTALK: "dingtalk.dingtalk_channel.DingTalkChannel",
    }

    assert channel_type in channel_classes, f"Unsupported channel type: {channel_type}"

    # Dynamically import the appropriate channel class
    channel_class_path = channel_classes[channel_type]
    module_path, class_name = channel_class_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    ChannelClass = getattr(module, class_name)

    # Instantiate the channel class
    ch = ChannelClass()

    # Set the channel_type attribute
    ch.channel_type = channel_type

    return ch
