from .core import Core
from .config import VERSION, ASYNC_COMPONENTS
from .log import set_logging

instance = Core()
if ASYNC_COMPONENTS:
    from .async_components import load_components

    load_components(instance)
else:
    from .components import load_components

    load_components(instance)

# Assign methods from instance to module-level functions
methods_to_export = [
    # components.login
    'login', 'get_QRuuid', 'get_QR', 'check_login', 'web_init', 'show_mobile_login',
    'start_receiving', 'get_msg', 'logout',
    # components.contact
    'update_chatroom', 'update_friend', 'get_contact', 'get_friends', 'get_chatrooms',
    'get_mps', 'set_alias', 'set_pinned', 'accept_friend', 'get_head_img', 'create_chatroom',
    'set_chatroom_name', 'delete_member_from_chatroom', 'add_member_into_chatroom',
    # components.messages
    'send_raw_msg', 'send_msg', 'upload_file', 'send_file', 'send_image', 'send_video',
    'send', 'revoke',
    # components.hotreload
    'dump_login_status', 'load_login_status',
    # components.register
    'auto_login', 'configured_reply', 'msg_register', 'run',
    # other functions
    'search_friends', 'search_chatrooms', 'search_mps',
]

# Dynamically assign methods to module-level functions
for method_name in methods_to_export:
    globals()[method_name] = getattr(instance, method_name)
