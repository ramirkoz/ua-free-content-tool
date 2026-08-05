# Platform Setup for UA FREE Content Tool

This document covers the credentials, permissions, and operational requirements for Facebook Pages, Threads, LinkedIn, Telegram, and Google Drive.

## Facebook and Threads applications

Version 1.1.0 stores Facebook and Threads application credentials separately. This supports the common case where the Facebook Page and Threads profile belong to different Meta accounts or were configured in different developer applications.

Configure these fields independently:

```text
Facebook App ID
Facebook App Secret
Facebook User Access Token

Threads App ID
Threads App Secret
Threads Access Token
```

Do not paste a Facebook App Secret into the Threads field or reuse an unrelated application merely because both products belong to Meta. Legacy shared Meta fields are migrated for compatibility, but the separate platform fields are authoritative after the v1.1.0 settings are saved.

App Secrets and tokens are stored in the encrypted portable configuration and are not written to normal logs.

## Facebook Pages

UA FREE Content Tool uses one Facebook User Access Token. It calls `/me/accounts` to load every page available to that token and stores the returned Page Access Tokens. API pagination is followed, so there is no artificial two-page limit.

A token created through Graph API Explorer is usually short-lived. After entering the **Facebook** App ID, Facebook App Secret, and a valid User Access Token, use **Find pages**. The application first attempts a long-lived-token exchange, then stores available Page Access Tokens and displays expiry information when available.

An expired token cannot be exchanged. Create a new valid User Access Token first.

The token must belong to an account that can manage the required Facebook Page and must include the permissions required by Meta for page discovery and publication.

## Threads

Enter the **Threads** App ID, Threads App Secret, and Threads Access Token in the Threads section. They are independent from the Facebook values.

Required publication permissions:

```text
threads_basic
threads_content_publish
```

Optional permission for current-topic comparison:

```text
threads_keyword_search
```

The trend-search check uses the current `graph.threads.net/keyword_search` endpoint, has a bounded timeout, and displays a separate result. The profile does not need to be resolved again for every trend check.

Without `threads_keyword_search`, ordinary publishing still works, but the trend/explosiveness assessment is marked as partial.

When the Threads App Secret is configured, an eligible short-lived Threads token can be exchanged for a long-lived token. A valid long-lived token may be refreshed before expiry. An already expired token must be recreated.

Use **Determine profile** to validate publication identity and **Check trend search** separately to validate `threads_keyword_search`. One check does not silently substitute for the other.

## LinkedIn

1. Open LinkedIn Developer Portal Token Generator.
2. Create a token with:

```text
openid
profile
w_member_social
```

3. Paste the token into the application and run the token check.

The personal profile is resolved automatically through the API.

## Telegram

Required:

- Bot Token from `@BotFather`;
- channel username or channel ID;
- the bot must be a channel administrator;
- the bot must have `can_post_messages`.

A correct Bot Token alone is not sufficient if the bot lacks the channel role or permission.

## Google Drive media

### One-time Google Cloud setup

1. Create a Google Cloud project. The Free Trial is not required.
2. Enable Google Drive API.
3. Configure the OAuth consent screen for the account that will own the media.
4. Create an OAuth Client ID of type `Desktop app`.
5. Copy the Client ID and, when provided, Client Secret into the application settings.
6. Use **Connect Drive** and approve access in the browser.

The refresh token is stored in the encrypted portable configuration. Drive access is used to download the selected file for publishing and to delete it only after every selected platform succeeds.

### For each publication

1. Upload one image or one video to your Google Drive folder.
2. Keep both the folder and file private.
3. Copy the link to the specific file.
4. Paste it into the Publication tab and use **Check media**.

The check verifies that:

- the file is an image or video;
- the connected account can download and delete it;
- when Threads is selected, the account can temporarily expose that specific file.

During Threads publishing, the application creates temporary `anyone/reader` access only for the selected file. After an error, the temporary permission is revoked and the file remains private. After all selected platforms succeed, the file is permanently deleted.

Do not make the whole folder public.

## Token storage and saving

The **Save changes** control remains available in Settings. Successful checks for Facebook, Threads, LinkedIn, Telegram, and Google Drive also persist verified values immediately.

When switching from v1.0.0, open Settings once, verify the separate Facebook and Threads fields, and save them. Do not rotate a working token merely because the field layout changed.

## Automatic connection diagnostics

The application checks saved connections after startup and every six hours. Results are shown in the Platforms and Google Drive section. Automatic checks do not open modal windows and do not block editorial work.

Connection states are intentionally distinct:

- `valid` — the live API confirmed the token and required read-only access;
- `replace token` — the platform explicitly reported invalid, expired, revoked, or insufficiently scoped credentials;
- `check permissions` — the token works, but a role or permission is missing;
- `temporarily unverified` — DNS, network, or platform failure; do not rotate a token without evidence;
- `not configured` — the integration has not been configured.

For LinkedIn, the application exposes the actual `/v2/userinfo` error fields when available. For Telegram, it checks the bot identity, channel access, administrator status, and `can_post_messages`.

## Recovering missed publications

After replacing expired tokens or correcting permissions, open the Queue and use **Reschedule missed / paused**. The application moves paused and overdue pending packages into the nearest future slots while preserving targets already marked `sent`.
## Publication history and engagement metrics

The History tab stores publication records locally even when a platform does not expose engagement data. Use **Refresh selected metrics** after publication.

- **Facebook Pages:** the application can read reactions, comments, shares, and the post permalink with the saved Page Access Token. Post views are not exposed by the basic Page-post fields used here.
- **Threads:** views, likes, replies, reposts, quotes, and shares require `threads_manage_insights`. Normal publishing still uses `threads_basic` and `threads_content_publish`.
- **LinkedIn:** likes and comments are requested through Social Actions when the application has approved read access. LinkedIn may reject this for personal posts when only `w_member_social` is granted; the limitation is shown in History and does not affect publishing.
- **Telegram:** the Bot API does not expose channel-post views, reactions, forwards, or comments. For public `@username` channels, the application still creates a direct `t.me` post link from the saved message ID.

Metric failures are stored per platform and never change the original publication time or retry a publication.
