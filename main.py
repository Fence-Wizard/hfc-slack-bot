import os
import re
import json
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# ─── App setup ────────────────────────────────────────────────────────────────
token = os.getenv("SLACK_BOT_TOKEN")
secret = os.getenv("SLACK_SIGNING_SECRET")

if token is None or secret is None:
    missing = []
    if token is None:
        missing.append("SLACK_BOT_TOKEN")
    if secret is None:
        missing.append("SLACK_SIGNING_SECRET")
    print(f"Error: Missing required environment variables: {', '.join(missing)}")
    raise SystemExit(1)

flask_app = Flask(__name__)
app = App(
    token=token,
    signing_secret=secret,
)
handler = SlackRequestHandler(app)

# ─── In‐memory store ────────────────────────────────────────────────────────────
poll_data = {
    "type": None,
    "question": None,
    "options": [],
    "feedback_questions": [],
    "feedback_format": "paragraph",
    "votes": {},
    "tallies": {},
    "feedback_responses": [],
    "creator_id": None,
    "channel_id": None,
    "anonymous": True,
    "active": False,
}

# ─── /poll ────────────────────────────────────────────────────────────────────
@app.command("/poll")
def open_poll_modal(ack, body, client):
    """Begin poll creation by selecting type and title."""
    ack()
    trigger_id = body["trigger_id"]
    metadata = json.dumps({"channel": body["channel_id"], "user": body["user_id"]})

    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "poll_step1",
            "private_metadata": metadata,
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Next"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "type_block",
                    "label": {"type": "plain_text", "text": "Poll Type"},
                    "element": {
                        "type": "static_select",
                        "action_id": "poll_type",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Vote"}, "value": "vote"},
                            {"text": {"type": "plain_text", "text": "Feedback"}, "value": "feedback"},
                        ]
                    }
                },
                {
                    "type": "input",
                    "block_id": "question_block",
                    "label": {"type": "plain_text", "text": "Poll Title"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "question_input",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Type the main question or prompt here"
                        }
                    }
                },
                {
                    "type": "input",
                    "block_id": "visibility_block",
                    "label": {"type": "plain_text", "text": "Results Visibility"},
                    "element": {
                        "type": "static_select",
                        "action_id": "visibility_select",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Anonymous"}, "value": "anonymous"},
                            {"text": {"type": "plain_text", "text": "Public"}, "value": "public"}
                        ]
                    }
                }
            ]
        }
    )

@app.view("poll_step1")
def handle_poll_step1(ack, body, view, client):
    """Show appropriate fields based on poll type."""
    ack()
    info = json.loads(view["private_metadata"])
    channel_id = info["channel"]
    creator_id = info["user"]
    state = view["state"]["values"]
    p_type = state["type_block"]["poll_type"]["selected_option"]["value"]
    title = state["question_block"]["question_input"]["value"]
    visibility = state["visibility_block"]["visibility_select"]["selected_option"]["value"]
    meta = json.dumps({"channel": channel_id, "user": creator_id, "type": p_type, "title": title, "visibility": visibility})

    if p_type == "vote":
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\nProvide up to 5 options."}}
        ] + [
            {
                "type": "input",
                "block_id": f"option_block_{i}",
                "optional": True,
                "label": {"type": "plain_text", "text": f"Option {i+1}"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"option_input_{i}",
                    "placeholder": {"type": "plain_text", "text": "Type option text here"}
                }
            }
            for i in range(5)
        ]
    else:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\nAdd up to 5 questions."}},
            {
                "type": "input",
                "block_id": "format_block",
                "label": {"type": "plain_text", "text": "Feedback Format"},
                "element": {
                    "type": "static_select",
                    "action_id": "format_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Paragraph"}, "value": "paragraph"},
                        {"text": {"type": "plain_text", "text": "Stars 1-5"}, "value": "stars"}
                    ]
                }
            }
        ] + [
            {
                "type": "input",
                "block_id": f"feedback_q_block_{i}",
                "optional": True,
                "label": {"type": "plain_text", "text": f"Question {i+1}"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"feedback_q_input_{i}",
                    "placeholder": {"type": "plain_text", "text": "Type your question here"}
                }
            }
            for i in range(5)
        ]

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "submit_poll",
            "private_metadata": meta,
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Post Poll"},
            "blocks": blocks
        }
    )
# ─── Submit Poll ───────────────────────────────────────────────────────────────
@app.view("submit_poll")
def handle_poll_submission(ack, body, view, client):
    ack()
    info = json.loads(view["private_metadata"])
    channel_id = info["channel"]
    creator_id = info["user"]
    p_type = info["type"]
    title = info["title"]
    visibility = info.get("visibility", "anonymous")
    state = view["state"]["values"]

    # collect
    opts, fqs = [], []
    f_format = "paragraph"
    for i in range(5):
        val = state.get(f"option_block_{i}", {})\
                   .get(f"option_input_{i}", {})\
                   .get("value")
        if val and p_type == "vote":
            opts.append(val)
    for i in range(5):
        q = state.get(f"feedback_q_block_{i}", {})\
                 .get(f"feedback_q_input_{i}", {})\
                 .get("value")
        if q and p_type == "feedback":
            fqs.append(q)
    if p_type == "feedback":
        sel = state.get("format_block", {}).get("format_select", {}).get("selected_option")
        if sel:
            f_format = sel["value"]

    # validation
    if p_type == "vote" and len(opts) < 2:
        client.chat_postEphemeral(
            channel=channel_id,
            user=creator_id,
            text="❌ You must provide at least *2* vote options."
        )
        return
    if p_type == "feedback" and len(fqs) < 1:
        client.chat_postEphemeral(
            channel=channel_id,
            user=creator_id,
            text="❌ You must provide at least *1* feedback question."
        )
        return

    # store
    poll_data.update({
        "type": p_type,
        "question": title,
        "options": opts,
        "feedback_questions": fqs,
        "feedback_format": f_format,
        "votes": {},
        "tallies": {i: 0 for i in range(len(opts))},
        "feedback_responses": [],
        "creator_id": creator_id,
        "channel_id": channel_id,
        "anonymous": visibility == "anonymous",
        "active": True,
    })

    # build blocks
    if p_type == "vote":
        blocks = [
            {"type": "section",
             "text": {"type": "mrkdwn", "text": f"*📊 {title}*"}},
            {"type": "actions",
             "elements": [
                 {
                   "type": "button",
                   "text": {"type": "plain_text", "text": opt},
                   "value": str(i),
                   "action_id": f"vote_{i}"
                 }
                 for i, opt in enumerate(opts)
             ]}
        ]
    else:
        blocks = [
            {"type": "section",
             "text": {"type": "mrkdwn", "text": f"*✏️ {title}*"}},
            {"type": "actions",
             "elements": [
                 {
                   "type": "button",
                   "text": {"type": "plain_text", "text": "Submit Feedback"},
                   "action_id": "open_feedback"
                 }
             ]}
        ]

    # post the poll
    client.chat_postMessage(channel=channel_id, text=title, blocks=blocks)

    # DM creator
    try:
        im = client.conversations_open(users=creator_id)
        dm = im["channel"]["id"]
        client.chat_postMessage(channel=dm, text="✅ Your poll has been posted.")
    except Exception as e:
        print(f"Error sending confirmation DM: {e}")

# ─── Voting ───────────────────────────────────────────────────────────────────
@app.action(re.compile(r"^vote_\d$"))
def handle_vote(ack, body, action, client):
    ack()
    if not poll_data["active"] or poll_data["type"] != "vote":
        client.chat_postEphemeral(channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="❌ This poll is closed or not a vote poll."
        )
        return

    user = body["user"]["id"]
    choice = int(action["action_id"].split("_")[1])
    ch   = body["channel"]["id"]

    if user in poll_data["votes"]:
        client.chat_postEphemeral(channel=ch, user=user,
            text="✅ You’ve already voted!")
        return

    poll_data["votes"][user] = choice
    poll_data["tallies"][choice] += 1

    rpt = f"🗳 Vote recorded for *{poll_data['options'][choice]}*\n\n*📊 Current Results:*"
    for i, opt in enumerate(poll_data["options"]):
        rpt += f"\n• {opt}: {poll_data['tallies'][i]}"

    client.chat_postEphemeral(channel=ch, user=user, text=rpt)

# ─── Open Feedback Modal ─────────────────────────────────────────────────────
@app.action("open_feedback")
def open_feedback_modal(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    questions  = poll_data["feedback_questions"]

    # add a header + one input per question
    blocks = [
        {
          "type": "section",
          "text": {"type": "mrkdwn", "text": "*Please answer the following:*"}
        }
    ]

    for i, q in enumerate(questions):
        if poll_data.get("feedback_format") == "stars":
            element = {
                "type": "static_select",
                "action_id": f"resp_input_{i}",
                "options": [
                    {"text": {"type": "plain_text", "text": "⭐"}, "value": "1"},
                    {"text": {"type": "plain_text", "text": "⭐⭐"}, "value": "2"},
                    {"text": {"type": "plain_text", "text": "⭐⭐⭐"}, "value": "3"},
                    {"text": {"type": "plain_text", "text": "⭐⭐⭐⭐"}, "value": "4"},
                    {"text": {"type": "plain_text", "text": "⭐⭐⭐⭐⭐"}, "value": "5"}
                ]
            }
        else:
            element = {
                "type": "plain_text_input",
                "action_id": f"resp_input_{i}",
                "placeholder": {"type": "plain_text", "text": "Your answer here"}
            }

        blocks.append({
            "type": "input",
            "block_id": f"resp_block_{i}",
            "label": {"type": "plain_text", "text": q},
            "element": element
        })

    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "submit_feedback",
            "title": {"type": "plain_text", "text": "Submit Feedback"},
            "submit": {"type": "plain_text", "text": "Send"},
            "blocks": blocks
        }
    )

# ─── Handle Feedback ─────────────────────────────────────────────────────────
@app.view("submit_feedback")
def handle_feedback_submission(ack, body, view, client):
    ack()
    user_id = body["user"]["id"]
    state   = view["state"]["values"]
    answers = []

    for i in range(len(poll_data["feedback_questions"])):
        if poll_data.get("feedback_format") == "stars":
            ans = state[f"resp_block_{i}"][f"resp_input_{i}"]["selected_option"]["value"]
        else:
            ans = state[f"resp_block_{i}"][f"resp_input_{i}"]["value"]
        answers.append(ans)

    poll_data["feedback_responses"].append({
        "user": user_id,
        "answers": answers
    })

    try:
        client.chat_postEphemeral(
            channel=poll_data["channel_id"],
            user=user_id,
            text="✅ Your feedback has been submitted."
        )
    except Exception as e:
        print(f"Error sending feedback confirmation: {e}")

# ─── /pollresults ────────────────────────────────────────────────────────────
@app.command("/pollresults")
def show_poll_results(ack, body, client):
    ack()
    ch, usr = body["channel_id"], body["user_id"]

    if not poll_data["active"]:
        client.chat_postEphemeral(channel=ch, user=usr,
                                  text="❗ No active poll right now.")
        return

    if poll_data["type"] == "vote":
        text = f"*📊 Results for:* {poll_data['question']}\n"
        total = sum(poll_data["tallies"].values())
        max_votes = max(poll_data["tallies"].values()) if total else 0
        for i, opt in enumerate(poll_data["options"]):
            tally = poll_data["tallies"][i]
            pct = int(round((tally / total) * 100)) if total else 0
            line = f"• {opt}: {tally} ({pct}%)"
            if tally == max_votes and total:
                line = f"*{line}*"
            text += line + "\n"
        if not poll_data.get("anonymous"):
            text += "\nVotes:\n"
            for user, choice in poll_data["votes"].items():
                text += f"• <@{user}> → {poll_data['options'][choice]}\n"
    else:
        text = f"*✏️ Feedback for:* {poll_data['question']}\n"
        if poll_data.get("anonymous"):
            if poll_data.get("feedback_format") == "stars":
                for idx, q in enumerate(poll_data["feedback_questions"]):
                    vals = [int(r["answers"][idx]) for r in poll_data["feedback_responses"]]
                    avg = sum(vals) / len(vals) if vals else 0
                    text += f"• *{q}*: average {avg:.1f}/5\n"
            else:
                for idx, q in enumerate(poll_data["feedback_questions"]):
                    text += f"\n*{q}*\n"
                    for resp in poll_data["feedback_responses"]:
                        text += f"    • {resp['answers'][idx]}\n"
        else:
            for resp in poll_data["feedback_responses"]:
                text += f"\n— <@{resp['user']}>'s answers:\n"
                for q, a in zip(poll_data["feedback_questions"], resp["answers"]):
                    text += f"    • *{q}*: {a}\n"

    client.chat_postEphemeral(channel=ch, user=usr, text=text)

# ─── /closepoll ──────────────────────────────────────────────────────────────
@app.command("/closepoll")
def close_poll(ack, body, client):
    ack()
    usr, ch = body["user_id"], body["channel_id"]

    if not poll_data["active"]:
        client.chat_postEphemeral(
            channel=ch,
            user=usr,
            text="❗ No active poll to close."
        )
        return

    if poll_data["creator_id"] != usr:
        client.chat_postEphemeral(
            channel=ch,
            user=usr,
            text="❌ Only the poll creator can close it."
        )
        return

    poll_data["active"] = False
    if poll_data["type"] == "vote":
        final = f"✅ Poll *{poll_data['question']}* closed. Final results:\n"
        total = sum(poll_data["tallies"].values())
        max_votes = max(poll_data["tallies"].values()) if total else 0
        for i, opt in enumerate(poll_data["options"]):
            tally = poll_data["tallies"][i]
            pct = int(round((tally / total) * 100)) if total else 0
            line = f"• {opt}: {tally} ({pct}%)"
            if tally == max_votes and total:
                line = f"*{line}*"
            final += line + "\n"
        if not poll_data.get("anonymous"):
            final += "\nVotes:\n"
            for user, choice in poll_data["votes"].items():
                final += f"• <@{user}> → {poll_data['options'][choice]}\n"
    else:
        final = f"✅ Feedback poll *{poll_data['question']}* closed. Collected feedback:\n"
        if poll_data.get("anonymous"):
            if poll_data.get("feedback_format") == "stars":
                for idx, q in enumerate(poll_data["feedback_questions"]):
                    vals = [int(r["answers"][idx]) for r in poll_data["feedback_responses"]]
                    avg = sum(vals) / len(vals) if vals else 0
                    final += f"• *{q}*: average {avg:.1f}/5\n"
            else:
                for idx, q in enumerate(poll_data["feedback_questions"]):
                    final += f"\n*{q}*\n"
                    for resp in poll_data["feedback_responses"]:
                        final += f"    • {resp['answers'][idx]}\n"
        else:
            for resp in poll_data["feedback_responses"]:
                final += f"\n— <@{resp['user']}>'s answers:\n"
                for q, a in zip(poll_data["feedback_questions"], resp["answers"]):
                    final += f"    • *{q}*: {a}\n"

    client.chat_postMessage(channel=ch, text=final)

# ─── Routes ───────────────────────────────────────────────────────────────────
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

@flask_app.route("/", methods=["GET"])
def index():
    return "✅ HFC Slack Bot is running."

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
