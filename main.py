
import os
import re
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# Initialize Slack app and Flask app
app = App(token=os.environ["SLACK_BOT_TOKEN"], signing_secret=os.environ["SLACK_SIGNING_SECRET"])
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# In-memory store for polls
polls = {}

@app.command("/poll")
def handle_poll_command(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "submit_poll",
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Post Poll"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "question_block",
                    "label": {"type": "plain_text", "text": "Poll Question"},
                    "element": {"type": "plain_text_input", "action_id": "question_input"}
                },
                *[
                    {
                        "type": "input",
                        "optional": i >= 2,
                        "block_id": f"option_block_{i}",
                        "label": {"type": "plain_text", "text": f"Option {i + 1}"},
                        "element": {"type": "plain_text_input", "action_id": f"option_input_{i}"}
                    }
                    for i in range(5)
                ]
            ]
        }
    )

@app.view("submit_poll")
def handle_poll_submission(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    state_values = body["view"]["state"]["values"]

    question = state_values["question_block"]["question_input"]["value"]
    options = []
    for i in range(5):
        key = f"option_block_{i}"
        action = f"option_input_{i}"
        if key in state_values and action in state_values[key]:
            val = state_values[key][action]["value"]
            if val:
                options.append(val)

    if not question or len(options) < 2:
        return

    message_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{question}*"}},
        {"type": "divider"},
    ]
    for idx, opt in enumerate(options):
        message_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":{['one','two','three','four','five'][idx]}: {opt}"}
        })

    # Post poll in the channel where command was invoked
    channel_id = body["view"]["private_metadata"] if "private_metadata" in body["view"] else user_id
    client.chat_postMessage(channel=channel_id, blocks=message_blocks, text=question)

    # Confirm to the user privately
    try:
        client.chat_postMessage(
            channel=user_id,
            text="✅ Your poll has been posted."
        )
    except Exception as e:
        print(f"Error sending poll confirmation: {e}")

# Slack events route
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# App root route (optional)
@flask_app.route("/", methods=["GET"])
def home():
    return "HFC Survey Bot is running!"

# Run the Flask app
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
