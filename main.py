import os
import re
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request

# Initialize Flask and Slack Bolt
flask_app = Flask(__name__)
app = App(token=os.environ["SLACK_BOT_TOKEN"], signing_secret=os.environ["SLACK_SIGNING_SECRET"])
handler = SlackRequestHandler(app)

# In-memory poll state
poll_data = {
    "question": None,
    "options": [],
    "votes": {},    # {user_id: option_index}
    "tallies": {},  # {option_index: vote_count}
}

# Health check
@flask_app.route("/", methods=["GET"])
def index():
    return "✅ HFC Slack Bot is running!"

# Slack event route
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# /poll command → opens modal
@app.command("/poll")
def open_poll_modal(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]

    modal_view = {
        "type": "modal",
        "callback_id": "poll_submission",
        "title": {"type": "plain_text", "text": "Create a Poll"},
        "submit": {"type": "plain_text", "text": "Post Poll"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "question_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "question_input"
                },
                "label": {"type": "plain_text", "text": "Poll Question"}
            }
        ] + [
            {
                "type": "input",
                "block_id": f"option_block_{i}",
                "optional": i >= 2,
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"option_input_{i}"
                },
                "label": {"type": "plain_text", "text": f"Option {i+1}"}
            } for i in range(5)
        ]
    }

    client.views_open(trigger_id=trigger_id, view=modal_view)

# Handle modal submission
@app.view("poll_submission")
def handle_poll_submission(ack, body, view, client, logger):
    ack()
    user_id = body["user"]["id"]
    channel_id = body["view"]["private_metadata"] or body["view"]["team_id"]  # fallback

    try:
        question = view["state"]["values"]["question_block"]["question_input"]["value"]
        options = []

        for i in range(5):
            block_id = f"option_block_{i}"
            action_id = f"option_input_{i}"
            input_value = view["state"]["values"].get(block_id, {}).get(action_id, {}).get("value")
            if input_value:
                options.append(input_value)

        if len(options) < 2:
            return  # Should never happen due to Slack modal validation

        # Save poll
        poll_data["question"] = question
        poll_data["options"] = options
        poll_data["votes"] = {}
        poll_data["tallies"] = {i: 0 for i in range(len(options))}

        # Create poll message
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*📊 {question}*"}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": option},
                        "value": str(i),
                        "action_id": f"vote_{i}"
                    } for i, option in enumerate(options)
                ]
            }
        ]

        # Post to channel where command was initiated
        client.chat_postMessage(
            channel=body["view"]["team_id"],  # default fallback
            text=f"📊 {question}",
            blocks=blocks
        )

    except Exception as e:
        logger.error(f"Failed to post poll: {e}")
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❗ Failed to create poll. Please try again."
        )

# Button vote handler
@app.action(re.compile("^vote_[0-4]$"))
def handle_vote(ack, body, action, client):
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    option_index = int(action["action_id"].split("_")[1])

    if user_id in poll_data["votes"]:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="✅ You’ve already voted!"
        )
        return

    poll_data["votes"][user_id] = option_index
    poll_data["tallies"][option_index] += 1

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"🗳 Vote recorded for *{poll_data['options'][option_index]}*"
    )

# /pollresults command
@app.command("/pollresults")
def show_poll_results(ack, body, client):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]

    if not poll_data["question"]:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❗ No active poll found. Use `/poll` to start one."
        )
        return

    results = f"*📊 Results for:* {poll_data['question']}\n"
    for i, option in enumerate(poll_data["options"]):
        count = poll_data["tallies"].get(i, 0)
        results += f"- {option}: {count} vote(s)\n"

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=results
    )

# Local or Render run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)



