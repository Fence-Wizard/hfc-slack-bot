# HFC Slack Bot

This repository contains a simple Slack bot built with [Slack Bolt](https://slack.dev/bolt-python) and Flask.

## Prerequisites

- **Python 3.8+** - ensure Python is installed on your system.
- **Slack credentials** - `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` from your Slack App configuration.

## Installation

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set the required environment variables:

```bash
export SLACK_BOT_TOKEN=<your-bot-token>
export SLACK_SIGNING_SECRET=<your-signing-secret>
```

## Running the Application

The application is configured to run with `gunicorn` as specified in the `Procfile`.
Start the bot with:

```bash
gunicorn main:flask_app
```

The bot will listen for events from Slack as configured in your Slack App.

When deployed on Render's free tier, the process is automatically spun down
after periods of inactivity. A simple `/` endpoint is available for health
checks, which returns `✅ HFC Slack Bot is running.` If you require constant
uptime, you may need to periodically ping this endpoint, subject to Render's
Terms of Service.

## Feedback Format Options

When creating a feedback poll, you can now add up to *ten* questions. Each
question may be set as a multiple-choice vote or a traditional feedback
question. Feedback questions still allow either free-form paragraphs or a
1–5 ranking.

## Blended Polls

The initial modal now lets you choose *Vote*, *Feedback*, *Ranking* or *Blended*.
Selecting **Blended** prompts you for up to ten questions where each question
can be marked as either a vote or feedback prompt. Vote questions can include
up to five custom options for participants to choose from.

## Ranking Polls

Select **Ranking** to ask participants to rate a single question from 1 to 5
stars. Enter the question as the poll title in the initial modal. After posting
the poll, users click *Submit Rating* to provide their star score.

## Multiple Selections

When creating a vote poll, you can optionally allow participants to choose more
than one option. In the second step of poll creation, check the *Allow multiple
selections?* box before posting the poll.
