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
    "feedback_formats": [],
    "feedback_kinds": [],
    "question_options": [],
    "vote_tallies": [],
    "votes": {},
    "tallies": {},
    "feedback_responses": [],
    "creator_id": None,
    "channel_id": None,
    "anonymous": True,
    "multi": False,
    "active": False,
}

# Helper to build the blended poll configuration blocks
def build_blended_blocks(title, q_types=None, state=None):
    """Return block kit structure for blended poll config."""
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*\nConfigure up to 10 questions."},
        }
    ]
    q_types = q_types or {}
    state = state or {}
    for i in range(10):
        sel = q_types.get(str(i))
        element = {
            "type": "static_select",
            "action_id": f"q_type_select_{i}",
            "options": [
                {"text": {"type": "plain_text", "text": "Feedback"}, "value": "feedback"},
                {"text": {"type": "plain_text", "text": "Vote"}, "value": "vote"},
            ],
        }
        if sel:
            element["initial_option"] = {
                "text": {"type": "plain_text", "text": "Feedback" if sel == "feedback" else "Vote"},
                "value": sel,
            }
        blocks.append({
            "type": "input",
            "block_id": f"q_type_block_{i}",
            "optional": True,
            "label": {"type": "plain_text", "text": f"Type for Question {i+1}"},
            "element": element,
        })
        if sel:
            q_text = state.get(f"q_block_{i}", {}).get(f"q_input_{i}", {}).get("value")
            q_element = {
                "type": "plain_text_input",
                "action_id": f"q_input_{i}",
                "placeholder": {"type": "plain_text", "text": "Type your question here"},
            }
            if q_text:
                q_element["initial_value"] = q_text
            blocks.append({
                "type": "input",
                "block_id": f"q_block_{i}",
                "optional": True,
                "label": {"type": "plain_text", "text": f"Question {i+1}"},
                "element": q_element,
            })

            fmt_sel = state.get(f"format_block_{i}", {}).get(f"format_select_{i}", {}).get("selected_option")
            fmt_element = {
                "type": "static_select",
                "action_id": f"format_select_{i}",
                "options": [
                    {"text": {"type": "plain_text", "text": "Paragraph"}, "value": "paragraph"},
                    {"text": {"type": "plain_text", "text": "Stars 1-5"}, "value": "stars"},
                ],
            }
            if fmt_sel:
                fmt_element["initial_option"] = fmt_sel
            blocks.append({
                "type": "input",
                "block_id": f"format_block_{i}",
                "optional": True,
                "label": {"type": "plain_text", "text": f"Format for Question {i+1}"},
                "element": fmt_element,
            })

            if sel == "vote":
                for j in range(5):
                    val = state.get(f"opt_block_{i}_{j}", {}).get(f"opt_input_{i}_{j}", {}).get("value")
                    opt_el = {
                        "type": "plain_text_input",
                        "action_id": f"opt_input_{i}_{j}",
                        "placeholder": {"type": "plain_text", "text": "Type option text here"},
                    }
                    if val:
                        opt_el["initial_value"] = val
                    blocks.append({
                        "type": "input",
                        "block_id": f"opt_block_{i}_{j}",
                        "optional": True,
                        "label": {"type": "plain_text", "text": f"Q{i+1} Option {j+1}"},
                        "element": opt_el,
                    })
    return blocks


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
                            {"text": {"type": "plain_text", "text": "Blended"}, "value": "blended"},
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
    info = json.loads(view["private_metadata"])
    channel_id = info["channel"]
    creator_id = info["user"]
    state = view["state"]["values"]
    p_type = state["type_block"]["poll_type"]["selected_option"]["value"]
    title = state["question_block"]["question_input"]["value"]
    visibility = state["visibility_block"]["visibility_select"]["selected_option"]["value"]
    meta_data = {"channel": channel_id, "user": creator_id, "type": p_type, "title": title, "visibility": visibility}
    if p_type == "blended":
        meta_data["q_types"] = {}
    meta = json.dumps(meta_data)

    if p_type == "vote":
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\nProvide up to 10 options."}}
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
            for i in range(10)
        ]
        blocks.append({
            "type": "input",
            "block_id": "multi_block",
            "optional": True,
            "label": {"type": "plain_text", "text": "Allow multiple selections?"},
            "element": {
                "type": "checkboxes",
                "action_id": "multi_select",
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "Users can select multiple options"},
                        "value": "allow_multi"
                    }
                ]
            }
        })
    elif p_type == "feedback":
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\nAdd up to 10 questions."}}
        ]
        for i in range(10):
            blocks.extend([
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
                },
                {
                    "type": "input",
                    "block_id": f"kind_block_{i}",
                    "optional": True,
                    "label": {"type": "plain_text", "text": f"Type for Question {i+1}"},
                    "element": {
                        "type": "static_select",
                        "action_id": f"kind_select_{i}",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Feedback"}, "value": "feedback"},
                            {"text": {"type": "plain_text", "text": "Vote"}, "value": "vote"}
                        ]
                    }
                },
                {
                    "type": "input",
                    "block_id": f"format_block_{i}",
                    "optional": True,
                    "label": {"type": "plain_text", "text": f"Format for Question {i+1}"},
                    "element": {
                        "type": "static_select",
                        "action_id": f"format_select_{i}",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Paragraph"}, "value": "paragraph"},
                            {"text": {"type": "plain_text", "text": "Stars 1-5"}, "value": "stars"}
                        ]
                    }
                }
            ])
    else:  # blended poll
        q_types = meta_data.get("q_types", {})
        blocks = build_blended_blocks(title, q_types)

    ack(
        response_action="update",
        view={
            "type": "modal",
            "callback_id": "submit_poll",
            "private_metadata": meta,
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Post Poll"},
            "blocks": blocks,
        },
    )

# ─── Handle question type selection for blended polls ─────────────────────────
@app.action(re.compile(r"^q_type_select_\d+$"))
def update_blended_question(ack, body, client):
    """Update blended poll modal when a question type is chosen."""
    view = body["view"]
    action = body["actions"][0]
    idx = int(action["action_id"].split("_")[-1])
    sel_type = action["selected_option"]["value"]
    meta = json.loads(view["private_metadata"])
    q_types = meta.get("q_types", {})
    q_types[str(idx)] = sel_type
    meta["q_types"] = q_types

    state = view.get("state", {}).get("values", {})
    blocks = build_blended_blocks(meta["title"], q_types, state)

    ack()
    client.views_update(
        view_id=view["id"],
        hash=view.get("hash"),
        view={
            "type": "modal",
            "callback_id": "submit_poll",
            "private_metadata": json.dumps(meta),
            "title": {"type": "plain_text", "text": "Create a Poll"},
            "submit": {"type": "plain_text", "text": "Post Poll"},
            "blocks": blocks,
        },
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
    opts, fqs, f_formats, f_kinds = [], [], [], []
    question_opts = []
    if p_type == "vote":
        for i in range(10):
            val = state.get(f"option_block_{i}", {})\
                       .get(f"option_input_{i}", {})\
                       .get("value")
            if val:
                opts.append(val)
    elif p_type == "feedback":
        for i in range(10):
            q = state.get(f"feedback_q_block_{i}", {})\
                     .get(f"feedback_q_input_{i}", {})\
                     .get("value")
            if q:
                fqs.append(q)
                kind_sel = state.get(f"kind_block_{i}", {}).get(f"kind_select_{i}", {}).get("selected_option")
                kind = kind_sel["value"] if kind_sel else "feedback"
                f_kinds.append(kind)
                sel = state.get(f"format_block_{i}", {}).get(f"format_select_{i}", {}).get("selected_option")
                fmt = sel["value"] if sel else "paragraph"
                f_formats.append(fmt)
    else:  # blended
        for i in range(10):
            ksel = state.get(f"q_type_block_{i}", {}).get(f"q_type_select_{i}", {}).get("selected_option")
            qtext = state.get(f"q_block_{i}", {}).get(f"q_input_{i}", {}).get("value")
            if not (ksel and qtext):
                continue
            kind = ksel["value"]
            fqs.append(qtext)
            f_kinds.append(kind)
            if kind == "feedback":
                sel = state.get(f"format_block_{i}", {}).get(f"format_select_{i}", {}).get("selected_option")
                fmt = sel["value"] if sel else "paragraph"
                f_formats.append(fmt)
                question_opts.append([])
            else:  # vote question
                opts_list = []
                for j in range(5):
                    val = state.get(f"opt_block_{i}_{j}", {}).get(f"opt_input_{i}_{j}", {}).get("value")
                    if val:
                        opts_list.append(val)
                question_opts.append(opts_list)
                f_formats.append(None)

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
    if p_type == "blended" and len(fqs) < 1:
        client.chat_postEphemeral(
            channel=channel_id,
            user=creator_id,
            text="❌ You must provide at least *1* question."
        )
        return
    if p_type == "blended":
        for idx, k in enumerate(f_kinds):
            if k == "vote" and len(question_opts[idx]) < 2:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=creator_id,
                    text=f"❌ Question {idx+1} needs at least 2 options."
                )
                return

    allow_multi = False
    if p_type == "vote":
        sel_opts = state.get("multi_block", {}).get("multi_select", {}).get("selected_options")
        allow_multi = bool(sel_opts)

    # store
    if p_type == "blended":
        vt = []
        for kind, opts_list in zip(f_kinds, question_opts):
            if kind == "vote":
                vt.append({i: 0 for i in range(len(opts_list))})
            else:
                vt.append({})
        poll_data.update({
            "type": p_type,
            "question": title,
            "options": [],
            "feedback_questions": fqs,
            "feedback_formats": f_formats,
            "feedback_kinds": f_kinds,
            "question_options": question_opts,
            "vote_tallies": vt,
            "votes": {},
            "tallies": {},
            "feedback_responses": [],
            "creator_id": creator_id,
            "channel_id": channel_id,
            "anonymous": visibility == "anonymous",
            "multi": False,
            "active": True,
        })
    else:
        poll_data.update({
            "type": p_type,
            "question": title,
            "options": opts,
            "feedback_questions": fqs,
            "feedback_formats": f_formats,
            "feedback_kinds": f_kinds,
            "question_options": [],
            "vote_tallies": [{"yes": 0, "no": 0} for _ in range(len(fqs))],
            "votes": {},
            "tallies": {i: 0 for i in range(len(opts))},
            "feedback_responses": [],
            "creator_id": creator_id,
            "channel_id": channel_id,
            "anonymous": visibility == "anonymous",
            "multi": allow_multi,
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
    else:  # feedback or blended
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

    if poll_data.get("multi"):
        choices = poll_data["votes"].setdefault(user, set())
        if choice in choices:
            client.chat_postEphemeral(channel=ch, user=user,
                text="✅ You’ve already voted for this option!")
            return
        choices.add(choice)
    else:
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
        fmt = poll_data.get("feedback_formats", ["paragraph"] * len(questions))[i]
        kind = poll_data.get("feedback_kinds", ["feedback"] * len(questions))[i]
        if kind == "vote":
            q_opts = poll_data.get("question_options", [])
            if q_opts and i < len(q_opts) and q_opts[i]:
                element = {
                    "type": "static_select",
                    "action_id": f"resp_input_{i}",
                    "options": [
                        {"text": {"type": "plain_text", "text": opt}, "value": str(idx)}
                        for idx, opt in enumerate(q_opts[i])
                    ]
                }
            else:
                element = {
                    "type": "static_select",
                    "action_id": f"resp_input_{i}",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Yes"}, "value": "yes"},
                        {"text": {"type": "plain_text", "text": "No"}, "value": "no"}
                    ]
                }
        elif fmt == "stars":
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

    q_types = poll_data.get("feedback_kinds", ["feedback"] * len(poll_data["feedback_questions"]))
    q_opts_all = poll_data.get("question_options", [])
    for i in range(len(poll_data["feedback_questions"])):
        kind = q_types[i]
        fmt = poll_data.get("feedback_formats", ["paragraph"])[i]
        if kind == "vote":
            sel = state[f"resp_block_{i}"][f"resp_input_{i}"]["selected_option"]["value"]
            vt = poll_data.get("vote_tallies", [])
            if q_opts_all and i < len(q_opts_all) and q_opts_all[i]:
                idx = int(sel)
                if i < len(vt):
                    vt[i][idx] = vt[i].get(idx, 0) + 1
                ans = idx
            else:
                if i < len(vt):
                    vt[i][sel] = vt[i].get(sel, 0) + 1
                ans = sel
        else:
            if fmt == "stars":
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
                if poll_data.get("multi"):
                    opts = ", ".join(poll_data['options'][c] for c in sorted(choice))
                    text += f"• <@{user}> → {opts}\n"
                else:
                    text += f"• <@{user}> → {poll_data['options'][choice]}\n"
    else:
        text = f"*✏️ Feedback for:* {poll_data['question']}\n"
        q_types = poll_data.get("feedback_kinds", ["feedback"] * len(poll_data["feedback_questions"]))
        q_opts_all = poll_data.get("question_options", [])
        if poll_data.get("anonymous"):
            for idx, q in enumerate(poll_data["feedback_questions"]):
                kind = q_types[idx]
                fmt = poll_data.get("feedback_formats", ["paragraph"])[idx]
                if kind == "vote":
                    tallies = poll_data.get("vote_tallies", [])
                    opts = q_opts_all[idx] if q_opts_all and idx < len(q_opts_all) else None
                    if opts:
                        counts = [tallies[idx].get(i, 0) for i in range(len(opts))] if idx < len(tallies) else [0]*len(opts)
                        result = ", ".join(f"{opt} {cnt}" for opt, cnt in zip(opts, counts))
                        text += f"• *{q}*: {result}\n"
                    else:
                        yes = tallies[idx]["yes"] if idx < len(tallies) else 0
                        no = tallies[idx]["no"] if idx < len(tallies) else 0
                        text += f"• *{q}*: yes {yes}, no {no}\n"
                elif fmt == "stars":
                    vals = [int(r["answers"][idx]) for r in poll_data["feedback_responses"]]
                    avg = sum(vals) / len(vals) if vals else 0
                    text += f"• *{q}*: average {avg:.1f}/5\n"
                else:
                    text += f"\n*{q}*\n"
                    for resp in poll_data["feedback_responses"]:
                        text += f"    • {resp['answers'][idx]}\n"
        else:
            for resp in poll_data["feedback_responses"]:
                text += f"\n— <@{resp['user']}>'s answers:\n"
                for idx, (q, a) in enumerate(zip(poll_data["feedback_questions"], resp["answers"])):
                    kind = q_types[idx]
                    fmt = poll_data.get("feedback_formats", ["paragraph"])[idx]
                    if kind == "vote":
                        opts = q_opts_all[idx] if q_opts_all and idx < len(q_opts_all) else None
                        if opts:
                            text += f"    • *{q}*: {opts[int(a)]}\n"
                        else:
                            text += f"    • *{q}*: {a}\n"
                    elif fmt == "stars":
                        text += f"    • *{q}*: {a}/5\n"
                    else:
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
                if poll_data.get("multi"):
                    opts = ", ".join(poll_data['options'][c] for c in sorted(choice))
                    final += f"• <@{user}> → {opts}\n"
                else:
                    final += f"• <@{user}> → {poll_data['options'][choice]}\n"
    else:
        final = f"✅ Feedback poll *{poll_data['question']}* closed. Collected feedback:\n"
        q_types = poll_data.get("feedback_kinds", ["feedback"] * len(poll_data["feedback_questions"]))
        q_opts_all = poll_data.get("question_options", [])
        if poll_data.get("anonymous"):
            for idx, q in enumerate(poll_data["feedback_questions"]):
                kind = q_types[idx]
                fmt = poll_data.get("feedback_formats", ["paragraph"])[idx]
                if kind == "vote":
                    tallies = poll_data.get("vote_tallies", [])
                    opts = q_opts_all[idx] if q_opts_all and idx < len(q_opts_all) else None
                    if opts:
                        counts = [tallies[idx].get(i, 0) for i in range(len(opts))] if idx < len(tallies) else [0]*len(opts)
                        result = ", ".join(f"{opt} {cnt}" for opt, cnt in zip(opts, counts))
                        final += f"• *{q}*: {result}\n"
                    else:
                        yes = tallies[idx]["yes"] if idx < len(tallies) else 0
                        no = tallies[idx]["no"] if idx < len(tallies) else 0
                        final += f"• *{q}*: yes {yes}, no {no}\n"
                elif fmt == "stars":
                    vals = [int(r["answers"][idx]) for r in poll_data["feedback_responses"]]
                    avg = sum(vals) / len(vals) if vals else 0
                    final += f"• *{q}*: average {avg:.1f}/5\n"
                else:
                    final += f"\n*{q}*\n"
                    for resp in poll_data["feedback_responses"]:
                        final += f"    • {resp['answers'][idx]}\n"
        else:
            for resp in poll_data["feedback_responses"]:
                final += f"\n— <@{resp['user']}>'s answers:\n"
                for idx, (q, a) in enumerate(zip(poll_data["feedback_questions"], resp["answers"])):
                    kind = q_types[idx]
                    fmt = poll_data.get("feedback_formats", ["paragraph"])[idx]
                    if kind == "vote":
                        opts = q_opts_all[idx] if q_opts_all and idx < len(q_opts_all) else None
                        if opts:
                            final += f"    • *{q}*: {opts[int(a)]}\n"
                        else:
                            final += f"    • *{q}*: {a}\n"
                    elif fmt == "stars":
                        final += f"    • *{q}*: {a}/5\n"
                    else:
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
