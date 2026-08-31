# UA FREE Content Tool v1.4.0-rc4

RC4 is an editorial/UI cleanup over the v1.4 independent-destination publication model.

## What changed

- Inbox no longer shows internal group/block IDs.
- Topic classification now scores the whole merged event: canonical headline, source headlines and bounded source text. Geography is stored as tags rather than being mistaken for the main topic.
- Topic assignments are cached in `Data/topic_assignments_v1_4_rc4.json`; a topic can be manually corrected by double-clicking the Topic cell, and `Авто` restores automatic classification.
- Duplicate review opens maximized, remembers column widths, removes visible group IDs, and preselects only high-confidence (90%+) merge candidates by default.
- Publication targets consistently show their social network: Facebook, Instagram, Threads, LinkedIn or Telegram.
- The last selected publication target set is restored on the next material and persisted while the user changes it.
- Queue now shows one editorial story per overview row. Selecting it reveals the independent per-network publication tasks below with profile, network, time, status and error.
- Publication History now shows one editorial story per overview row. Selecting it reveals the individual network results and metrics below.

## What did not change

- Every destination still has its own independent batch and schedule.
- Terminal publication errors are still not retried automatically, preventing uncertain duplicate posts.
- Shared media cleanup still waits until every selected destination is terminal.

## Upgrade

Extract the Portable package into a new folder and copy the complete `Data` directory from v1.4.0-rc3. Do not merge program files from different RC folders.
