from bot.bot_factory import create_bot
from common import const
from common.log import logger
from common.singleton import singleton
from config import config
from translate.factory import create_translator
from voice.factory import create_voice
from .context import Context
from .reply import Reply


@singleton
class Bridge(object):
    def __init__(self):
        self.btype = {
            "chat": const.CHATGPT,
            "voice_to_text": config.get("voice_to_text", "openai"),
            "text_to_voice": config.get("text_to_voice", "google"),
            "translate": config.get("translate", "baidu"),
        }

        bot_type = config.get("bot_type")
        if bot_type:
            self.btype["chat"] = bot_type
        else:
            model_type = config.get("model") or const.GPT35

            if model_type == "text-davinci-003":
                self.btype["chat"] = const.OPEN_AI

            if config.get("use_azure_chatgpt", False):
                self.btype["chat"] = const.CHATGPTONAZURE

            if model_type in ["wenxin", "wenxin-4"]:
                self.btype["chat"] = const.BAIDU

            if model_type == "xunfei":
                self.btype["chat"] = const.XUNFEI

            if model_type == const.QWEN:
                self.btype["chat"] = const.QWEN

            if model_type in [const.QWEN_TURBO, const.QWEN_PLUS, const.QWEN_MAX]:
                self.btype["chat"] = const.QWEN_DASHSCOPE

            if model_type == const.GEMINI:
                self.btype["chat"] = const.GEMINI

            if model_type == const.ZHIPU_AI:
                self.btype["chat"] = const.ZHIPU_AI

            if model_type and model_type.startswith("claude-3"):
                self.btype["chat"] = const.CLAUDEAPI

            if model_type == "claude":
                self.btype["chat"] = const.CLAUDEAI

            if model_type in ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]:
                self.btype["chat"] = const.MOONSHOT

            if model_type == "abab6.5-chat":
                self.btype["chat"] = const.MiniMax

            if config.get("use_linkai") and config.get("linkai_api_key"):
                self.btype["chat"] = const.LINKAI
                if not config.get("voice_to_text") or config.get("voice_to_text") == "openai":
                    self.btype["voice_to_text"] = const.LINKAI
                if not config.get("text_to_voice") or config.get("text_to_voice") in ["openai", const.TTS_1,
                                                                                      const.TTS_1_HD]:
                    self.btype["text_to_voice"] = const.LINKAI

        self.bots = {}
        self.chat_bots = {}

    def get_bot(self, typename):
        if self.bots.get(typename) is None:
            logger.info(f"Creating bot {self.btype[typename]} for {typename}")
            if typename == "text_to_voice" or typename == "voice_to_text":
                self.bots[typename] = create_voice(self.btype[typename])
            elif typename == "chat":
                self.bots[typename] = create_bot(self.btype[typename])
            elif typename == "translate":
                self.bots[typename] = create_translator(self.btype[typename])
        return self.bots[typename]

    def get_bot_type(self, typename):
        return self.btype.get(typename)

    def fetch_reply_content(self, query, context: Context) -> Reply:
        return self.get_bot("chat").reply(query, context)

    def fetch_voice_to_text(self, voiceFile) -> Reply:
        return self.get_bot("voice_to_text").voiceToText(voiceFile)

    def fetch_text_to_voice(self, text) -> Reply:
        return self.get_bot("text_to_voice").textToVoice(text)

    def fetch_translate(self, text, from_lang="", to_lang="en") -> Reply:
        return self.get_bot("translate").translate(text, from_lang, to_lang)

    def find_chat_bot(self, bot_type: str):
        if self.chat_bots.get(bot_type) is None:
            self.chat_bots[bot_type] = create_bot(bot_type)
        return self.chat_bots.get(bot_type)

    def reset_bot(self):
        """
        Reset bot routing
        """
        self.__init__()
