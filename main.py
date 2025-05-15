import os
import re
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request

# ── App setup ─────────────────────────────────────────────────────────────────
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# In-memory store: channel → poll data
polls: dict[str, dict] = {}

# ── /poll: open the “new poll” modal ──────────────────────────────────────────
@app.command("/poll")
def open_poll_modal(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "poll_modal",
            "private_metadata": body["channel_id"],
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Create"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                # Question text
                {
                    "type": "input",
                    "block_id": "question_block",
                    "label": {"type": "plain_text", "text": "Question"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "question_input"
                    },
                },
                # Poll type selector
                {
                    "type": "input",
                    "block_id": "type_block",
                    "label": {"type": "plain_text", "text": "Poll Type"},
                    "element": {
                        "type": "static_select",
                        "action_id": "type_select",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "🔘 Voting"},
                                "value": "voting"
                            },
                            {
                                "text": {"type": "plain_text", "text": "📝 Feedback"},
                                "value": "feedback"
                            },
                        ],
                        "initial_option": {
                            "text": {"type": "plain_text", "text": "🔘 Voting"},
                            "value": "voting"
                        }
                    }
                },
                # Visibility selector
                {
                    "type": "input",
                    "block_id": "vis_block",
                    "label": {"type": "plain_text", "text": "Visibility"},
                    "element": {
                        "type": "static_select",
                        "action_id": "vis_select",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "👁️ Public"},
                                "value": "public"
                            },
                            {
                                "text": {"type": "plain_text", "text": "🕵️ Anonymous"},
                                "value": "anonymous"
                            },
                        ],
                        "initial_option": {
                            "text": {"type": "plain_text", "text": "👁️ Public"},
                            "value": "public"
                        }
                    }
                },
            ]
            # If voting: let them enter up to 5 options
            + [
                {
                    "type": "input",
                    "block_id": f"option_{i}_block",
                    "optional": i >= 2,
                    "label": {"type": "plain_text", "text": f"Option {i+1}"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"option_{i}_input"
                    },
                }
                for i in range(5)
            ]
        },
    )

# ── Handle the modal submission ────────────────────────────────────────────────
@app.view("poll_modal")
def handle_poll_modal(ack, body, view, client):
    ack()
    user_id = body["user"]["id"]
    channel_id = view["private_metadata"]
    vals = view["state"]["values"]

    question = vals["question_block"]["question_input"]["value"].strip()
    poll_type = vals["type_block"]["type_select"]["selected_option"]["value"]
    visibility = vals["vis_block"]["vis_select"]["selected_option"]["value"]

    # Gather voting options if voting poll
    options = []
    if poll_type == "voting":
        for i in range(5):
            opt = vals[f"option_{i}_block"][f"option_{i}_input"]["value"].strip()
            if i < 2 or opt:
                options.append(opt)

    # Build the blocks for the posted message
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{question}*"}}]
    if poll_type == "voting":
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "block_id": "poll_buttons",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": opt},
                    "action_id": f"vote_{i}",
                    "value": str(i),
                }
                for i, opt in enumerate(options)
            ]
        })
    else:
        # feedback poll
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "block_id": "feedback_buttons",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "📝 Give Feedback"},
                "action_id": "give_feedback"
            }]
        })

    resp = client.chat_postMessage(channel=channel_id, blocks=blocks)
    ts = resp["ts"]

    # store poll metadata
    polls[channel_id] = {
        "question": question,
        "type": poll_type,
        "visibility": visibility,
        "options": options,      # voting only
        "votes": {},             # user → choice index
        "feedback": [],          # list of (user, text)
        "creator": user_id,
        "message_ts": ts,
        "closed": False,
    }

    # confirm to creator
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="✅ Your poll has been posted!"
    )

# ── Voting handler ────────────────────────────────────────────────────────────
@app.action(re.compile(r"^vote_\d+$"))
def handle_vote(ack, body, client):
    ack()
    channel = body["channel"]["id"]
    user = body["user"]["id"]
    idx = int(body["actions"][0]["value"])
    poll = polls.get(channel)

    if not poll or poll["closed"] or poll["type"] != "voting":
        client.chat_postEphemeral(channel=channel, user=user,
            text="⚠️ No active voting poll here.")
        return

    # record
    poll["votes"][user] = idx

    # tally
    counts = [0]*len(poll["options"])
    for v in poll["votes"].values():
        counts[v] += 1

    # build results text
    lines = "\n".join(
        f"*{poll['options'][i]}*: {counts[i]} vote{'s' if counts[i]!=1 else ''}"
        for i in range(len(poll["options"]))
    )
    client.chat_postEphemeral(
        channel=channel, user=user,
        text=f"🗳 You voted *{poll['options'][idx]}*\n\n*Current results:*\n{lines}"
    )

# ── Feedback button opens a modal ────────────────────────────────────────────
@app.action("give_feedback")
def open_feedback_modal(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    channel = body["channel"]["id"]
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "feedback_modal",
            "private_metadata": channel,
            "title": {"type": "plain_text", "text": "Submit Feedback"},
            "submit": {"type": "plain_text", "text": "Send"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "fb_block",
                    "label": {"type": "plain_text", "text": "Your feedback"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "fb_input",
                        "multiline": True
                    }
                }
            ]
        }
    )

# ── Handle feedback submission ───────────────────────────────────────────────
@app.view("feedback_modal")
def handle_feedback_submission(ack, body, view, client):
    ack()
    user = body["user"]["id"]
    channel = view["private_metadata"]
    text = view["state"]["values"]["fb_block"]["fb_input"]["value"].strip()
    poll = polls.get(channel)

    if not poll or poll["closed"] or poll["type"] != "feedback":
        client.chat_postEphemeral(channel=channel, user=user,
            text="⚠️ No active feedback poll here.")
        return

    # record
    poll["feedback"].append((user, text))

    # confirmation
    client.chat_postEphemeral(channel=channel, user=user,
        text="✅ Thanks for your feedback!")

# ── /pollresults: show live tallies or feedback ───────────────────────────────
@app.command("/pollresults")
def show_results(ack, body, client):
    ack()
    ch = body["channel_id"]
    usr = body["user_id"]
    poll = polls.get(ch)
    if not poll:
        client.chat_postEphemeral(channel=ch, user=usr,
            text="⚠️ No poll here.")
        return

    if poll["type"] == "voting":
        counts = [0]*len(poll["options"])
        for v in poll["votes"].values():
            counts[v] += 1
        lines = "\n".join(
            f"*{poll['options'][i]}*: {counts[i]} vote{'s' if counts[i]!=1 else ''}"
            for i in range(len(poll["options"]))
        )
        text = f"*{poll['question']}*\n\n{lines}"

    else:
        # feedback
        entries = []
        for u, resp in poll["feedback"]:
            if poll["visibility"] == "public":
                user_info = client.users_info(user=u)
                name = user_info["user"]["real_name"] or user_info["user"]["name"]
                entries.append(f"*{name}*: {resp}")
            else:
                entries.append(f"• {resp}")
        if not entries:
            text = "_No feedback submitted yet._"
        else:
            text = "*Feedback so far:*\n" + "\n".join(entries)

    client.chat_postEphemeral(channel=ch, user=usr, text=text)

# ── /closepoll: freeze and publish final results ─────────────────────────────
@app.command("/closepoll")
def close_poll(ack, body, client):
    ack()
    ch = body["channel_id"]
    usr = body["user_id"]
    poll = polls.get(ch)

    if not poll:
        client.chat_postEphemeral(channel=ch, user=usr,
            text="⚠️ No poll here.")
        return
    if poll["creator"] != usr:
        client.chat_postEphemeral(channel=ch, user=usr,
            text="⚠️ Only the creator can close it.")
        return

    poll["closed"] = True

    # build final text exactly as in /pollresults
    if poll["type"] == "voting":
        counts = [0]*len(poll["options"])
        for v in poll["votes"].values():
            counts[v] += 1
        body_text = "\n".join(
            f"*{poll['options'][i]}*: {counts[i]} vote{'s' if counts[i]!=1 else ''}"
            for i in range(len(poll["options"]))
        )
        final = f"*{poll['question']}* _(closed)_\n\n{body_text}"
    else:
        entries = []
        for u, resp in poll["feedback"]:
            if poll["visibility"] == "public":
                info = client.users_info(user=u)["user"]
                name = info["real_name"] or info["name"]
                entries.append(f"*{name}*: {resp}")
            else:
                entries.append(f"• {resp}")
        if not entries:
            final = f"*{poll['question']}* _(closed)_\n\n_No feedback submitted._"
        else:
            final = "*Feedback (closed)*\n\n" + "\n".join(entries)

    # update original message
    client.chat_update(
        channel=ch,
        ts=poll["message_ts"],
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": final}}]
    )

    client.chat_postEphemeral(channel=ch, user=usr,
        text="✅ Poll closed and results published.")

# ── Event receiver ────────────────────────────────────────────────────────────
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

if __name__ == "__main__":
    flask_app.run(port=3000)
