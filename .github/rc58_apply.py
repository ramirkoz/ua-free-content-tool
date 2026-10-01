from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"RC58 patch marker missing in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# Backward-compatible store: image-only by default, current runtime opts into video.
replace("content_agent/multi_image_store_v1_2_rc4.py",
    '    @classmethod\n    def from_mapping(cls, value: object) -> "StoredImageAttachment":\n',
    '    @classmethod\n    def from_mapping(cls, value: object, *, allow_video: bool = False) -> "StoredImageAttachment":\n')
replace("content_agent/multi_image_store_v1_2_rc4.py",
    '        if not file_id or not mime_type.startswith("image/"):\n            raise MultiImageStoreError("У списку кількох медіа дозволені лише фото.")\n',
    '        allowed = mime_type.startswith("image/") or (allow_video and mime_type.startswith("video/"))\n        if not file_id or not allowed:\n            raise MultiImageStoreError("У списку кількох медіа дозволені лише фото або відео одного типу.")\n')
replace("content_agent/multi_image_store_v1_2_rc4.py",
    'class MultiImageStore:\n    def __init__(self, path: Path | None = None):\n        self.path = path or (data_dir() / "multi_images_v1_2.json")\n',
    'class MultiImageStore:\n    def __init__(self, path: Path | None = None, *, allow_video: bool = False):\n        self.path = path or (data_dir() / "multi_images_v1_2.json")\n        self.allow_video = bool(allow_video)\n')
replace("content_agent/multi_image_store_v1_2_rc4.py",
    '        return [StoredImageAttachment.from_mapping(item) for item in raw][:MAX_IMAGE_ATTACHMENTS]\n',
    '        return [StoredImageAttachment.from_mapping(item, allow_video=self.allow_video) for item in raw][:MAX_IMAGE_ATTACHMENTS]\n')
replace("content_agent/multi_image_store_v1_2_rc4.py",
    '        for item in items:\n            if not item.mime_type.casefold().startswith("image/"):\n                raise MultiImageStoreError("Кілька медіафайлів дозволені тільки для зображень.")\n            if not item.file_id or item.file_id in seen:\n',
    '        media_families: set[str] = set()\n        for item in items:\n            mime = item.mime_type.casefold()\n            family = "image" if mime.startswith("image/") else ("video" if mime.startswith("video/") else "")\n            if not family or (family == "video" and not self.allow_video):\n                raise MultiImageStoreError("Кілька медіафайлів дозволені тільки для фото або відео.")\n            media_families.add(family)\n            if len(media_families) > 1:\n                raise MultiImageStoreError("Не змішуйте фото й відео в одному наборі медіа.")\n            if not item.file_id or item.file_id in seen:\n')

# Active legacy boundary uses the RC58 factory/worker and video-enabled sidecar.
replace("content_agent/ui/v1_2_rc4_window.py",
    'from ..publisher_factory_v1_2_rc3_compat import Rc3CompatiblePublisherFactory\nfrom ..worker_v1_2_rc4 import Rc4PublicationWorker\n',
    'from ..publisher_factory_rc58 import Rc58PublisherFactory\nfrom ..worker_rc58 import Rc58PublicationWorker\n')
replace("content_agent/ui/v1_2_rc4_window.py", '        self.multi_image_store = MultiImageStore()\n', '        self.multi_image_store = MultiImageStore(allow_video=True)\n')
replace("content_agent/ui/v1_2_rc4_window.py",
    '        self.publisher_factory = Rc3CompatiblePublisherFactory(self.config)\n        self.worker = Rc4PublicationWorker(\n',
    '        self.publisher_factory = Rc58PublisherFactory(self.config)\n        self.worker = Rc58PublicationWorker(\n')

Path("content_agent/media_registration_rc58.py").write_text('''from __future__ import annotations
from .google_drive import GoogleDriveError
from .managed_media_drive import ManagedMediaUpload
from .multi_image_store_v1_2_rc4 import MAX_IMAGE_ATTACHMENTS, MultiImageStore, StoredImageAttachment

def register_secondary_media(db, registry, store: MultiImageStore, upload: ManagedMediaUpload, group_id: int) -> None:
    if upload.info.kind not in {"image", "video"}:
        raise GoogleDriveError("Підтримуються тільки фото та відео.")
    group = db.get_group(group_id)
    rows = store.list_group(group_id)
    if rows and rows[0].file_id != group.media_file_id:
        rows = []
    if not rows and group.media_file_id and group.media_kind in {"image", "video"}:
        rows = [StoredImageAttachment(group.media_file_id, group.media_name or group.media_kind, group.media_mime or ("image/jpeg" if group.media_kind == "image" else "video/mp4"), int(group.media_size or 0), group.media_drive_url)]
    if not rows or group.media_kind != upload.info.kind:
        raise GoogleDriveError("Додаткове медіа має бути того самого типу, що й основне.")
    if len(rows) >= MAX_IMAGE_ATTACHMENTS:
        raise GoogleDriveError(f"До однієї публікації можна додати не більше {MAX_IMAGE_ATTACHMENTS} медіафайлів.")
    store.set_group(group_id, rows)
    registry.register(upload.info.file_id, folder_id=upload.folder_id, group_id=group_id, name=upload.info.name)
    store.append(group_id, StoredImageAttachment(upload.info.file_id, upload.info.name, upload.info.mime_type, upload.info.size, f"https://drive.google.com/file/d/{upload.info.file_id}/view"))
''', encoding="utf-8")

Path("content_agent/ui/multi_image_actions_v1_2_rc4.py").write_text('''from __future__ import annotations
from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_registration_rc58 import register_secondary_media
from ..multi_image_store_v1_2_rc4 import StoredImageAttachment

class MultiImageActionsMixin:
    def _attachment_rows(self, group_id: int | None = None) -> list[StoredImageAttachment]:
        target = int(group_id or getattr(self, "current_group_id", 0) or 0)
        if not target: return []
        group = self.db.get_group(target)
        if not group.media_file_id: return []
        rows = self.multi_image_store.list_group(target)
        if rows and rows[0].file_id == group.media_file_id: return rows
        if group.media_kind in {"image", "video"}:
            return [StoredImageAttachment(group.media_file_id, group.media_name or group.media_kind, group.media_mime or ("image/jpeg" if group.media_kind == "image" else "video/mp4"), int(group.media_size or 0), group.media_drive_url)]
        return []

    def _refresh_attached_images(self) -> None:
        rows = self._attachment_rows()
        if len(rows) > 1 and hasattr(self, "media_status_var"):
            kind = "відео" if rows[0].mime_type.casefold().startswith("video/") else "фото"
            self.media_status_var.set(f"Прикріплено {kind}: {len(rows)} із 10. Google Drive: перевірено ✓")
        tree = getattr(self, "attached_images_tree", None)
        if tree is not None:
            tree.delete(*tree.get_children())
            from .media_workflow import format_media_size
            for index, item in enumerate(rows, start=1):
                tree.insert("", "end", iid=item.file_id, values=(index, item.name, format_media_size(item.size)))

    def register_extra_media(self, upload: ManagedMediaUpload, group_id: int) -> None:
        register_secondary_media(self.db, self.managed_media_registry, self.multi_image_store, upload, group_id)
        self._refresh_attached_images()
    def register_extra_image(self, upload: ManagedMediaUpload, group_id: int) -> None:
        self.register_extra_media(upload, group_id)

    def _commit_uploaded_media(self, uploads: list[ManagedMediaUpload], group_id: int) -> None:
        if not uploads: return
        kinds = {item.info.kind for item in uploads}
        if len(kinds) != 1 or next(iter(kinds)) not in {"image", "video"}:
            raise GoogleDriveError("Оберіть медіа одного типу: тільки фото або тільки відео.")
        kind = next(iter(kinds)); group = self.db.get_group(group_id); start = 0
        if not group.media_file_id:
            self._media_target_group_id = group_id; self._attach_uploaded_media(uploads[0]); start = 1
        elif group.media_kind != kind:
            raise GoogleDriveError("Не можна змішувати фото й відео в одному наборі медіа.")
        for upload in uploads[start:]: self.register_extra_media(upload, group_id)
        self._refresh_attached_images()
    def _commit_uploaded_images(self, uploads: list[ManagedMediaUpload], group_id: int) -> None:
        self._commit_uploaded_media(uploads, group_id)

    def _upload_image_batch(self, prepared: list[tuple[object, str]], group_id: int, *, label: str) -> None:
        def action() -> object:
            client = self._managed_drive_client(); uploaded: list[ManagedMediaUpload] = []
            try:
                for media, filename in prepared: uploaded.append(client.upload_validated_media(media, filename))
                return uploaded
            except Exception:
                for upload in uploaded:
                    try: client.delete_file(upload.info.file_id)
                    except GoogleDriveError: pass
                raise
        def success(result: object) -> None:
            uploads = list(result) if isinstance(result, list) else []
            self._commit_uploaded_media(uploads, group_id)
            self.media_candidates_status_var.set(f"Прикріплено медіа: {len(self._attachment_rows(group_id))}. Google Drive: перевірено ✓")
        self.run_async(action, success, label=label, done_label="Медіа оновлено")
''', encoding="utf-8")

Path("content_agent/ui/candidate_gallery_actions_v1_2_rc4.py").write_text('''from __future__ import annotations
from ..google_drive import GoogleDriveError
from ..managed_media_drive import ManagedMediaUpload
from ..media_candidates import download_media_candidate
from .media_workflow import media_filename_from_url

class CandidateGalleryActionsMixin:
    def _selected_media_candidates_rc4(self):
        tree = getattr(self, "media_candidates_tree", None)
        if tree is None: return []
        result = []
        for iid in tree.selection():
            try: index = int(iid)
            except ValueError: continue
            if 0 <= index < len(self._media_candidates): result.append(self._media_candidates[index])
        return result

    def use_selected_media_candidate(self) -> None:
        candidates = self._selected_media_candidates_rc4()
        if not candidates: return super().use_selected_media_candidate()
        group_id = getattr(self, "current_group_id", None)
        if group_id is None:
            self.msg.showinfo("Медіа", "Спочатку відкрийте новину в редакторі.", parent=self.root); return
        if len(candidates) == 1: return super().use_selected_media_candidate()
        kinds = {candidate.kind for candidate in candidates}
        if len(kinds) != 1 or next(iter(kinds)) not in {"image", "video"}:
            self._show_error(GoogleDriveError("Оберіть кілька медіа одного типу: тільки фото або тільки відео.")); return
        if len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 медіафайлів.")); return
        kind = next(iter(kinds)); attached = self._attachment_rows(group_id)
        if attached:
            attached_kind = "video" if attached[0].mime_type.casefold().startswith("video/") else "image"
            if attached_kind != kind:
                self._show_error(GoogleDriveError("Не можна змішувати фото й відео в одному наборі медіа.")); return
        if len(attached) + len(candidates) > 10:
            self._show_error(GoogleDriveError("До однієї публікації можна додати не більше 10 медіафайлів.")); return
        def action() -> object:
            client = self._managed_drive_client(); uploaded: list[ManagedMediaUpload] = []
            try:
                for candidate in candidates:
                    media = download_media_candidate(candidate)
                    uploaded.append(client.upload_validated_media(media, media_filename_from_url(media.source_url or candidate.url, media.mime_type)))
                return uploaded
            except Exception:
                for upload in uploaded:
                    try: client.delete_file(upload.info.file_id)
                    except GoogleDriveError: pass
                raise
        def success(result: object) -> None:
            uploads = list(result) if isinstance(result, list) else []
            self._commit_uploaded_media(uploads, group_id)
            self.media_candidates_status_var.set(f"Із джерел додано {'відео' if kind == 'video' else 'фото'}: {len(uploads)}.")
        self.run_async(action, success, label=f"Завантажую вибрані медіа з джерел: {len(candidates)}", done_label="Медіа з джерел додано")
''', encoding="utf-8")

replace("content_agent/ui/multi_image_v1_2_rc4.py", 'text="Прикріплені фото (до 10)"', 'text="Прикріплені медіа (до 10)"')
replace("content_agent/ui/multi_image_v1_2_rc4.py", 'text="Прибрати вибрані фото"', 'text="Прибрати вибране медіа"')
replace("content_agent/ui/multi_image_v1_2_rc4.py", '        if group.media_file_id and group.media_kind == "image":\n', '        if group.media_file_id and group.media_kind in {"image", "video"}:\n')
replace("content_agent/ui/multi_image_v1_2_rc4.py", '                    name=group.media_name or "image",\n                    mime_type=group.media_mime or "image/jpeg",\n', '                    name=group.media_name or group.media_kind,\n                    mime_type=group.media_mime or ("image/jpeg" if group.media_kind == "image" else "video/mp4"),\n')

p = Path("content_agent/media_gallery_v1_2_rc4.py")
p.write_text(p.read_text(encoding="utf-8") + '''\n\n@dataclass(slots=True)\nclass VideoGalleryPayload:\n    items: list[MediaPayload]\n    def __post_init__(self) -> None:\n        if not (2 <= len(self.items) <= MAX_IMAGE_ATTACHMENTS): raise ValueError(f"Відеокарусель повинна містити від 2 до {MAX_IMAGE_ATTACHMENTS} відео.")\n        if any(item.kind != "video" or not item.mime_type.casefold().startswith("video/") for item in self.items): raise ValueError("У відеокаруселі дозволені тільки відео.")\n    @property\n    def first(self) -> MediaPayload: return self.items[0]\n    @property\n    def file_id(self) -> str: return self.first.file_id\n    @property\n    def name(self) -> str: return self.first.name\n    @property\n    def kind(self) -> str: return "video"\n    @property\n    def mime_type(self) -> str: return self.first.mime_type\n    @property\n    def data(self) -> bytes: return self.first.data\n    @property\n    def public_url(self) -> str: return self.first.public_url\n''', encoding="utf-8")

Path("content_agent/telegram_video_album_rc58.py").write_text('''from __future__ import annotations
import json, secrets
from .comment_compat_v1_2_rc3 import CompatibleTelegramPublisher
from .media_gallery_v1_2_rc4 import VideoGalleryPayload
from .network import NetworkError, fetch_url
from .publication_text import telegram_split
from .publishers import PublishContext, PublishError, PublishResult, _check_payload, _post_form

def _video_album_body(chat_id: str, caption: str, gallery: VideoGalleryPayload) -> tuple[bytes, str]:
    boundary = "----UAFreeVideoAlbum" + secrets.token_hex(16); rows=[]
    for i,item in enumerate(gallery.items):
        row={"type":"video","media":f"attach://video{i}"}
        if i==0 and caption: row["caption"]=caption
        rows.append(row)
    chunks=[]
    for key,value in {"chat_id":chat_id,"media":json.dumps(rows,ensure_ascii=False,separators=(",", ":"))}.items(): chunks += [f"--{boundary}\\r\\n".encode(), f'Content-Disposition: form-data; name="{key}"\\r\\n\\r\\n'.encode(), str(value).encode(), b"\\r\\n"]
    for i,item in enumerate(gallery.items):
        safe=item.name.replace('"','_').replace('\\r','_').replace('\\n','_'); chunks += [f"--{boundary}\\r\\n".encode(), f'Content-Disposition: form-data; name="video{i}"; filename="{safe}"\\r\\n'.encode(), f"Content-Type: {item.mime_type}\\r\\n\\r\\n".encode(), item.data, b"\\r\\n"]
    chunks.append(f"--{boundary}--\\r\\n".encode()); return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

def _send_video_album(token,chat_id,caption,gallery):
    body,ct=_video_album_body(chat_id,caption,gallery); response=fetch_url(f"https://api.telegram.org/bot{token}/sendMediaGroup",method="POST",headers={"Content-Type":ct,"Accept":"application/json"},body=body,max_bytes=4*1024*1024,allowed_content_types={"application/json","text/javascript"},timeout=300,max_redirects=1,allow_http_errors=True); payload=response.json() if response.body else {}
    if response.status>=400: _check_payload(payload,http_status=response.status); raise PublishError(f"Telegram sendMediaGroup failed with HTTP {response.status}.",retryable=response.status==429 or response.status>=500,rate_limited=response.status==429)
    result=_check_payload(payload).get("result")
    if not isinstance(result,list): raise PublishError("Telegram не повернув список повідомлень після відеокаруселі.",retryable=False,outcome_unknown=True)
    ids=[str(x.get("message_id")) for x in result if isinstance(x,dict) and x.get("message_id") not in (None,"")]
    if not ids: raise PublishError("Telegram не повернув message_id після відеокаруселі.",retryable=False,outcome_unknown=True)
    return ids

class Rc58TelegramPublisher(CompatibleTelegramPublisher):
    def publish(self,text,progress,context:PublishContext,media=None):
        if not isinstance(media,VideoGalleryPayload): return super().publish(text,progress,context,media)
        ids=list(progress.get("telegram_video_album_remote_ids") or [])
        if progress.get("telegram_video_album_completed") and ids: return PublishResult(remote_id=str(ids[0]),progress=progress)
        if progress.get("telegram_video_album_started"): raise PublishError("Telegram: результат попередньої відеокаруселі невідомий; автоматичний повтор заблоковано.",retryable=False,outcome_unknown=True)
        caption=text if len(text)<=1024 else ""; progress={**progress,"telegram_video_album_started":True,"telegram_video_album_completed":False}; context.save_progress(progress); context.before_write()
        try: ids=_send_video_album(self.token,self.chat_id,caption,media)
        except PublishError as exc:
            if not exc.retryable and not exc.outcome_unknown: context.save_progress({**progress,"telegram_video_album_started":False}); raise
            raise PublishError("Telegram: результат відеокаруселі невідомий; повтор заблоковано.",retryable=False,outcome_unknown=True) from exc
        except NetworkError as exc: raise PublishError("Telegram: з'єднання перервалося під час відеокаруселі; результат невідомий.",retryable=False,outcome_unknown=True) from exc
        progress={**progress,"telegram_video_album_started":False,"telegram_video_album_completed":True,"telegram_video_album_remote_ids":ids}; context.save_progress(progress)
        if not caption and text:
            for part in telegram_split(text):
                context.before_write(); result=_post_form(f"https://api.telegram.org/bot{self.token}/sendMessage",{"chat_id":self.chat_id,"text":part,"disable_web_page_preview":"false"})
                if result.get("ok") is not True: raise PublishError(str(result.get("description","Telegram rejected text after video album.")))
        return PublishResult(remote_id=ids[0],progress=progress)
''', encoding="utf-8")

Path("content_agent/publisher_factory_rc58.py").write_text('''from .media_gallery_v1_2_rc4 import VideoGalleryPayload
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
''', encoding="utf-8")

Path("content_agent/worker_rc58.py").write_text('''from .google_drive import GoogleDriveError
from .media_gallery_v1_2_rc4 import ImageGalleryPayload, VideoGalleryPayload
from .models import MediaPayload
from .worker_v1_2_rc4 import Rc4PublicationWorker
class Rc58PublicationWorker(Rc4PublicationWorker):
    def _load_media(self,batch_article_id:int):
        group_id=self.database.group_id_for_article(batch_article_id); group=self.database.get_group(group_id)
        if not group.media_file_id: return None,None,group_id,None
        client=self._drive_client(); rows=self.image_store.list_group(group_id)
        if len(rows)>=2:
            payloads=[]; infos=[]; kinds=set()
            for stored in rows:
                info=client.inspect_media(stored.file_id)
                if info.kind not in {"image","video"}: raise GoogleDriveError("Набір медіа містить непідтримуваний файл.")
                kinds.add(info.kind)
                if len(kinds)>1: raise GoogleDriveError("Не змішуйте фото й відео в одному наборі медіа.")
                if info.kind=="image": client.ensure_public_for_threads(info)
                data=client.download_media(info); infos.append(info); payloads.append(MediaPayload(info.file_id,info.name,info.kind,info.mime_type,data,info.public_url))
            return (VideoGalleryPayload(payloads) if next(iter(kinds))=="video" else ImageGalleryPayload(payloads)),client,group_id,infos[0]
        info=client.inspect_media(group.media_file_id)
        if info.kind=="image": client.ensure_public_for_threads(info)
        return MediaPayload(info.file_id,info.name,info.kind,info.mime_type,client.download_media(info),info.public_url),client,group_id,info
''', encoding="utf-8")

# Telegram grouped post: follow every player page and retain real videos.
replace("content_agent/telegram_media_v1_3_rc6.py", '        self.items: list[MediaCandidate] = []\n', '        self.items: list[MediaCandidate] = []\n        self.player_pages: list[str] = []\n')
replace("content_agent/telegram_media_v1_3_rc6.py", '        if lowered_tag == "a":\n            href = values.get("href", "")\n            if urlsplit(href).path.casefold().endswith(_VIDEO_EXT):\n                self._append(href, fallback="video", origin="telegram:a:video", score=145)\n', '        if lowered_tag == "a":\n            href = _safe_media_url(self.page_url, values.get("href", ""))\n            if href and urlsplit(href).path.casefold().endswith(_VIDEO_EXT):\n                self._append(href, fallback="video", origin="telegram:a:video", score=145)\n            elif href and (urlsplit(href).hostname or "").casefold().endswith("telesco.pe"):\n                if href not in self.player_pages:\n                    self.player_pages.append(href)\n')
replace("content_agent/telegram_media_v1_3_rc6.py", 'def extract_telegram_post_media(html: str, page_url: str, source_label: str = "") -> list[MediaCandidate]:\n    parser = _TelegramPostMediaParser(page_url, source_label)\n    parser.feed(str(html or ""))\n    return prefer_real_video(deduplicate_media_candidates(parser.items))\n', 'def _extract_telegram_post_details(html: str, page_url: str, source_label: str = "") -> tuple[list[MediaCandidate], list[str]]:\n    parser = _TelegramPostMediaParser(page_url, source_label)\n    parser.feed(str(html or ""))\n    return prefer_real_video(deduplicate_media_candidates(parser.items)), list(parser.player_pages)\n\ndef extract_telegram_post_media(html: str, page_url: str, source_label: str = "") -> list[MediaCandidate]:\n    items, _ = _extract_telegram_post_details(html, page_url, source_label)\n    return items\n')
replace("content_agent/telegram_media_v1_3_rc6.py", '        exact = extract_telegram_post_media(html, response.final_url, source_label)\n        if exact:\n            result = exact\n        else:\n', '        exact, player_pages = _extract_telegram_post_details(html, response.final_url, source_label)\n        followed_videos: list[MediaCandidate] = []\n        for player_url in player_pages[:10]:\n            try:\n                player = fetch_url(player_url, headers={"Accept":"text/html,application/xhtml+xml","Cache-Control":"no-cache"}, max_bytes=5*1024*1024, allowed_content_types={"text/html","application/xhtml+xml"}, timeout=35, max_redirects=5)\n            except NetworkError:\n                continue\n            followed_videos.extend(item for item in extract_html_media(player.body.decode("utf-8", errors="replace"), player.final_url, source_label) if item.kind == "video")\n        if exact or followed_videos:\n            result = prefer_real_video(deduplicate_media_candidates([*exact, *followed_videos]))\n        else:\n')

# Busy-only media progress.
replace("content_agent/v2/ui/manual_topics_window_rc44.py", '        progress.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(2, 4))\n        self._rc56_media_progress = progress\n', '        progress.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(2, 4))\n        progress.grid_remove()\n        self._rc56_media_progress = progress\n')
replace("content_agent/v2/ui/manual_topics_window_rc44.py", '        if progress is not None:\n            progress.start(12)\n', '        if progress is not None:\n            progress.grid()\n            progress.start(10)\n            try:\n                progress.update_idletasks()\n            except Exception:\n                pass\n')
replace("content_agent/v2/ui/manual_topics_window_rc44.py", '                self._post_ui(progress.stop)\n', '                def _stop_media_progress() -> None:\n                    progress.stop()\n                    progress.grid_remove()\n                self._post_ui(_stop_media_progress)\n')

Path("VERSION.txt").write_text("2.0.0-rc58\n", encoding="utf-8")
Path("PUBLIC_VERSION.txt").write_text("2.0.0-rc58\n", encoding="utf-8")
replace("content_agent/__init__.py", '__version__ = "2.0.0-rc57"', '__version__ = "2.0.0-rc58"')
Path("RELEASE_NOTES_v2.0.0-rc58.md").write_text("# UA FREE Content Tool 2.0.0-rc58\n\nFocused live-media bugfix: busy-only animated media progress; all real videos from Telegram grouped posts; 2–10 selected videos; Telegram sends all as media group; other platforms receive first selected video; RC57 Inbox stability retained.\n", encoding="utf-8")

Path("tests/test_rc58_video_carousel.py").write_text('''from pathlib import Path
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
    src=inspect.getsource(MainWindow); assert "progress.grid_remove()" in src and "progress.grid()" in src and "progress.start(10)" in src
def test_candidate_video_multiselect_enabled():
    src=Path("content_agent/ui/candidate_gallery_actions_v1_2_rc4.py").read_text(encoding="utf-8"); assert "self._commit_uploaded_media(uploads, group_id)" in src; assert "Кілька медіафайлів можна додавати тільки як фотогалерею" not in src
''', encoding="utf-8")

Path(".github/workflows/rc58-targeted.yml").write_text('''name: RC58 Telegram video carousel gate
on:
  push:
    branches: [rc58-telegram-video-carousel]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  validate-and-build:
    runs-on: windows-2025
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: python -m pip install -r requirements.txt
      - name: Compile
        run: python -m compileall -q content_agent tests
      - name: RC58 contracts
        run: python -m pytest -q tests/test_rc58_video_carousel.py
      - name: RC57 and RC56 regression
        run: python -m pytest -q tests/test_rc57_inbox_stability.py tests/test_rc56_live_bugfixes.py
      - name: Full suite BLOCKING
        run: python -m pytest -q
      - name: Build portable
        run: python scripts/build_windows_portable.py --version 2.0.0-rc58
      - name: Package exact portable
        shell: pwsh
        run: |
          $name = "UA_FREE_Content_Tool_v2.0.0-rc58_Windows_Portable_MANUAL_TEST.zip"
          Compress-Archive -Path "dist/UA_FREE_Content_Tool_v2.0.0-rc58_Windows_Portable/*" -DestinationPath $name -Force
          $hash = (Get-FileHash $name -Algorithm SHA256).Hash.ToLower()
          "$hash  $name" | Out-File -Encoding ascii SHA256SUMS_RC58.txt
      - uses: actions/upload-artifact@v4
        with:
          name: UA_FREE_Content_Tool_v2.0.0-rc58_Windows_Portable_MANUAL_TEST
          path: |
            UA_FREE_Content_Tool_v2.0.0-rc58_Windows_Portable_MANUAL_TEST.zip
            SHA256SUMS_RC58.txt
''', encoding="utf-8")
