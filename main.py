from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import os

# Initialize Slack app
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)

# Flask app for handling requests
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# Store anonymous votes and comments in memory
votes = {"good": 0, "neutral": 0, "bad": 0}
comments = []

# Slash command /survey
@app.command("/survey")
def handle_survey_command(ack, body, client):
    ack()
    channel_id = body["channel_id"]
    client.chat_postMessage(
        channel=channel_id,
        text="*HFC Anonymous Survey*:\nHow do you feel about our new process?",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": "How do you feel about our new process?"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "👍 Good"}, "value": "good", "action_id": "vote_good"},
                {"type": "button", "text": {"type": "plain_text", "text": "😐 Neutral"}, "value": "neutral", "action_id": "vote_neutral"},
                {"type": "button", "text": {"type": "plain_text", "text": "👎 Bad"}, "value": "bad", "action_id": "vote_bad"},
                {"type": "button", "text": {"type": "plain_text", "text": "✏️ Leave a comment"}, "action_id": "open_comment_modal"},
            ]}
        ]
    )

# Button voting logic
@app.action("vote_good")
@app.action("vote_neutral")
@app.action("vote_bad")
def handle_vote(ack, action, respond):
    ack()
    vote = action["value"]
    votes[vote] += 1
    respond(delete_original=True)
    respond("✅ Your anonymous vote was recorded. Thank you!")

# Comment modal logic
@app.action("open_comment_modal")
def open_comment_modal(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "submit_comment",
            "title": {"type": "plain_text", "text": "Anonymous Feedback"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "comment_block",
                    "label": {"type": "plain_text", "text": "What's on your mind?"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "comment_input",
                        "multiline": True
                    }
                }
            ],
            "submit": {"type": "plain_text", "text": "Submit"}
        }
    )

@app.view("submit_comment")
def handle_comment_submission(ack, view):
    ack()
    comment = view["state"]["values"]["comment_block"]["comment_input"]["value"]
    comments.append(comment)

# Slack events endpoint
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# Home route to test Render
@flask_app.route("/", methods=["GET"])
def home():
    return "✅ HFC Survey Bot is running!"

# Required to run Flask via gunicorn
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=3000)
