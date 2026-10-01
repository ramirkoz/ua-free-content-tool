from .google_drive import GoogleDriveError
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
