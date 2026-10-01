from __future__ import annotations
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
    for key,value in {"chat_id":chat_id,"media":json.dumps(rows,ensure_ascii=False,separators=(",", ":"))}.items(): chunks += [f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"]
    for i,item in enumerate(gallery.items):
        safe=item.name.replace('"','_').replace('\r','_').replace('\n','_'); chunks += [f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="video{i}"; filename="{safe}"\r\n'.encode(), f"Content-Type: {item.mime_type}\r\n\r\n".encode(), item.data, b"\r\n"]
    chunks.append(f"--{boundary}--\r\n".encode()); return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

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
