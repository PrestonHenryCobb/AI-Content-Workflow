# YouTube API audit: copy-paste answers

**Why:** until this audit passes, YouTube locks every video uploaded through the API to
**private**, and `publishAt` won't make it public. The form also requests a quota increase.

**Form:** [YouTube API Services: Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form)
(choose the option for an audit / quota extension for an existing project).

Field names on Google's form change from time to time; match these answers to the closest field.

| Field | Answer |
|---|---|
| Your name / contact email | your name and the Gmail that owns the Google Cloud project |
| Organization | Cold Save (individual creator) |
| Organization website | https://prestonhenrycobb.github.io/AI-Content-Workflow/ |
| Google Cloud project ID / number | Google Cloud console → project picker → `cold-save` (copy both from the dashboard's *Project info* card) |
| API client name | Cold Save Pipeline |
| Privacy policy URL | https://prestonhenrycobb.github.io/AI-Content-Workflow/privacy.html |
| Terms of service URL | https://prestonhenrycobb.github.io/AI-Content-Workflow/terms.html |
| APIs used | YouTube Data API v3; YouTube Analytics API |
| Is the client publicly available / used by other users? | No. Single-channel internal tool used only by the channel owner on their own channel (@coldsavecases). |
| Requested daily quota | 20,000 units |

## "Describe your use case / how your client uses YouTube API Services"

> Cold Save Pipeline is a private, server-side publishing tool for a single YouTube channel
> that I own and operate, Cold Save (@coldsavecases, channel ID UCUXvG67KWKTb-pMFdx95qbw).
> It has no other users, no public sign-in, and no user interface; it runs as scheduled
> GitHub Actions jobs authorized with my own OAuth credentials.
>
> It uses the YouTube Data API to: upload the channel's own original short videos
> (videos.insert, resumable) scheduled with status.publishAt and with
> containsSyntheticMedia=true disclosed; set the channel's own description, keywords and
> banner (channels.update, channelBanners.insert); create the channel's own playlists and
> add its videos to them (playlists.insert, playlistItems.insert); post one comment from
> the channel on each of its own videos (commentThreads.insert); and read top-level public
> comments on its own videos once a week (commentThreads.list) to count which real cases
> viewers are requesting. Commenter identities are not stored.
>
> It uses the YouTube Analytics API to read the channel's own per-video aggregate metrics
> (views, average view percentage, average view duration, likes, comments, subscribers
> gained) to decide which content formats work best. API data is refreshed or deleted
> within 30 days.
>
> No YouTube data is sold, shared, or shown to anyone else. The videos are original
> AI-assisted documentary shorts about real, historical cold cases, researched from public
> records, with sources listed in every description.

## "Why do you need additional quota?"

> The channel publishes 3 short videos per day plus one long-form compilation per week.
> Each upload costs 1,600 units (videos.insert), plus playlist inserts and a comment
> (about 150 units per video), so about 5,250 units per day for shorts and about 2,000 on
> compilation days. Channel/playlist reads, weekly comment reads, and occasional retries
> after failed uploads push peak days to about 9,000–11,000 units, too close to the default
> 10,000. 20,000 units per day gives safe headroom for retries without
> exceeding real need.

## Screencast / demo (if requested)

There's no UI. If the form requires a video or screenshots, provide:
1. A screen recording of the GitHub Actions **channel-setup** and **nightly** runs and their
   logs, showing the sign-in to @coldsavecases and the scheduled upload.
2. A screenshot of the channel showing the uploaded videos and playlists.
3. A link to the public repository: https://github.com/PrestonHenryCobb/AI-Content-Workflow
   (`pipeline/youtube.py` shows every API call made).

## After submitting

Approval usually takes days to a few weeks, and Google may email follow-up questions;
reply from the same address. The pipeline can run before approval; uploads just stay
private until it's granted.
