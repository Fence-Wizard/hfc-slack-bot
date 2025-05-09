from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import os

# Initialize Slack app
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)

# Initialize Flask app
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# Store anonymous votes and comments
votes = {"good": 0, "neutral": 0, "bad": 0}
comments = []

# Slash command: /survey
@app.command("/survey")
def handle_survey_command(ack, body, client, logger):
    try:
        ack()  # Must acknowledge within 3 seconds to avoid "dispatch_failed"
        logger.info("✅ /survey slash command received")

        channel_id = body.get("channel_id")
        if not channel_id:
            logger.error("❌ No channel_id in slash command body")
            return

        client.chat_postMessage(
            channel=channel_id,
            text="*HFC Anonymous Survey*:\nHow do you feel about our new process?",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "How do you feel about our new process?"}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "👍 Good"},
                            "value": "good",
                            "action_id": "vote_good"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "😐 Neutral"},
                            "value": "neutral",
                            "action_id": "vote_neutral"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "👎 Bad"},
                            "value": "bad",
                            "action_id": "vote_bad"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✏️ Leave a comment"},
                            "action_id": "open_comment_modal"
                        }
                    ]
                }
            ]
        )

        logger.info("✅ Survey message sent successfully")
    except Exception as e:
        logger.error(f"❌ Error in /survey handler: {e}")

# Button vote handlers
@app.action("vote_good")
@app.action("vote_neutral")
@app.action("vote_bad")
def handle_vote(ack, action, respond, logger):
    ack()
    vote = action["value"]
    votes[vote] += 1
    respond(delete_original=True)
    respond("✅ Your anonymous vote was recorded. Thank you!")
    logger.info(f"🗳 Vote recorded: {vote}")

# Modal trigger
@app.action("open_comment_modal")
def open_comment_modal(ack, body, client, logger):
    ack()
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
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
        logger.info("📝 Comment modal opened")
    except Exception as e:
        logger.error(f"❌ Error opening comment modal: {e}")

# Modal submission
@app.view("submit_comment")
def handle_comment_submission(ack, view, logger):
    ack()
    try:
        comment = view["state"]["values"]["comment_block"]["comment_input"]["value"]
        comments.append(comment)
        logger.info(f"📝 Comment submitted: {comment}")
    except Exception as e:
        logger.error(f"❌ Error processing submitted comment: {e}")

# Slack events endpoint
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# Healthcheck route (for Render)
@flask_app.route("/")
def home():
    return "✅ HFC Survey Bot is running!"

# Gunicorn entry point
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)
