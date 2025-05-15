import os
import re
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# Flask + Bolt setup
flask_app = Flask(__name__)
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)
handler = SlackRequestHandler(app)

# In-memory poll state
poll_data = {
    "question": None,
    "options": [],
    "votes": {},       # user_id -> option_index
    "tallies": {},     # option_index -> count
    "creator_id": None,
    "active": False
}

# 1) /poll opens a modal to build your question + up to 5 options
@app.command("/poll")
def open_poll_modal(ack, body, client):
    ack()
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    trigger_id = body["trigger_id"]

    # pack both channel and user into private_metadata
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "submit_poll",
            "private_metadata": f"{channel_id}|{user_id}",
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Post Poll"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "question_block",
                    "label": {"type": "plain_text", "text": "Poll Question"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "question_input"
                    }
                },
                *[
                    {
                        "type": "input",
                        "block_id": f"option_block_{i}",
                        "optional": i >= 2,
                        "label": {"type": "plain_text", "text": f"Option {i+1}"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": f"option_input_{i}"
                        }
                    }
                    for i in range(5)
                ]
            ]
        }
    )

# 2) Handle the modal submission, post the poll, DM confirmation
@app.view("submit_poll")
def handle_poll_submission(ack, body, view, client):
    ack()
    # unpack metadata
    meta = view["private_metadata"].split("|")
    channel_id, creator_id = meta[0], meta[1]

    # gather inputs
    state = view["state"]["values"]
    question = state["question_block"]["question_input"]["value"]

    options = []
    for i in range(5):
        block = state.get(f"option_block_{i}", {})
        val = block.get(f"option_input_{i}", {}).get("value")
        if val:
            options.append(val)

    if len(options) < 2:
        client.chat_postEphemeral(
            channel=creator_id, user=creator_id,
            text="❌ Please provide at least two options."
        )
        return

    # reset poll data
    poll_data.update({
        "question": question,
        "options": options,
        "votes": {},
        "tallies": {i: 0 for i in range(len(options))},
        "creator_id": creator_id,
        "active": True
    })

    # build and post the poll
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📊 {question}*"}}
    ]
    action_elems = []
    for idx, opt in enumerate(options):
        action_elems.append({
            "type": "button",
            "text": {"type": "plain_text", "text": opt},
            "action_id": f"vote_{idx}",
            "value": str(idx)
        })
    blocks.append({"type": "actions", "elements": action_elems})

    client.chat_postMessage(channel=channel_id, text=question, blocks=blocks)

    # DM the creator a confirmation
    try:
        im = client.conversations_open(users=creator_id)
        dm = im["channel"]["id"]
        client.chat_postMessage(channel=dm, text="✅ Your poll has been posted.")
    except Exception as e:
        print(f"Error sending poll confirmation: {e}")

# 3) Handle any vote button clicks
@app.action(re.compile(r"^vote_\d+$"))
def handle_vote(ack, body, client):
    ack()
    if not poll_data["active"]:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="❌ This poll has been closed."
        )
        return

    user = body["user"]["id"]
    channel = body["channel"]["id"]
    idx = int(body["actions"][0]["action_id"].split("_")[1])

    if user in poll_data["votes"]:
        client.chat_postEphemeral(
            channel=channel, user=user,
            text="✅ You’ve already voted."
        )
        return

    # record the vote
    poll_data["votes"][user] = idx
    poll_data["tallies"][idx] = poll_data["tallies"].get(idx, 0) + 1

    # build immediate results
    lines = [f"🗳 Vote recorded for *{poll_data['options'][idx]}*"]
    lines.append("\n*📊 Current Results:*")
    for i, opt in enumerate(poll_data["options"]):
        count = poll_data["tallies"].get(i, 0)
        lines.append(f"- {opt}: {count} vote(s)")

    client.chat_postEphemeral(
        channel=channel,
        user=user,
        text="\n".join(lines)
    )

# 4) /pollresults shows the current tallies to any user
@app.command("/pollresults")
def show_poll_results(ack, body, client):
    ack()
    chan = body["channel_id"]
    user = body["user_id"]
    if not poll_data["question"]:
        client.chat_postEphemeral(
            channel=chan, user=user,
            text="❗ No active poll."
        )
        return

    lines = [f"*📊 Results for:* {poll_data['question']}"]
    for i, opt in enumerate(poll_data["options"]):
        count = poll_data["tallies"].get(i, 0)
        lines.append(f"- {opt}: {count} vote(s)")

    client.chat_postEphemeral(
        channel=chan, user=user,
        text="\n".join(lines)
    )

# 5) /closepoll lets only the creator end it and broadcast final results
@app.command("/closepoll")
def close_poll(ack, body, client):
    ack()
    user = body["user_id"]
    chan = body["channel_id"]

    if poll_data["creator_id"] != user:
        client.chat_postEphemeral(
            channel=chan, user=user,
            text="❌ Only the poll creator can close the poll."
        )
        return

    poll_data["active"] = False
    lines = [f"✅ Poll *{poll_data['question']}* has been closed.", "\n*Final Results:*"]
    for i, opt in enumerate(poll_data["options"]):
        count = poll_data["tallies"].get(i, 0)
        lines.append(f"- {opt}: {count} vote(s)")

    client.chat_postMessage(channel=chan, text="\n".join(lines))

# HTTP endpoints
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

@flask_app.route("/", methods=["GET"])
def index():
    return "✅ HFC Slack Bot is running."

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
