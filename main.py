import os
import re
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# Initialize Slack app with bot token and signing secret
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# In-memory storage for poll data
active_poll = {
    "question": None,
    "options": [],
    "votes": {},
    "voted_users": set()
}

# Health check route for uptime monitor
@flask_app.route("/", methods=["GET"])
def health_check():
    return "✅ HFC Survey Bot is running!"

# Slack event endpoint
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# Slash command to trigger a survey
@app.command("/survey")
def handle_survey_command(ack, respond):
    ack()
    respond("*HFC Survey Bot* is active! Use `/poll` to create a poll.")

# Slash command to create a poll
@app.command("/poll")
def handle_poll_command(ack, body, respond):
    ack()
    user_id = body["user_id"]
    text = body.get("text", "")

    # Parse poll text as "Question | Option 1 | Option 2 | Option 3"
    parts = [part.strip() for part in text.split("|")]
    if len(parts) < 3:
        respond("❌ Invalid format. Use: `/poll Question | Option 1 | Option 2 | ...`")
        return

    question = parts[0]
    options = parts[1:]

    active_poll["question"] = question
    active_poll["options"] = options
    active_poll["votes"] = {i: 0 for i in range(len(options))}
    active_poll["voted_users"] = set()

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{question}*"}},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"{i + 1}. {option}"},
                "value": str(i),
                "action_id": f"vote_{i}"
            } for i, option in enumerate(options)
        ]}
    ]

    respond(blocks=blocks)

# Handle vote button actions
@app.action(re.compile("^vote_[0-9]+$"))
def handle_vote_action(ack, body, action, respond):
    ack()
    user_id = body["user"]["id"]
    vote_index = int(action["value"])

    if user_id in active_poll["voted_users"]:
        respond("❗ You have already voted.")
        return

    if vote_index not in active_poll["votes"]:
        respond("❌ Invalid vote option.")
        return

    active_poll["votes"][vote_index] += 1
    active_poll["voted_users"].add(user_id)
    respond("✅ Vote recorded. Thanks!")

# Slash command to show poll results
@app.command("/pollresults")
def handle_poll_results(ack, respond):
    ack()
    if not active_poll["question"]:
        respond("ℹ️ No active poll.")
        return

    results = [f"*{active_poll['question']}*\n"]
    for i, option in enumerate(active_poll["options"]):
        vote_count = active_poll["votes"].get(i, 0)
        results.append(f"> {option}: {vote_count} votes")

    respond("\n".join(results))

# Run Flask app
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))


