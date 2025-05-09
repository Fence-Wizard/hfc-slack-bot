from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import os

# Slack App & Flask setup
app = App(token=os.environ["SLACK_BOT_TOKEN"],
          signing_secret=os.environ["SLACK_SIGNING_SECRET"])
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# In-memory poll storage
poll_data = {
    "question": None,
    "options": [],
    "votes": {},  # {user_id: option_index}
    "tallies": {}  # {option_index: vote_count}
}


# Slash command: /poll "Question?" "Option 1" "Option 2" ...
@app.command("/poll")
def create_poll(ack, body, client, logger):
    ack()
    try:
        text = body.get("text", "").strip()
        parts = [p.strip('"') for p in text.split('"') if p.strip() and p != " "]
        
        if len(parts) < 2:
            client.chat_postEphemeral(
                channel=body["channel_id"],
                user=body["user_id"],
                text="❗ Please provide a question and at least one option in quotes.\nExample: `/poll \"Where to eat?\" \"Chipotle\" \"Panera\" \"Tazza\"`"
            )
            return

        question = parts[0]
        options = parts[1:]
        if len(options) > 5:
            client.chat_postEphemeral(
                channel=body["channel_id"],
                user=body["user_id"],
                text="⚠️ Please limit to 5 options."
            )
            return

        # Reset current poll data
        poll_data["question"] = question
        poll_data["options"] = options
        poll_data["votes"] = {}
        poll_data["tallies"] = {i: 0 for i in range(len(options))}

        # Post poll
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*📊 {question}*"}}
        ]
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": option},
                    "value": str(i),
                    "action_id": f"vote_{i}"
                } for i, option in enumerate(options)
            ]
        })

        client.chat_postMessage(
            channel=body["channel_id"],
            blocks=blocks,
            text=f"📊 {question}"
        )
    except Exception as e:
        logger.error(f"Error in /poll: {e}")


# Slash command: /pollresults
@app.command("/pollresults")
def show_poll_results(ack, body, client):
    ack()
    if not poll_data["question"]:
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text="❗ No active poll found. Use `/poll` to start one."
        )
        return

    results = f"*📊 Results for:* {poll_data['question']}\n"
    for i, option in enumerate(poll_data["options"]):
        count = poll_data["tallies"].get(i, 0)
        results += f"- {option}: {count} vote(s)\n"

    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=body["user_id"],
        text=results
    )


# Button vote handler (shared)
@app.action(re.compile("^vote_[0-4]$"))
def handle_vote(ack, body, action, client):
    ack()
    user_id = body["user"]["id"]
    option_index = int(action["action_id"].split("_")[1])

    if user_id in poll_data["votes"]:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="✅ You’ve already voted!"
        )
        return

    poll_data["votes"][user_id] = option_index
    poll_data["tallies"][option_index] += 1

    client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=user_id,
        text=f"🗳 Vote recorded for *{poll_data['options'][option_index]}*"
    )


# Slack + Flask integration
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


# Healthcheck
@flask_app.route("/", methods=["GET"])
def index():
    return "✅ Slack Poll Bot is live!"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)

