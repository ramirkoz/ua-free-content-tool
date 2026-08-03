# GitHub repository setup

Recommended repository settings:

- Repository name: `ua-free-content-tool`
- Visibility: public
- Default branch: `main`
- Description: `Privacy-first Windows desktop tool for collecting, rewriting, scheduling and cross-posting Ukrainian news with local Ollama.`
- Homepage: `https://uafree.org/`
- Topics: `ukraine`, `news`, `content-automation`, `ollama`, `telegram`, `threads`, `linkedin`, `facebook`, `python`, `windows`, `privacy`, `nonprofit`

## First release

1. Push this repository to `main`.
2. Open **Actions → Build and publish Windows release**.
3. Choose **Run workflow**.
4. Enter version `1.0.0` and leave prerelease disabled.
5. The workflow runs tests, builds the portable package, creates a source ZIP and publishes GitHub Release `v1.0.0` with SHA-256 checksums.

Do not upload a working `Data` folder or any file containing real credentials.
