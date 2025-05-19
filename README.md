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
