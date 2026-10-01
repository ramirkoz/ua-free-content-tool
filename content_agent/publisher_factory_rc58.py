from .media_gallery_v1_2_rc4 import VideoGalleryPayload
from .publisher_factory_v1_2_rc3_compat import Rc3CompatiblePublisherFactory
from .telegram_video_album_rc58 import Rc58TelegramPublisher
class _FirstVideoOnlyPublisher:
    def __init__(self,delegate): self.delegate=delegate
    def publish(self,text,progress,context,media=None):
        if isinstance(media,VideoGalleryPayload): media=media.first
        return self.delegate.publish(text,progress,context,media)
class Rc58PublisherFactory(Rc3CompatiblePublisherFactory):
    def create(self,platform:str):
        if platform=="telegram" or platform.startswith("telegram:"): return Rc58TelegramPublisher(self.config.telegram_bot_token,self.config.telegram_chat_id)
        return _FirstVideoOnlyPublisher(super().create(platform))
