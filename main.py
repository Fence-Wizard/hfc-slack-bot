
import os
import re
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# Flask and Slack app initialization
flask_app = Flask(__name__)
app = App(token=os.environ["SLACK_BOT_TOKEN"], signing_secret=os.environ["SLACK_SIGNING_SECRET"])
handler = SlackRequestHandler(app)

# In-memory poll data
poll_data = {
    "question": None,
    "options": [],
    "votes": {},
    "tallies": {},
    "creator_id": None,
    "active": False
}

@app.command("/poll")
def open_poll_modal(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    user_id = body["user_id"]
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "submit_poll",
            "private_metadata": user_id,
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
def handle_poll_submission(ack, body, view, client):
    ack()
    user_id = body["user"]["id"]
    channel_id = body["view"]["private_metadata"]
    state_values = view["state"]["values"]

    question = state_values["question_block"]["question_input"]["value"]
    options = []
    for i in range(5):
        block_id = f"option_block_{i}"
        action_id = f"option_input_{i}"
        if block_id in state_values and action_id in state_values[block_id]:
            val = state_values[block_id][action_id]["value"]
            if val:
                options.append(val)

    if len(options) < 2:
        return

    # Save poll state
    poll_data["question"] = question
    poll_data["options"] = options
    poll_data["votes"] = {}
    poll_data["tallies"] = {i: 0 for i in range(len(options))}
    poll_data["creator_id"] = user_id
    poll_data["active"] = True

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📊 {question}*"}},
        {"type": "actions",
         "elements": [
             {
                 "type": "button",
                 "text": {"type": "plain_text", "text": option},
                 "value": str(i),
                 "action_id": f"vote_{i}"
             } for i, option in enumerate(options)
         ]}
    ]

    client.chat_postMessage(channel=channel_id, text=question, blocks=blocks)

    try:
        im = client.conversations_open(users=user_id)
        dm_channel = im["channel"]["id"]
        client.chat_postMessage(channel=dm_channel, text="✅ Your poll has been posted.")
    except Exception as e:
        print(f"Error sending poll confirmation: {e}")

@app.action(re.compile("^vote_\d$"))
def handle_vote(ack, body, action, client):
    ack()
    if not poll_data["active"]:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="❌ This poll has been closed."
        )
        return

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

    results = f"🗳 Vote recorded for *{poll_data['options'][option_index]}*

*📊 Current Results:*
"
    for i, option in enumerate(poll_data["options"]):
        results += f"- {option}: {poll_data['tallies'].get(i, 0)} vote(s)
"

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=results
    )

@app.command("/pollresults")
def show_poll_results(ack, body, client):
    ack()
    channel_id = body["channel_id"]
    user_id = body["user_id"]

    if not poll_data["question"]:
        client.chat_postEphemeral(channel=channel_id, user=user_id,
                                  text="❗ No active poll found.")
        return

    results = f"*📊 Results for:* {poll_data['question']}
"
    for i, option in enumerate(poll_data["options"]):
        results += f"- {option}: {poll_data['tallies'].get(i, 0)} vote(s)
"

    client.chat_postEphemeral(channel=channel_id, user=user_id, text=results)

@app.command("/closepoll")
def close_poll(ack, body, client):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]

    if poll_data.get("creator_id") != user_id:
        client.chat_postEphemeral(channel=channel_id, user=user_id,
                                  text="❌ Only the poll creator can close the poll.")
        return

    poll_data["active"] = False

    results = f"✅ Poll *'{poll_data['question']}'* has been closed.

*Final Results:*
"
    for i, option in enumerate(poll_data["options"]):
        results += f"- {option}: {poll_data['tallies'].get(i, 0)} vote(s)
"

    client.chat_postMessage(channel=channel_id, text=results)

# Slack route
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# Health check
@flask_app.route("/", methods=["GET"])
def index():
    return "✅ HFC Slack Bot is running."

# Run app
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))

