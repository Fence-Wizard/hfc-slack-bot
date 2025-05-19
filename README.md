# HFC Slack Bot

A Slack bot for polls and feedback using Flask and Slack Bolt.

## Environment Variables

The bot requires the following variables set in your environment:

- `SLACK_BOT_TOKEN` – Bot user OAuth token from Slack.
- `SLACK_SIGNING_SECRET` – Signing secret for verifying Slack requests.
- `PORT` – Port to bind the Flask server (default `3000`).

## Installation

Install dependencies with pip:

```bash
pip install -r requirements.txt
```

## Running Locally

Set the required environment variables and start the Flask app:

```bash
python main.py
```

This runs the bot on `http://localhost:$PORT/`.

## Deployment with Gunicorn/Heroku

A `Procfile` is included for running with Gunicorn:

```bash
gunicorn main:flask_app
```

Deploy the app to Heroku (or a similar platform) using this command. Heroku will install dependencies from `requirements.txt` and run the above command automatically.

