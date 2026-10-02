from pathlib import Path
import inspect, pytest
from content_agent.media_gallery_v1_2_rc4 import VideoGalleryPayload
from content_agent.models import MediaPayload
from content_agent.multi_image_store_v1_2_rc4 import MultiImageStore, MultiImageStoreError, StoredImageAttachment
from content_agent.publisher_factory_rc58 import _FirstVideoOnlyPublisher
from content_agent.telegram_media_v1_3_rc6 import _TelegramPostMediaParser
from content_agent.telegram_video_album_rc58 import _video_album_body
from content_agent.v2.ui.manual_topics_window_rc44 import MainWindow

def media(name): return MediaPayload(name,name,"video","video/mp4",b"video","")
def test_store_video_opt_in(tmp_path):
    item=StoredImageAttachment("v","v.mp4","video/mp4",5,"")
    with pytest.raises(MultiImageStoreError): MultiImageStore(tmp_path/"a.json").set_group(1,[item])
    s=MultiImageStore(tmp_path/"b.json",allow_video=True); s.set_group(1,[item]); assert s.list_group(1)[0].mime_type=="video/mp4"
def test_video_gallery_and_album():
    g=VideoGalleryPayload([media("1"),media("2"),media("3")]); body,ct=_video_album_body("chat","caption",g)
    assert all(f"attach://video{i}".encode() in body for i in range(3)); assert b'"type":"video"' in body; assert ct.startswith("multipart/form-data")
def test_other_platform_first_only():
    calls=[]
    class D:
        def publish(self,t,p,c,media=None): calls.append(media); return "ok"
    g=VideoGalleryPayload([media("1"),media("2")]); assert _FirstVideoOnlyPublisher(D()).publish("x",{},None,g)=="ok"; assert calls==[g.first]
def test_grouped_player_pages_all_collected():
    html='<div class="tgme_widget_message_grouped"><a class="tgme_widget_message_video_player" href="https://telesco.pe/file/a"></a><a class="tgme_widget_message_video_player" href="https://telesco.pe/file/b"></a></div>'
    p=_TelegramPostMediaParser("https://t.me/x/1?embed=1","x"); p.feed(html); assert p.player_pages==["https://telesco.pe/file/a","https://telesco.pe/file/b"]
def test_progress_busy_only():
    src=inspect.getsource(MainWindow); assert "progress.start(" in src and "progress.stop()" in src and "_rc59_media_busy_count" in src
def test_candidate_video_multiselect_enabled():
    src=Path("content_agent/ui/candidate_gallery_actions_v1_2_rc4.py").read_text(encoding="utf-8"); assert "self._commit_uploaded_media(uploads, group_id)" in src; assert "Кілька медіафайлів можна додавати тільки як фотогалерею" not in src
