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

When creating a feedback poll, each question can now be configured individually
to collect answers as free-form paragraphs or as a 1–5 ranking. Select the
desired format for each question in the creation modal.
