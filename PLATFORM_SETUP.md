# Platform Setup for UA FREE Content Tool

This document covers the credentials, permissions, and operational requirements for Facebook Pages, Threads, LinkedIn, Telegram, and Google Drive.

## Meta App ID and App Secret

Facebook and Threads can use the same Meta application, but they use different access tokens. Enter the Meta App ID and Meta App Secret so the application can exchange eligible short-lived tokens for long-lived tokens. The App Secret is stored in the same encrypted portable configuration as the tokens and is never written to normal logs.

## Facebook Pages

UA FREE Content Tool uses one Facebook User Access Token. It calls `/me/accounts` to load every page available to that token and stores the returned Page Access Tokens. API pagination is followed, so there is no artificial two-page limit.

A token created through Graph API Explorer is usually short-lived. After entering the App ID, App Secret, and a valid User Access Token, use **Find pages**. The application first attempts a long-lived-token exchange, then stores all Page Access Tokens and displays expiry information when available.

An expired token cannot be exchanged. Create a new valid User Access Token first.

## Threads

Required Threads permissions:

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

When the Meta App Secret is configured, an eligible short-lived Threads token can be exchanged for a long-lived token. A valid long-lived token may be refreshed before expiry. An already expired token must be recreated.

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

The **Save changes** control remains available in Settings. Successful checks for Facebook, Threads, LinkedIn, Telegram, and Google Drive also persist the verified values immediately.

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
